import csv
import io
import unittest
from unittest.mock import patch,MagicMock
from types import SimpleNamespace
import frappe
from privacy_shield import outputs
from privacy_shield.policy import Capabilities

class OutputTests(unittest.TestCase):
    def setUp(self):
        for p in [patch.object(frappe.local,"flags",frappe._dict(in_test=True),create=True),
                  patch.object(frappe,"conf",{"privacy_shield_desk_enabled":True}),
                  patch.object(frappe,"session",SimpleNamespace(user="test-agent")),
                  patch("privacy_shield.outputs.current_capabilities",return_value=Capabilities())]:
            p.start();self.addCleanup(p.stop)

    def test_csv_omits_original_and_formula_escape(self):
        response={}
        with patch.object(frappe,"response",response),patch.object(frappe.permissions,"can_export",return_value=True), \
             patch.object(frappe,"get_list",return_value=[{"name":"=formula","mobile_no":"9876543210","owner":"test-agent"}]):
            outputs.write_export("CRM Lead",["name","mobile_no"],None,"CSV")
        text=response["filecontent"].decode("utf-8-sig")
        self.assertNotIn("9876543210",text)
        rows=list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows,[["name","mask_mobile"],["'=formula","******3210"]])

    def test_export_permission_denial_prevents_query(self):
        with patch.object(frappe.permissions,"can_export",return_value=False),patch.object(frappe,"get_list") as query:
            with self.assertRaises(frappe.PermissionError):outputs.export_table("Patient",["mobile"])
            query.assert_not_called()

    def test_owner_only_permission_is_enforced(self):
        with patch.object(frappe.permissions,"can_export",side_effect=[False,True]), \
             patch.object(frappe,"get_list",return_value=[{"name":"P1","mobile":"9876543210","owner":"someone-else"}]):
            with self.assertRaises(frappe.PermissionError):outputs.export_table("Patient",["mobile"])

    def test_large_export_rejected_not_truncated(self):
        with patch.object(frappe.permissions,"can_export",return_value=True), \
             patch.object(frappe,"get_list",return_value=[{"name":"P1"}]*501) as query:
            with self.assertRaises(frappe.ValidationError):outputs.export_table("Patient",["name"])
            self.assertEqual(query.call_args.kwargs["limit_page_length"],501)

    def test_unreviewed_columns_rejected_before_query(self):
        for field in ["address","description","mobile as x","*"]:
            with self.assertRaises((frappe.PermissionError,frappe.ValidationError)):
                outputs.export_table("Patient",[field])

    def test_print_checks_read_and_print_and_escapes_id(self):
        doc=MagicMock();doc.name="<P1>";doc.permitted_fieldnames={"mobile"};doc.get.return_value="9876543210"
        with patch.object(frappe,"get_doc",return_value=doc): html=outputs.summary_html("Patient","<P1>")
        self.assertNotIn("9876543210",html)
        self.assertIn("******3210",html)
        self.assertIn("&lt;P1&gt;",html)
        self.assertEqual([c.args[0] for c in doc.check_permission.call_args_list],["read","print"])

    def test_print_denial_prevents_render(self):
        doc=MagicMock();doc.check_permission.side_effect=frappe.PermissionError
        with patch.object(frappe,"get_doc",return_value=doc):
            with self.assertRaises(frappe.PermissionError):outputs.summary_html("Patient","P1")
            doc.get.assert_not_called()

    def test_arbitrary_format_or_client_doc_rejected(self):
        with patch("frappe.utils.pdf.get_pdf") as renderer:
            with self.assertRaises(frappe.PermissionError):outputs.download_pdf("Patient","P1",format="Standard")
            with self.assertRaises(frappe.PermissionError):outputs.download_pdf("Patient","P1",format=outputs.FORMAT,doc={"mobile":"raw"})
            renderer.assert_not_called()

    def test_summary_pdf_only_receives_reviewed_html(self):
        response={}
        with patch.object(frappe,"response",response),patch.object(outputs,"summary_html",return_value="<p>******3210</p>"), \
             patch("frappe.utils.pdf.get_pdf",return_value=b"synthetic-pdf") as renderer:
            outputs.download_pdf("Patient","P1",format=outputs.FORMAT)
            renderer.assert_called_once_with("<p>******3210</p>")
            self.assertEqual(response["type"],"pdf")

    def test_full_view_uses_existing_output_permission_path(self):
        with patch.object(outputs,"current_capabilities",return_value=Capabilities(True,False)), \
             patch("frappe.utils.print_format.download_pdf",return_value="original") as original:
            self.assertEqual(outputs.download_pdf("Patient","P1"),"original")
            original.assert_called_once()

    def test_deferred_doctype_passes_through(self):
        with patch("frappe.utils.print_format.download_pdf",return_value="original"):
            self.assertEqual(outputs.download_pdf("Vobiz Call Log","V1"),"original")

    def test_direct_printview_is_guarded(self):
        with patch.object(frappe.local,"request",SimpleNamespace(path="/printview"),create=True), \
             patch.object(frappe,"form_dict",{"doctype":"Patient"}):
            with self.assertRaises(frappe.PermissionError):outputs.guard_printview()

    def test_excel_writer_needs_no_site_date_format(self):
        from openpyxl import load_workbook
        response={}
        with patch.object(frappe,"response",response),patch.object(frappe.permissions,"can_export",return_value=True), \
             patch.object(frappe,"get_list",return_value=[{"name":"P1","mobile":"9876543210","owner":"test-agent"}]):
            outputs.write_export("Patient",["name","mobile"],None,"Excel")
        workbook=load_workbook(io.BytesIO(response["filecontent"]),read_only=True)
        self.assertEqual(list(workbook.active.values),[("name","mask_mobile"),("P1","******3210")])
        workbook.close()
