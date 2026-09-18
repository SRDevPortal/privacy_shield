import unittest
from unittest.mock import patch, MagicMock
import frappe
from privacy_shield import query_outputs as query

class QueryOutputTests(unittest.TestCase):
    def setUp(self):
        for p in [patch.object(frappe.local,"flags",frappe._dict(in_test=True),create=True),
                  patch.object(frappe,"session",frappe._dict(user="agent")),
                  patch.object(query,"restricted",return_value=True)]:
            p.start();self.addCleanup(p.stop)

    def test_scoped_run_denied_before_execution(self):
        with patch.object(query,"check_report",side_effect=frappe.PermissionError),patch("frappe.desk.query_report.run") as original:
            with self.assertRaises(frappe.PermissionError):query.run("R1",ignore_prepared_report=True)
            original.assert_not_called()

    def test_export_cannot_bypass_direct_internal_run(self):
        with patch.object(frappe,"form_dict",{"report_name":"R1"}),patch.object(query,"check_report",side_effect=frappe.PermissionError),patch("frappe.desk.query_report.export_query") as original:
            with self.assertRaises(frappe.PermissionError):query.export_query()
            original.assert_not_called()

    def test_scoped_custom_field_lookup_denied(self):
        with patch("frappe.desk.query_report.get_data_for_custom_field") as original:
            with self.assertRaises(frappe.PermissionError):query.get_data_for_custom_field("Patient","mobile")
            original.assert_not_called()

    def test_alternate_user_rejected(self):
        with self.assertRaises(frappe.PermissionError):query.check_request("R1",user="Administrator")

    def test_foreign_prepared_report_rejected(self):
        with patch.object(query,"check_report"),patch.object(query,"check_prepared"),patch.object(frappe,"get_doc",return_value=frappe._dict(report_name="R2")):
            with self.assertRaises(frappe.PermissionError):query.check_request("R1",{"prepared_report_name":"P1"})

    def test_prepared_access_denial_prevents_original(self):
        with patch.object(query,"check_report"),patch.object(query,"check_prepared",side_effect=frappe.PermissionError),patch("frappe.desk.query_report.run") as original:
            with self.assertRaises(frappe.PermissionError):query.run("R1",'{"prepared_report_name":"P1"}')
            original.assert_not_called()

    def test_gate_off_or_full_view_preserves_all_arguments(self):
        with patch.object(query,"restricted",return_value=False),patch("frappe.desk.query_report.run",return_value="ok") as original:
            self.assertEqual(query.run("R1",{},None,True,["x"],True,"parent",False),"ok")
            original.assert_called_once_with("R1",{},None,True,["x"],True,"parent",False)

    def test_unrelated_or_deferred_field_delegates(self):
        with patch("frappe.desk.query_report.get_data_for_custom_field",return_value={}) as original:
            self.assertEqual(query.get_data_for_custom_field("Vobiz Call Log","customer_number",["V1"]),{})
            original.assert_called_once()
