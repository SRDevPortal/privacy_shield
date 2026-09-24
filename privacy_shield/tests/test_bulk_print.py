import unittest
from unittest.mock import patch, MagicMock
import frappe
from privacy_shield import bulk_print


class BulkPrintTests(unittest.TestCase):
    def setUp(self):
        for item in [patch.object(frappe.local, 'flags', frappe._dict(in_test=True), create=True),
                     patch.object(frappe.local, 'conf', frappe._dict(privacy_shield_desk_enabled=True), create=True),
                     patch.object(bulk_print, 'current_capabilities', return_value=frappe._dict(view_full=False))]:
            item.start();self.addCleanup(item.stop)

    def test_gate_off_retains_native_path(self):
        frappe.conf.privacy_shield_desk_enabled=False
        with patch.object(frappe,'get_doc') as get:
            bulk_print.check_bulk('Patient', '["P1"]')
            get.assert_not_called()

    def test_deferred_only_input_untouched(self):
        with patch.object(frappe,'get_doc') as get:
            bulk_print.check_bulk('Chat Contact', '["C1"]')
            get.assert_not_called()

    def test_restricted_mixed_mapping_denied_before_read(self):
        with patch.object(frappe,'get_doc') as get:
            with self.assertRaises(frappe.PermissionError):
                bulk_print.check_bulk({'Patient':['P1'],'Address':['A1']}, 'combined')
            get.assert_not_called()

    def test_restricted_async_denied_before_enqueue(self):
        with patch('frappe.utils.print_format.download_multi_pdf_async') as original:
            with self.assertRaises(frappe.PermissionError):
                bulk_print.download_multi_pdf_async('Patient','["P1"]')
            original.assert_not_called()

    def test_full_view_does_not_bypass_document_permission(self):
        with patch.object(bulk_print,'current_capabilities',return_value=frappe._dict(view_full=True)), patch.object(frappe,'get_doc') as get:
            get.return_value.check_permission.side_effect=frappe.PermissionError
            with self.assertRaises(frappe.PermissionError):bulk_print.check_bulk('Patient','["P1"]')

    def test_full_view_checks_read_and_print_on_every_document(self):
        with patch.object(bulk_print,'current_capabilities',return_value=frappe._dict(view_full=True)), patch.object(frappe,'get_doc') as get:
            bulk_print.check_bulk({'Patient':['P1','P2']},'combined')
            self.assertEqual(get.call_count,2)
            self.assertEqual([c.args[0] for c in get.return_value.check_permission.call_args_list],['read','print','read','print'])

    def test_invalid_name_shapes_rejected(self):
        with patch.object(bulk_print,'current_capabilities',return_value=frappe._dict(view_full=True)):
            for value in ['invalid','{}','[]','[null]']:
                with self.subTest(value=value),self.assertRaises(frappe.ValidationError):bulk_print.check_bulk('Patient',value)

    def test_page_bound_before_database_reads(self):
        with patch.object(bulk_print,'current_capabilities',return_value=frappe._dict(view_full=True)), patch.object(frappe,'get_doc') as get:
            with self.assertRaises(frappe.ValidationError):bulk_print.check_bulk({'Patient':['P1']*501},'combined')
            get.assert_not_called()
