import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import frappe
from privacy_shield import raw_access, outputs, report_outputs, hooks
from privacy_shield.import_access import TARGETS
from shipment_tracking.api.privacy import support_summary
from shipment_tracking.api import support
from payment_orchestrator.api import pinelabs


class RawProviderAccessTests(unittest.TestCase):
    def setUp(self):
        for item in [patch.object(frappe.local, "flags", frappe._dict(in_test=True), create=True),
                     patch.object(frappe, "conf", {"privacy_shield_desk_enabled": True}),
                     patch("privacy_shield.policy.current_capabilities", return_value=SimpleNamespace(view_full=False))]:
            item.start();self.addCleanup(item.stop)

    def test_every_raw_type_has_deny_only_record_and_list_hooks(self):
        for dt in raw_access.RAW_DOCTYPES:
            self.assertIn(dt,TARGETS)
            self.assertEqual(hooks.has_permission[dt],"privacy_shield.raw_access.has_permission")
            self.assertEqual(hooks.permission_query_conditions[dt],"privacy_shield.raw_access.query_condition")
            with self.assertRaises(frappe.PermissionError):
                raw_access.has_permission(SimpleNamespace(doctype=dt),ptype="read")
            with self.assertRaises(frappe.PermissionError):raw_access.check(dt)
        self.assertEqual(raw_access.query_condition(),"1=0")

    def test_gate_off_and_full_view_never_grant_permissions(self):
        doc=SimpleNamespace(doctype="Payment Intent")
        with patch.object(frappe,"conf",{}):
            self.assertIsNone(raw_access.has_permission(doc));self.assertEqual(raw_access.query_condition(),"")
        with patch("privacy_shield.policy.current_capabilities",return_value=SimpleNamespace(view_full=True)):
            self.assertIsNone(raw_access.has_permission(doc));self.assertEqual(raw_access.query_condition(),"")
        self.assertIsNone(raw_access.has_permission(SimpleNamespace(doctype="Unrelated")))

    def test_export_and_pdf_deny_before_render(self):
        with patch("frappe.core.doctype.data_export.exporter.export_data") as export, \
             patch("frappe.utils.print_format.download_pdf") as pdf:
            for dt in raw_access.RAW_DOCTYPES:
                with self.assertRaises(frappe.PermissionError):outputs.export_data(doctype=dt)
                with self.assertRaises(frappe.PermissionError):outputs.download_pdf(dt,"synthetic")
            export.assert_not_called();pdf.assert_not_called()

    def test_reports_cannot_return_raw_provider_records(self):
        with patch.object(frappe,"get_doc",return_value=SimpleNamespace(ref_doctype="Shipment Tracking Sync Log")):
            with self.assertRaises(frappe.PermissionError):report_outputs.check_report("synthetic")

    def test_request_doctype_guard(self):
        with patch.object(frappe,"form_dict",{"doctype":"Payment Intent"}):
            with self.assertRaises(frappe.PermissionError):raw_access.guard_request()

    def test_support_summary_drops_free_text_and_attachments(self):
        data={"success":True,"ticket":"LOCAL1","latest_ticket":"LOCAL1","stage":"call 9876543210",
              "latest_response":"9876543210","responses":[{"attachment":"https://invalid/9876543210"}],
              "raw_response":{"customer":"9876543210"},"hub_address_disabled":True}
        result=support_summary(data)
        self.assertTrue(result["success"]);self.assertTrue(result["hub_address_disabled"])
        self.assertEqual(result["ticket"],"LOCAL1");self.assertEqual(result["responses"],[])
        self.assertNotIn("9876543210",str(result));self.assertIn("9876543210",str(data))
        with patch.object(frappe,"conf",{}):self.assertIs(support_summary(data),data)

    def test_support_return_helper_uses_summary(self):
        ticket=MagicMock();ticket.name="LOCAL1";ticket.latest_response="9876543210"
        with patch.object(support,"support_response_entries",return_value=[{"text":"9876543210"}]):
            result=support.support_return_payload(ticket,{"contact":"9876543210"},"done")
            self.assertNotIn("9876543210",str(result));self.assertNotIn("raw_response",result)

    def test_realtime_checks_recipient_not_worker(self):
        db=MagicMock();db.get_value.side_effect=["recipient@example.invalid","Failed"]
        with patch.object(frappe,"db",db),patch.object(frappe,"publish_realtime") as publish, \
             patch("privacy_shield.policy.current_capabilities",return_value=SimpleNamespace(view_full=False)) as policy:
            pinelabs.publish_pos_failure("PI1","Declined 9876543210")
            policy.assert_called_once_with("recipient@example.invalid")
            self.assertNotIn("9876543210",str(publish.call_args))
            self.assertEqual(publish.call_args.kwargs["user"],"recipient@example.invalid")

    def test_missing_recipient_never_broadcasts(self):
        with patch.object(frappe,"db",MagicMock(get_value=MagicMock(return_value=None))), \
             patch.object(frappe,"publish_realtime") as publish:
            pinelabs.publish_pos_failure("PI1","Declined 9876543210")
            publish.assert_not_called()

    def test_mirrored_support_replies_and_timeline_comments_are_removed(self):
        from privacy_shield.desk import project_document, _project_response
        caps=SimpleNamespace(view_full=False,edit_original=False)
        for dt,prefix in [("Sales Invoice","si"),("Patient Encounter","pe")]:
            payload={"doctype":dt,"name":"LOCAL1",prefix+"_latest_support_response":"Call 9876543210"}
            self.assertNotIn("9876543210",str(project_document(payload,caps)))
        response={"docs":[],"docinfo":{"comments":[{"content":"9876543210"}],"versions":[]}}
        with patch.object(frappe,"response",response):
            _project_response(caps)
            self.assertEqual(response["docinfo"]["comments"],[])
