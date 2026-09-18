import unittest
from unittest.mock import patch, MagicMock
import frappe
from privacy_shield import file_outputs as out


class FileOutputTests(unittest.TestCase):
    def setUp(self):
        for p in [patch.object(frappe.local, "flags", frappe._dict(in_test=True), create=True),
                  patch.object(out, "restricted", return_value=True),
                  patch("privacy_shield.report_outputs.check_attachment_urls"),
                  patch.object(frappe, "db", MagicMock()),
                  patch.object(frappe, "get_list", return_value=[frappe._dict(name="F1", file_url="/private/files/test.csv")]),
                  patch("frappe.core.api.file.zip_files", return_value="zip")]:
            p.start(); self.addCleanup(p.stop)
        frappe.db.sql.return_value = []

    def test_rejects_invalid_and_unbounded_inputs(self):
        for value in [[], ["F"]*101, [{"name":"F1"}], "{}", [None]]:
            with self.assertRaises(frappe.ValidationError): out.zip_files(value)
        frappe.get_list.assert_not_called()

    def test_missing_or_permission_filtered_file_denies_entire_zip(self):
        with self.assertRaises(frappe.PermissionError): out.zip_files(["F1", "F2"])
        frappe.db.sql.assert_not_called()

    def test_duplicate_url_attachment_denied(self):
        frappe.db.sql.return_value = [(1,)]
        with self.assertRaises(frappe.PermissionError): out.zip_files(["F1"])
        from frappe.core.api.file import zip_files
        zip_files.assert_not_called()

    def test_accessible_unrelated_files_delegate(self):
        self.assertEqual(out.zip_files(["F1", "F1"]), "zip")
        self.assertEqual(frappe.get_list.call_args.kwargs["limit_page_length"],100)
        self.assertEqual(frappe.db.sql.call_count,1)

    def test_gate_off_or_full_view_preserves_original(self):
        with patch.object(out, "restricted", return_value=False):
            self.assertEqual(out.zip_files("original-input"), "zip")
        frappe.get_list.assert_not_called()

    def test_extraction_denied_before_source_content_read(self):
        frappe.db.sql.return_value = [(1,)]
        with patch("frappe.core.api.file.unzip_file") as original:
            with self.assertRaises(frappe.PermissionError): out.unzip_file("F1")
            original.assert_not_called()

    def test_attachment_copy_denied_before_creation(self):
        frappe.db.sql.return_value = [(1,)]
        with patch("frappe.utils.file_manager.add_attachments") as original:
            with self.assertRaises(frappe.PermissionError): out.add_attachments("ToDo","T1",["F1"])
            original.assert_not_called()

    def test_extract_requires_source_write_and_delete(self):
        doc=MagicMock()
        with patch.object(frappe,"get_doc",return_value=doc), patch("frappe.core.api.file.unzip_file",return_value="extracted"):
            self.assertEqual(out.unzip_file("F1"),"extracted")
        self.assertEqual([c.args[0] for c in doc.check_permission.call_args_list],["write","delete"])

    def test_copy_requires_destination_write(self):
        doc=MagicMock();doc.check_permission.side_effect=frappe.PermissionError
        with patch.object(frappe,"get_doc",return_value=doc),patch("frappe.utils.file_manager.add_attachments") as original:
            with self.assertRaises(frappe.PermissionError):out.add_attachments("ToDo","T1",["F1"])
            original.assert_not_called()

    def test_zip_calls_prepared_report_guard_before_building(self):
        with patch("privacy_shield.report_outputs.check_attachment_urls",side_effect=frappe.PermissionError) as guard:
            with self.assertRaises(frappe.PermissionError):out.zip_files(["F1"])
            guard.assert_called_once_with(("/private/files/test.csv",))
        from frappe.core.api.file import zip_files
        zip_files.assert_not_called()
