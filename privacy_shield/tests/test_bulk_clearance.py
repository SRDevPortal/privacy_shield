import unittest,importlib,csv,io,tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock,patch
import frappe
from sriaas_clinic.api import bulk_clearance as bulk, bulk_clearance_access as access

class BulkClearanceTests(unittest.TestCase):
    def setUp(self):
        for p in [patch.object(frappe.local,"flags",frappe._dict(in_test=True),create=True),
                  patch.object(frappe,"session",SimpleNamespace(user="tester")),patch.object(frappe,"conf",{}),
                  patch.object(frappe,"get_roles",return_value=["Accounts Manager"]),
                  patch.object(frappe,"has_permission",return_value=True)]:
            p.start();self.addCleanup(p.stop)

    def test_both_main_routes_deny_before_file_access(self):
        with patch.object(frappe,"get_roles",return_value=["Agent"]),patch.object(bulk,"read_rows") as read:
            for call in [bulk.process_file_from_ui,bulk.process_file_settle_invoices]:
                for submit in [0,1]:
                    with self.subTest(call=call.__name__,submit=submit),self.assertRaises(frappe.PermissionError):
                        call("/etc/passwd",submit)
            read.assert_not_called()

    def test_guest_and_invalid_submit_rejected(self):
        with patch.object(frappe,"session",SimpleNamespace(user="Guest")),self.assertRaises(frappe.PermissionError):
            access.authorize(0)
        for value in [-1,2,"true"]:
            with self.assertRaises(frappe.ValidationError):access.authorize(value)

    def test_preview_role_does_not_allow_submission(self):
        with patch.object(frappe,"get_roles",return_value=["Accounts User"]):
            self.assertFalse(access.authorize(0))
            with self.assertRaises(frappe.PermissionError):access.authorize(1)

    def test_submission_requires_native_create_and_submit(self):
        self.assertTrue(access.authorize(1))
        self.assertEqual([call.args[:2] for call in frappe.has_permission.call_args_list],
                         [("Sales Invoice","read"),("Payment Entry","create"),("Payment Entry","submit")])

    def test_private_policy_checked_before_read(self):
        with patch.object(frappe,"conf",{"privacy_shield_desk_enabled":True}),              patch("privacy_shield.policy.current_capabilities",return_value=SimpleNamespace(view_full=False,edit_original=False)),              patch.object(bulk,"read_rows") as read:
            with self.assertRaises(frappe.PermissionError):bulk.process_file_from_ui("F1",0)
            read.assert_not_called()

    def test_arbitrary_paths_and_remote_urls_rejected(self):
        for value in ["/etc/passwd","../../secret.csv","https://example.invalid/x.csv","s3://key"]:
            with self.subTest(value=value),self.assertRaises(frappe.PermissionError):
                access.read_rows(value)

    def test_file_permission_and_root_containment_precede_open(self):
        doc=MagicMock();doc.file_url="/private/files/input.csv"
        with tempfile.TemporaryDirectory() as root,patch.object(frappe,"get_all",return_value=["F1"]),              patch.object(frappe,"get_doc",return_value=doc),patch.object(frappe,"get_site_path",return_value=root):
            doc.has_permission.return_value=False
            with self.assertRaises(frappe.PermissionError):access.read_rows(doc.file_url)
            doc.has_permission.return_value=True;doc.get_full_path.return_value="/etc/passwd"
            with self.assertRaises(frappe.PermissionError):access.read_rows(doc.file_url)
            path=Path(root)/"input.csv";path.write_text("invoice,amount"+chr(10)+"INV1,10"+chr(10))
            doc.get_full_path.return_value=str(path)
            self.assertEqual(access.read_rows(doc.file_url),[{"invoice":"INV1","amount":"10"}])

    def test_all_invoice_permissions_preflight_before_accounting(self):
        doc=MagicMock();doc.check_permission.side_effect=frappe.PermissionError
        with patch.object(bulk,"read_rows",return_value=[{"invoice":"INV1"}]),              patch.object(frappe,"get_doc",return_value=doc),              patch.object(bulk,"_create_payment_entry_and_allocate") as create,patch.object(bulk,"_write_log_csv_common") as report:
            with self.assertRaises(frappe.PermissionError):bulk.process_file_settle_invoices("F1",1)
            create.assert_not_called();report.assert_not_called()

    def test_preview_caps_amount_and_never_creates_payment(self):
        invoice=frappe._dict(outstanding_amount=40)
        with patch.object(bulk,"read_rows",return_value=[{"invoice":"INV1","amount":"80","remittance_date":"2026-09-18"}]),              patch.object(bulk,"checked_invoices",return_value={"INV1":invoice}),              patch.object(bulk,"_create_payment_entry_and_allocate") as create,              patch.object(bulk,"_write_log_csv_common",return_value="/private/files/report.csv"):
            result=bulk.process_file_settle_invoices("F1",0)
            self.assertEqual(result["processed"][0]["allocated_amount"],40)
            self.assertTrue(result["log_file"].startswith("/private/"));create.assert_not_called()

    def test_report_is_private_and_neutralizes_formulas(self):
        doc=MagicMock(file_url="/private/files/report.csv")
        with patch.object(frappe,"get_doc",return_value=doc) as get_doc:
            bulk._write_log_csv_common([[1,"=unsafe","ok","",""]])
            fields=get_doc.call_args.args[0]
            self.assertEqual(fields["is_private"],1)
            self.assertEqual(list(csv.reader(io.StringIO(fields["content"])))[1][1],"'=unsafe")
            doc.insert.assert_called_once_with()

    def test_native_payment_insert_does_not_ignore_permissions(self):
        invoice=MagicMock(name="invoice");invoice.name="INV1";invoice.get.side_effect=lambda k:{"outstanding_amount":40,"grand_total":40}.get(k)
        payment=MagicMock();payment.name="PE1"
        with patch.object(frappe,"get_doc",return_value=invoice),patch.object(frappe,"new_doc",return_value=payment):
            self.assertEqual(bulk._create_payment_entry_and_allocate("INV1",invoice,10,"2026-09-18","Account","test"),"PE1")
            invoice.check_permission.assert_called_once_with("read")
            payment.insert.assert_called_once_with();payment.submit.assert_called_once_with()

    def test_legacy_wrappers_use_same_guard(self):
        for module,fn in [("_bulk_clearance copy","process_file"),("_bulk_clearance copy 2","process_file_settle_invoices"),("_bulk_clearance copy 3","process_file_settle_invoices")]:
            legacy=importlib.import_module("sriaas_clinic.api."+module)
            with patch.object(frappe,"get_roles",return_value=["Agent"]),patch.object(bulk,"read_rows") as read:
                with self.assertRaises(frappe.PermissionError):getattr(legacy,fn)("F1",1)
                read.assert_not_called()
