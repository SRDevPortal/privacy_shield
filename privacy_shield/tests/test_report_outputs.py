import unittest
from unittest.mock import patch, MagicMock
import frappe
from privacy_shield import report_outputs as reports, file_outputs as files

PREFIX="frappe.core.doctype.prepared_report.prepared_report."

class ReportOutputTests(unittest.TestCase):
    def setUp(self):
        for p in [patch.object(frappe.local,"flags",frappe._dict(in_test=True),create=True),
                  patch.object(reports,"restricted",return_value=True),
                  patch.object(files,"restricted",return_value=True),
                  patch.object(frappe,"db",MagicMock())]:
            p.start();self.addCleanup(p.stop)

    def test_direct_shared_url_denied_before_content_read(self):
        frappe.db.sql.return_value=[(1,)]
        with patch("frappe.handler.download_file") as original:
            with self.assertRaises(frappe.PermissionError):files.download_file("/private/files/a.csv")
            original.assert_not_called()

    def test_direct_url_matches_original_exactly(self):
        frappe.db.sql.return_value=[]
        url="/private/files/a%20b.csv"
        with patch.object(reports,"check_attachment_urls") as guard, patch("frappe.handler.download_file",return_value="data") as original:
            self.assertEqual(files.download_file(url),"data")
            original.assert_called_once_with(url)
            guard.assert_called_once_with([url])
        self.assertEqual(frappe.db.sql.call_args.args[1][0],(url,))

    def test_external_url_rejected_before_lookup(self):
        with self.assertRaises(frappe.PermissionError):files.download_file("https://example.com/file")
        frappe.db.sql.assert_not_called()

    def test_scoped_prepared_download_denied_before_decompression(self):
        prepared=MagicMock(report_name="R1")
        with patch.object(frappe,"get_doc",side_effect=[prepared,frappe._dict(ref_doctype="Patient",report_type="Query Report")]),patch(PREFIX+"download_attachment") as original:
            with self.assertRaises(frappe.PermissionError):reports.download_attachment("P1")
            original.assert_not_called()
            prepared.check_permission.assert_called_once_with("read")

    def test_custom_report_reference_cannot_bypass(self):
        docs=[MagicMock(report_name="R1"),frappe._dict(ref_doctype="ToDo",report_type="Custom Report",reference_report="R2"),frappe._dict(ref_doctype="Contact",report_type="Query Report")]
        with patch.object(frappe,"conf",{"privacy_shield_desk_enabled":True}),patch.object(frappe,"get_doc",side_effect=docs),patch(PREFIX+"enqueue_json_to_csv_conversion") as original:
            with self.assertRaises(frappe.PermissionError):reports.enqueue_json_to_csv_conversion("P1")
            original.assert_not_called()

    def test_reference_cycle_denied(self):
        with patch.object(frappe,"get_doc",side_effect=[MagicMock(report_name="R1"),frappe._dict(ref_doctype="ToDo",report_type="Custom Report",reference_report="R1")]):
            with self.assertRaises(frappe.PermissionError):reports.check_prepared("P1")

    def test_deferred_report_uses_original(self):
        with patch.object(frappe,"get_doc",side_effect=[MagicMock(report_name="R1"),frappe._dict(ref_doctype="Vobiz Call Log",report_type="Script Report")]),patch(PREFIX+"download_attachment",return_value="original"):
            self.assertEqual(reports.download_attachment("P1"),"original")

    def test_full_view_or_disabled_passes_through(self):
        with patch.object(reports,"restricted",return_value=False),patch.object(frappe,"get_doc") as read,patch(PREFIX+"download_attachment",return_value="original"):
            self.assertEqual(reports.download_attachment("P1"),"original")
            read.assert_not_called()
        with patch.object(files,"restricted",return_value=False),patch("frappe.handler.download_file",return_value="data"):
            self.assertEqual(files.download_file("/files/a.csv"),"data")
        frappe.db.sql.assert_not_called()

    def test_attachment_batch_scoped_report_denied(self):
        frappe.db.sql.return_value=[frappe._dict(name="P1",report_name="R1")]
        with patch.object(frappe,"get_all",return_value=[frappe._dict(name="R1",ref_doctype="Patient",report_type="Query Report")]) as query:
            with self.assertRaises(frappe.PermissionError):reports.check_attachment_urls(["/private/files/a.gz"])
            self.assertEqual(query.call_count,1)

    def test_attachment_orphan_and_excessive_matches_denied(self):
        for rows in [[frappe._dict(name=None,report_name=None)],[frappe._dict(name="P1",report_name="R1")]*101]:
            frappe.db.sql.return_value=rows
            with self.assertRaises(frappe.PermissionError):reports.check_attachment_urls(["/private/files/a.gz"])

    def test_attachment_custom_reference_checked_in_batches(self):
        frappe.db.sql.return_value=[frappe._dict(name="P1",report_name="R1")]
        with patch.object(frappe,"get_all",side_effect=[
            [frappe._dict(name="R1",ref_doctype="ToDo",report_type="Custom Report",reference_report="R2")],
            [frappe._dict(name="R2",ref_doctype="Contact",report_type="Query Report")]]) as query:
            with self.assertRaises(frappe.PermissionError):reports.check_attachment_urls(["/private/files/a.gz"])
            self.assertEqual(query.call_count,2)

    def test_unrelated_attachment_needs_no_report_reads(self):
        frappe.db.sql.return_value=[]
        with patch.object(frappe,"get_all") as query:
            reports.check_attachment_urls(["/private/files/a.txt"])
            query.assert_not_called()

    def test_private_file_request_checks_prepared_links(self):
        from types import SimpleNamespace
        with patch.object(frappe.local,"request",SimpleNamespace(path="/private/files/a.gz"),create=True),patch.object(reports,"check_attachment_urls") as check:
            reports.guard_private_report_file()
            check.assert_called_once_with(["/private/files/a.gz"])

    def test_conversion_rechecks_current_user_policy(self):
        method="frappe.core.doctype.prepared_report.prepared_report.convert_json_to_csv"
        with patch.object(frappe,"conf",{"privacy_shield_desk_enabled":True}),patch.object(frappe.local,"job",frappe._dict(user="agent"),create=True),patch.object(frappe,"session",frappe._dict(user="agent")),patch.object(reports,"check_conversion_access",side_effect=frappe.PermissionError) as check:
            with self.assertRaises(frappe.PermissionError):reports.guard_conversion_job(method,{"prepared_report_name":"P1"})
            check.assert_called_once_with("P1")

    def test_conversion_without_recorded_actor_denied(self):
        with patch.object(frappe,"conf",{"privacy_shield_desk_enabled":True}),patch.object(frappe.local,"job",frappe._dict(user=None),create=True):
            with self.assertRaises(frappe.PermissionError):reports.guard_conversion_job("frappe.core.doctype.prepared_report.prepared_report.convert_json_to_csv",{})

    def test_conversion_gate_off_has_no_reads(self):
        with patch.object(frappe,"conf",{}),patch.object(reports,"check_prepared") as check:
            reports.guard_conversion_job("frappe.core.doctype.prepared_report.prepared_report.convert_json_to_csv",{})
            check.assert_not_called()

    def test_full_viewer_must_read_report_before_enqueue(self):
        doc=MagicMock();doc.check_permission.side_effect=frappe.PermissionError
        with patch.object(frappe,"conf",{"privacy_shield_desk_enabled":True}), patch.object(reports,"restricted",return_value=False), patch.object(frappe,"get_doc",return_value=doc), patch(PREFIX+"enqueue_json_to_csv_conversion") as original:
            with self.assertRaises(frappe.PermissionError):reports.enqueue_json_to_csv_conversion("P1")
            original.assert_not_called()

    def test_worker_rejects_disabled_and_mismatched_actor(self):
        for actor,session,enabled in (("agent","agent",0),("agent","other",1)):
            with patch.object(frappe,"conf",{"privacy_shield_desk_enabled":True}), patch.object(frappe.local,"job",frappe._dict(user=actor),create=True), patch.object(frappe,"session",frappe._dict(user=session)), patch.object(frappe.db,"get_value",return_value=enabled), patch.object(reports,"check_conversion_access") as check:
                with self.assertRaises(frappe.PermissionError):reports.guard_conversion_job(PREFIX+"convert_json_to_csv",{"prepared_report_name":"P1"})
                check.assert_not_called()

    def test_full_worker_still_checks_document_permission(self):
        doc=MagicMock();doc.check_permission.side_effect=frappe.PermissionError
        with patch.object(reports,"restricted",return_value=False),patch.object(frappe,"get_doc",return_value=doc):
            with self.assertRaises(frappe.PermissionError):reports.check_conversion_access("P1")
            doc.check_permission.assert_called_once_with("read")
