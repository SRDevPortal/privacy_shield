import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
import frappe
from privacy_shield import imports
from privacy_shield.policy import Capabilities


class ImportTests(unittest.TestCase):
    def setUp(self):
        for p in [patch.object(frappe.local, "flags", frappe._dict(in_test=True), create=True),
                  patch.object(frappe, "conf", {"privacy_shield_desk_enabled": True}),
                  patch.object(frappe, "session", SimpleNamespace(user="agent")),
                  patch.object(frappe.local, "job", frappe._dict(user="agent"), create=True),
                  patch.object(imports, "current_capabilities", return_value=Capabilities())]:
            p.start(); self.addCleanup(p.stop)

    def test_restricted_preview_rejected_before_file_read(self):
        doc = SimpleNamespace(reference_doctype="Patient")
        with patch.object(imports.DataImport, "get_importer") as original:
            with self.assertRaises(frappe.PermissionError): imports.PrivacyDataImport.get_importer(doc)
            original.assert_not_called()

    def test_restricted_start_rejected_before_enqueue(self):
        doc = SimpleNamespace(reference_doctype="CRM Lead")
        with patch.object(imports.DataImport, "start_import") as original:
            with self.assertRaises(frappe.PermissionError): imports.PrivacyDataImport.start_import(doc)
            original.assert_not_called()

    def test_validate_denied_before_template_parse(self):
        with patch.object(imports.DataImport, "validate") as original:
            with self.assertRaises(frappe.PermissionError):
                imports.PrivacyDataImport.validate(SimpleNamespace(reference_doctype="Contact"))
            original.assert_not_called()

    def test_view_only_cannot_import(self):
        with patch.object(imports, "current_capabilities", return_value=Capabilities(True, False)):
            imports.check_target("Patient")
            with self.assertRaises(frappe.PermissionError): imports.check_target("Patient", write=True)

    def test_editor_without_visibility_cannot_import(self):
        with patch.object(imports, "current_capabilities", return_value=Capabilities(False, True)):
            with self.assertRaises(frappe.PermissionError): imports.check_target("Patient", write=True)

    def test_full_editor_allowed(self):
        with patch.object(imports, "current_capabilities", return_value=Capabilities(True, True)):
            imports.check_target("Patient", write=True)

    def test_queued_job_rechecks_current_policy(self):
        doc = MagicMock(reference_doctype="Patient")
        with patch.object(frappe, "get_doc", return_value=doc):
            with self.assertRaises(frappe.PermissionError):
                imports.guard_job(imports.PREFIX+"start_import", {"data_import":"TEST"})
            doc.check_permission.assert_called_once_with("write")

    def test_missing_worker_actor_not_administrator_bypass(self):
        with patch.object(frappe, "get_doc", return_value=MagicMock(reference_doctype="Patient")), \
             patch.object(frappe.local, "job", frappe._dict(user=None)), \
             patch.object(imports, "current_capabilities", return_value=Capabilities(True, True)):
            with self.assertRaises(frappe.PermissionError):
                imports.guard_job(imports.PREFIX+"start_import", {"data_import":"TEST"})

    def test_logs_denied_before_returning_exceptions(self):
        doc = MagicMock(reference_doctype="Patient")
        with patch.object(frappe, "get_doc", return_value=doc), \
             patch(imports.PREFIX+"get_import_logs") as original:
            with self.assertRaises(frappe.PermissionError): imports.get_import_logs("TEST")
            original.assert_not_called()
            doc.check_permission.assert_called_once_with("read")

    def test_template_denied_before_export(self):
        with patch(imports.PREFIX+"download_template") as original:
            with self.assertRaises(frappe.PermissionError): imports.download_template("Contact")
            original.assert_not_called()

    def test_gate_off_and_deferred_are_unchanged(self):
        for dt in ["ToDo", "Chat Contact", "Vobiz Call Log"]:
            imports.check_target(dt, write=True)
        with patch.object(frappe, "conf", {}), patch.object(frappe, "get_doc") as query:
            imports.check_target("Patient", write=True)
            imports.guard_job(imports.PREFIX+"start_import", {"data_import":"TEST"})
            query.assert_not_called()
        imports.guard_job("some.other.job", {})

    def test_contact_child_scoped(self):
        with self.assertRaises(frappe.PermissionError): imports.check_target("Contact Phone")
