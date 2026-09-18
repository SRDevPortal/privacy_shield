import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock,patch
import frappe
from payment_orchestrator.api.common.privacy_response import project_payment_response
from payment_orchestrator.api import whatsapp,dashboard

class PaymentOutputProjectionTests(unittest.TestCase):
    def setUp(self):
        for item in [patch.object(frappe.local,"flags",frappe._dict(in_test=True),create=True),patch.object(frappe,"conf",{"privacy_shield_desk_enabled":True}),patch("privacy_shield.policy.current_capabilities",return_value=SimpleNamespace(view_full=False))]:
            item.start();self.addCleanup(item.stop)

    def test_preview_and_send_mask_recipient_and_remove_prose(self):
        source={"ok":True,"payment_intent":"PI1","mobile_no":"9876543210","message":"Pay https://invalid/9876543210","display_name":"9876543210","delivery_status":"Delivered"}
        for kind in ["message_preview","message_result"]:
            result=project_payment_response(kind,source)
            self.assertNotIn("9876543210",str(result));self.assertTrue(result["mask_mobile"].endswith("3210"))
            self.assertTrue(result["ok"]);self.assertEqual(result["delivery_status"],"Delivered")
        self.assertEqual(source["mobile_no"],"9876543210")

    def test_failure_and_mobile_prompt_contract(self):
        result=project_payment_response("message_result",{"ok":False,"needs_mobile":True,"message":"Invalid 9876543210"})
        self.assertFalse(result["ok"]);self.assertTrue(result["needs_mobile"]);self.assertNotIn("9876543210",str(result))

    def test_dashboard_totals_survive_unknown_fields_and_urls_removed(self):
        source={"has_history":True,"summary":{"total_paid":25,"currency":"INR","extra":"9876543210"},"intents":[{"name":"PI1","status":"Paid","amount_paid":25,"currency":"INR","payment_status":"Declined 9876543210","payment_link_url":"https://invalid/9876543210","provider_payment_id":"9876543210","gateway":"Razorpay"}]}
        result=project_payment_response("dashboard",source)
        self.assertEqual(result["summary"]["total_paid"],25);self.assertEqual(result["intents"][0]["status"],"Paid")
        self.assertNotIn("9876543210",str(result));self.assertTrue(result["intents"][0]["details_restricted"]);self.assertEqual(result["intents"][0]["payment_status"],"failed")

    def test_refund_status_amount_without_provider_notes(self):
        result=project_payment_response("refund",{"status":"processed","amount":1000,"notes":{"recipient":"9876543210"},"id":"9876543210"})
        self.assertEqual(result["amount"],1000);self.assertEqual(result["status"],"processed");self.assertNotIn("9876543210",str(result))

    def test_gate_off_and_full_visibility_preserve_all_contracts(self):
        data={"mobile_no":"9876543210"}
        for kind in ["message_preview","message_result","dashboard","refund"]:
            with patch.object(frappe,"conf",{}):self.assertIs(project_payment_response(kind,data),data)
            with patch("privacy_shield.policy.current_capabilities",return_value=SimpleNamespace(view_full=True)):
                self.assertIs(project_payment_response(kind,data),data)

    def test_preview_endpoint_authorizes_and_projects(self):
        doc=MagicMock();doc.name="PI1"
        with patch.object(frappe,"get_doc",return_value=doc),patch.object(whatsapp,"ensure_payment_intent_read_permission") as permission,patch.object(whatsapp,"ensure_whatsapp_supported_payment_intent"),patch.object(whatsapp,"resolve_payment_whatsapp_recipient",return_value={"mobile_no":"9876543210"}),patch.object(whatsapp,"build_payment_whatsapp_message",return_value="Call 9876543210"):
            result=whatsapp.get_payment_message_preview("PI1");permission.assert_called_once_with(doc)
            self.assertNotIn("9876543210",str(result))

    def test_send_result_and_failure_without_real_send(self):
        doc=MagicMock();doc.name="PI1"
        for outcome in [{"ok":True,"mobile_no":"9876543210"},RuntimeError("Invalid 9876543210")]:
            with patch.object(frappe,"get_doc",return_value=doc),patch.object(whatsapp,"ensure_payment_intent_action_permission"),patch.object(whatsapp,"ensure_whatsapp_supported_payment_intent"),patch.object(whatsapp,"send_payment_whatsapp_message",side_effect=outcome if isinstance(outcome,Exception) else None,return_value=outcome):
                result=whatsapp.send_payment_request("PI1");self.assertNotIn("9876543210",str(result))

    def test_dashboard_wrapper_projects_after_internal_summary(self):
        with patch.object(dashboard,"_get_reference_dashboard",return_value={"has_history":True,"summary":{},"intents":[{"payment_link_url":"9876543210"}]}) as original:
            result=dashboard.get_reference_dashboard("Sales Invoice","SI1")
            original.assert_called_once_with("Sales Invoice","SI1");self.assertNotIn("9876543210",str(result))

    def test_refund_endpoint_projects_after_backend_state_update(self):
        from payment_orchestrator.api import razorpay
        doc=MagicMock(gateway="Razorpay",provider_payment_id="PAY1",refund_status="",amount_paid=25,amount_refunded=0,provider_mode="Test")
        client=MagicMock();client.create_refund.return_value={"status":"processed","amount":1000,"notes":{"recipient":"9876543210"}}
        with patch.object(frappe,"get_doc",return_value=doc),patch.object(razorpay,"get_settings",return_value=MagicMock(enable_refunds=True)),patch.object(razorpay,"ensure_payment_action_permission"),patch.object(razorpay,"ensure_payment_intent_action_permission"),patch.object(razorpay,"RazorpayClient",return_value=client):
            result=razorpay.refund_payment("PI1",amount=10)
            self.assertEqual(result["amount"],1000);self.assertNotIn("9876543210",str(result))
            client.create_refund.assert_called_once_with("PAY1",{"amount":1000})
            doc.db_set.assert_any_call("refund_status","Refund Initiated")
