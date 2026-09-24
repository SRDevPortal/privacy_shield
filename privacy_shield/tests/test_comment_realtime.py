import unittest
from unittest.mock import MagicMock, patch
import frappe
from frappe.core.doctype.comment.comment import Comment
from privacy_shield.private_comments import PrivacyComment


class CommentRealtimeTests(unittest.TestCase):
    def doc(self, **changes):
        fields = dict(doctype="Comment", name="C1", reference_doctype="Sales Invoice", reference_name="SI1", comment_type="Comment", content="9876543210", owner="author", subject="9876543210")
        fields.update(changes)
        doc = object.__new__(PrivacyComment)
        doc.__dict__.update(fields)
        return doc

    def test_protected_payload_has_only_source_identity_for_all_actors(self):
        with patch.object(frappe, "conf", {"privacy_shield_desk_enabled": True}), patch.object(frappe, "publish_realtime") as publish:
            for actor in ("restricted", "full"):
                for action in ("add", "update", "delete"):
                    self.doc(owner=actor).notify_change(action)
                    args, kwargs = publish.call_args
                    self.assertEqual(args, ("privacy_shield_history_changed", {"doctype": "Sales Invoice", "name": "SI1"}))
                    self.assertEqual(kwargs, {"doctype": "Sales Invoice", "docname": "SI1", "after_commit": True})
                    self.assertNotIn("9876543210", str(publish.call_args))

    def test_gate_off_and_unrelated_source_delegate_to_core(self):
        with patch.object(Comment, "notify_change") as core:
            with patch.object(frappe, "conf", {}):
                self.doc().notify_change("add")
                core.assert_called_once_with("add")
            core.reset_mock()
            with patch.object(frappe, "conf", {"privacy_shield_desk_enabled": True}):
                self.doc(reference_doctype="ToDo").notify_change("delete")
                core.assert_called_once_with("delete")

    def test_missing_reference_and_unsupported_type_do_not_broadcast(self):
        with patch.object(frappe, "conf", {"privacy_shield_desk_enabled": True}), patch.object(frappe, "publish_realtime") as publish:
            self.doc(reference_name=None).notify_change("add")
            self.doc(comment_type="Info").notify_change("add")
            publish.assert_not_called()

    def test_native_realtime_queues_only_safe_event_and_rollback_clears_it(self):
        from frappe.realtime import publish_realtime, clear_realtime_log
        db = MagicMock()
        with patch.object(frappe, "conf", {"privacy_shield_desk_enabled": True}), patch.object(frappe.local, "db", db, create=True), patch.object(frappe.local, "_realtime_log", [], create=True), patch.object(frappe, "publish_realtime", publish_realtime), patch("frappe.realtime.emit_via_redis") as emit:
            self.doc().notify_change("add")
            self.assertEqual(len(frappe.local._realtime_log), 1)
            event, payload, room = frappe.local._realtime_log[0]
            self.assertEqual(event, "privacy_shield_history_changed")
            self.assertEqual(room, "doc:Sales Invoice/SI1")
            self.assertNotIn("9876543210", str(payload))
            emit.assert_not_called()
            clear_realtime_log()
            self.assertFalse(hasattr(frappe.local, "_realtime_log"))
            frappe.local._realtime_log = []
