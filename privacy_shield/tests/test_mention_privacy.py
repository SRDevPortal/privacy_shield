import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import frappe
from privacy_shield.notification_privacy import protect_notification_log, NOTICE
from privacy_shield.comment_actions import add_comment
from sriaas_clinic.api.crm_lead.privacy_notifications import PrivacyCRMNotification
from crm.fcrm.doctype.crm_notification.crm_notification import CRMNotification


class MentionPrivacyTests(unittest.TestCase):
    def setUp(self):
        for item in (patch.object(frappe, "conf", {"privacy_shield_desk_enabled": True}),
                     patch.object(frappe.local, "flags", frappe._dict(in_test=True), create=True),
                     patch("privacy_shield.policy.current_capabilities", return_value=SimpleNamespace(view_full=False))):
            item.start(); self.addCleanup(item.stop)

    def test_log_previews_generic_for_all_recipients(self):
        for recipient in ("restricted", "full"):
            doc = frappe._dict(type="Mention", document_type="Patient", document_name="P1", for_user=recipient, subject="9876543210", email_content="9876543210")
            protect_notification_log(doc)
            self.assertNotIn("9876543210", str(doc))
            self.assertEqual(doc.email_content, NOTICE)
            self.assertEqual(doc.for_user, recipient)
            self.assertEqual(doc.document_name, "P1")

    def test_log_gate_off_unrelated_and_other_types_unchanged(self):
        for gate, source, kind in ((False, "Patient", "Mention"), (True, "ToDo", "Mention"), (True, "Patient", "Alert")):
            doc = frappe._dict(type=kind, document_type=source, subject="9876543210", email_content="9876543210")
            with patch.object(frappe, "conf", {"privacy_shield_desk_enabled": gate}): protect_notification_log(doc)
            self.assertEqual(doc.subject, "9876543210")

    def crm_doc(self):
        doc = object.__new__(PrivacyCRMNotification)
        doc.__dict__.update(doctype="CRM Notification", type="Mention", reference_doctype="CRM Lead", reference_name="L1", from_user="author", to_user="recipient", notification_type_doctype="Comment", notification_type_doc="C1", message="9876543210", notification_text="9876543210", flags=frappe._dict())
        return doc

    def test_crm_preview_sanitized_before_native_insert(self):
        doc = self.crm_doc()
        with patch.object(frappe.local, "db", MagicMock(), create=True), patch.object(CRMNotification, "insert", return_value=doc) as insert:
            frappe.db.exists.return_value = None
            self.assertIs(doc.insert(ignore_permissions=True), doc)
            insert.assert_called_once_with(ignore_permissions=True)
            self.assertNotIn("9876543210", str(frappe.db.exists.call_args))
            self.assertEqual(doc.message, NOTICE)
            self.assertEqual(doc.to_user, "recipient")

    def test_crm_duplicate_does_not_insert_again(self):
        doc = self.crm_doc()
        with patch.object(frappe.local, "db", MagicMock(), create=True), patch.object(frappe, "get_doc", return_value="existing") as get_doc, patch.object(CRMNotification, "insert") as insert:
            frappe.db.exists.return_value = "N1"
            self.assertEqual(doc.insert(ignore_permissions=True), "existing")
            get_doc.assert_called_once_with("CRM Notification", "N1")
            insert.assert_not_called()

    def test_crm_normal_insert_never_uses_privileged_duplicate_shortcut(self):
        doc = self.crm_doc()
        with patch.object(frappe.local, "db", MagicMock(), create=True), patch.object(CRMNotification, "insert", side_effect=frappe.PermissionError):
            with self.assertRaises(frappe.PermissionError): doc.insert()
            frappe.db.exists.assert_not_called()

    def test_crm_gate_off_preserves_native_insert(self):
        doc = self.crm_doc()
        with patch.object(frappe, "conf", {}), patch.object(CRMNotification, "insert") as insert:
            doc.insert(ignore_permissions=True)
            insert.assert_called_once_with(ignore_permissions=True)
            self.assertEqual(doc.message, "9876543210")

    def test_comment_response_safe_and_original_unchanged(self):
        doc = frappe._dict(name="C1", creation="2026-09-21", modified="2026-09-21", content="9876543210", comment_by="9876543210")
        with patch("frappe.desk.form.utils.add_comment", return_value=doc) as original:
            result = add_comment("Patient", "P1", "9876543210", "author", "Name")
            original.assert_called_once_with("Patient", "P1", "9876543210", "author", "Name")
            self.assertNotIn("9876543210", str(result))
            self.assertEqual(result["name"], "C1")
            self.assertEqual(doc.content, "9876543210")
            self.assertEqual(result["owner"], "")

    def test_comment_native_denial_propagates(self):
        with patch("frappe.desk.form.utils.add_comment", side_effect=frappe.PermissionError):
            with self.assertRaises(frappe.PermissionError): add_comment("Patient", "P1", "text", "author", "Name")

    def test_comment_full_or_gate_off_returns_original(self):
        doc = frappe._dict(content="9876543210")
        with patch("frappe.desk.form.utils.add_comment", return_value=doc):
            with patch.object(frappe, "conf", {}):
                self.assertIs(add_comment("Patient", "P1", "text", "author", "Name"), doc)
            with patch("privacy_shield.policy.current_capabilities", return_value=SimpleNamespace(view_full=True)):
                self.assertIs(add_comment("Patient", "P1", "text", "author", "Name"), doc)

    def test_raw_source_comment_rejected_before_mutation(self):
        with patch("frappe.desk.form.utils.add_comment") as original:
            with self.assertRaises(frappe.PermissionError): add_comment("Payment Intent", "PI1", "text", "author", "Name")
            original.assert_not_called()
