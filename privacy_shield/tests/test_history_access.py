import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import frappe
from privacy_shield import history_access as history


class HistoryAccessTests(unittest.TestCase):
    def setUp(self):
        for item in (patch.object(frappe.local, "flags", frappe._dict(in_test=True), create=True),
                     patch.object(frappe, "conf", {"privacy_shield_desk_enabled": True}),
                     patch("privacy_shield.policy.current_capabilities", return_value=SimpleNamespace(view_full=False))):
            item.start()
            self.addCleanup(item.stop)

    def test_scoped_history_denial_cannot_fall_back_to_share(self):
        for dt, field in history.HISTORY_FIELDS.items():
            with self.assertRaises(frappe.PermissionError):
                history.has_permission(frappe._dict(doctype=dt, **{field: "Sales Invoice"}), user="agent")
            if dt != "MCP Audit Log":
                self.assertIsNone(history.has_permission(frappe._dict(doctype=dt, **{field: "ToDo"})))

    def test_gate_off_and_full_view_do_not_override_native_permissions(self):
        doc = frappe._dict(doctype="Version", ref_doctype="Sales Invoice")
        with patch.object(frappe, "conf", {}):
            self.assertIsNone(history.has_permission(doc))
            self.assertEqual(history.version_condition(), "")
        with patch("privacy_shield.policy.current_capabilities", return_value=SimpleNamespace(view_full=True)):
            self.assertIsNone(history.has_permission(doc))
            self.assertEqual(history.comment_condition(), "")

    def test_list_conditions_use_source_fields_and_scope(self):
        with patch.object(frappe.local, "db", MagicMock(escape=lambda value: repr(value)), create=True):
            self.assertIn("`tabComment`.`reference_doctype`", history.comment_condition())
            self.assertIn("'Sales Invoice'", history.comment_condition())
            self.assertIn("`tabVersion`.`ref_doctype`", history.version_condition())

    def test_restricted_timeline_reads_authorize_source_without_loading_history(self):
        for name in ("get_comments", "get_communications"):
            doc = MagicMock()
            with patch.object(frappe, "get_doc", return_value=doc) as get_doc, patch("frappe.desk.form.load." + name) as original:
                self.assertEqual(getattr(history, name)("Sales Invoice", "SI1"), [])
                get_doc.assert_called_once_with("Sales Invoice", "SI1")
                doc.check_permission.assert_called_once_with("read")
                original.assert_not_called()
                doc.check_permission.side_effect = frappe.PermissionError
                with self.assertRaises(frappe.PermissionError):
                    getattr(history, name)("Sales Invoice", "SI1")
                original.assert_not_called()

    def test_raw_source_history_is_denied(self):
        with patch.object(frappe, "get_doc") as get_doc:
            with self.assertRaises(frappe.PermissionError):
                history.get_comments("Payment Intent", "PI1")
            get_doc.assert_not_called()

    def test_full_and_gate_off_timeline_contracts_delegate(self):
        for conf, full in (({}, False), ({"privacy_shield_desk_enabled": True}, True)):
            with patch.object(frappe, "conf", conf), patch("privacy_shield.policy.current_capabilities", return_value=SimpleNamespace(view_full=full)):
                for name, args in (("get_comments", ("Sales Invoice", "SI1", "Comment")), ("get_communications", ("Sales Invoice", "SI1", 2, 10))):
                    with patch("frappe.desk.form.load." + name, return_value=["original"]) as original:
                        self.assertEqual(getattr(history, name)(*args), ["original"])
                        original.assert_called_once_with(*args)

    def test_docinfo_scrubs_all_reviewed_timeline_channels_preserving_permissions(self):
        info = {field: ["9876543210"] for field in history.TIMELINE_FIELDS}
        info["permissions"] = {"read": 1}
        response = frappe._dict(docinfo=info)
        with patch.object(frappe.local, "response", response, create=True), patch.object(frappe, "get_doc", return_value=MagicMock()), patch("frappe.desk.form.load.get_docinfo") as original:
            history.get_docinfo(doctype="Sales Invoice", name="SI1")
            original.assert_called_once_with(doctype="Sales Invoice", name="SI1")
            self.assertNotIn("9876543210", str(info))
            self.assertEqual(info["permissions"], {"read": 1})

    def test_client_supplied_doc_rejected_before_native_loader(self):
        with patch("frappe.desk.form.load.get_docinfo") as original:
            with self.assertRaises(frappe.PermissionError):
                history.get_docinfo(doc={"doctype": "Sales Invoice", "name": "SI1"})
            original.assert_not_called()

    def test_initial_desk_response_scrubs_history(self):
        from privacy_shield.desk import _project_response
        response = frappe._dict(docs=[], docinfo={field: ["9876543210"] for field in history.TIMELINE_FIELDS})
        with patch.object(frappe.local, "response", response, create=True):
            _project_response(SimpleNamespace(view_full=False))
            self.assertNotIn("9876543210", str(response))

    def test_communication_secondary_link_denial(self):
        doc = frappe._dict(doctype="Communication", reference_doctype="ToDo", timeline_links=[frappe._dict(link_doctype="Patient")])
        with self.assertRaises(frappe.PermissionError):
            history.has_permission(doc)
        doc.timeline_links = [frappe._dict(link_doctype="ToDo")]
        self.assertIsNone(history.has_permission(doc))

    def test_communication_condition_includes_secondary_links(self):
        with patch.object(frappe.local, "db", MagicMock(escape=lambda value: repr(value)), create=True):
            condition = history.communication_condition()
            self.assertIn("`tabCommunication`.`reference_doctype`", condition)
            self.assertIn("NOT EXISTS", condition)
            self.assertIn("ps_link.parent = `tabCommunication`.name", condition)
            self.assertIn("ps_link.parentfield = 'timeline_links'", condition)
        with patch.object(frappe, "conf", {}):
            self.assertEqual(history.communication_condition(), "")

    def test_mcp_raw_logs_require_full_visibility_regardless_of_source(self):
        import json
        for source in (None, "", "   ", "Patient", "ToDo", "Chat Contact", "Vobiz Call Log"):
            for field, value in (("error_trace", "Call 2025550101"),
                                 ("response_summary_json", json.dumps({"mobile": "2025550101"})),
                                 ("diff_json", json.dumps(json.dumps({"mobile": "2025550101"}))),
                                 ("request_summary_json", None)):
                doc = frappe._dict(doctype="MCP Audit Log", ref_doctype=source, **{field: value})
                with self.assertRaises(frappe.PermissionError):
                    history.has_permission(doc)
                with patch.object(frappe, "conf", {}):
                    self.assertIsNone(history.has_permission(doc))
                    self.assertEqual(history.mcp_audit_condition(), "")
                with patch("privacy_shield.policy.current_capabilities", return_value=SimpleNamespace(view_full=True)):
                    self.assertIsNone(history.has_permission(doc))
                    self.assertEqual(history.mcp_audit_condition(), "")
        self.assertEqual(history.mcp_audit_condition(), "1=0")

    def test_deferred_app_documents_not_raw_blocked(self):
        from privacy_shield.raw_access import check
        for doctype in ("Chat Contact", "Vobiz Call Log"):
            check(doctype)
