import copy
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import frappe
from payment_orchestrator.api.common.privacy_response import project_payment_response
from payment_orchestrator.api import razorpay, pinelabs


class PaymentResponsePrivacyTests(unittest.TestCase):
    def setUp(self):
        for item in [patch.object(frappe.local, "flags", frappe._dict(in_test=True), create=True),
                     patch.object(frappe, "conf", {"privacy_shield_desk_enabled": True}),
                     patch("privacy_shield.policy.current_capabilities", return_value=SimpleNamespace(view_full=False))]:
            item.start(); self.addCleanup(item.stop)

    def test_gate_off_and_full_viewer_preserve_existing_contract(self):
        payload = {"customer": {"contact": "9876543210"}}
        for kind in ("razorpay", "pinelabs_link", "pinelabs_pos"):
            with patch.object(frappe, "conf", {}):
                self.assertIs(project_payment_response(kind, payload), payload)
            with patch("privacy_shield.policy.current_capabilities", return_value=SimpleNamespace(view_full=True)):
                self.assertIs(project_payment_response(kind, payload), payload)

    def test_restricted_payload_drops_unknown_aliases_without_mutation(self):
        payload = {"status": "paid", "customer": {"contact": "9876543210"},
                   "notes": {"recipient": "9876543210"}, "short_url": "https://invalid/9876543210",
                   "new_provider_field": ["9876543210"]}
        original = copy.deepcopy(payload)
        self.assertEqual(project_payment_response("razorpay", payload), {"status": "paid"})
        self.assertEqual(payload, original)
        self.assertEqual(project_payment_response("razorpay", {"status": "Call 9876543210"}), {"status": None})

    def test_link_completion_and_pos_failure_contracts_survive(self):
        payload = {"payment_intent": "PI1", "provider_status": "PROCESSED", "processed": True,
                   "provider_response": {"mobile": "9876543210"},
                   "result": {"payment_intent": "PI1", "payment_entry": "PE1", "status": "Paid",
                              "allocated_amount": 10, "extra": "9876543210"}}
        result = project_payment_response("pinelabs_link", payload)
        self.assertTrue(result["processed"]);self.assertEqual(result["result"]["payment_entry"], "PE1")
        self.assertNotIn("9876543210", str(result))
        result = project_payment_response("pinelabs_pos", {"failed": True, "failure_message": "Call 9876543210",
                    "pos_request_status": "Declined for 9876543210", "provider_response": payload})
        self.assertTrue(result["failed"]);self.assertTrue(result["failure_message"])
        self.assertNotIn("9876543210", str(result))

    def test_policy_failure_does_not_fall_back_to_raw(self):
        with patch("privacy_shield.policy.current_capabilities", side_effect=RuntimeError("policy unavailable")):
            with self.assertRaises(RuntimeError):project_payment_response("razorpay", {"mobile": "9876543210"})

    def test_razorpay_routes_persist_raw_before_projecting(self):
        for route,method in [(razorpay.fetch_payment_link,"fetch_payment_link"),
                             (razorpay.fetch_qr_code,"fetch_qr_code"), (razorpay.close_qr_code,"close_qr_code")]:
            intent = MagicMock(gateway="Razorpay",provider_link_id="LINK",provider_qr_id="QR",provider_mode="Test")
            payload = {"status": "paid", "customer": {"contact": "9876543210"}}
            client = MagicMock();getattr(client,method).return_value=payload
            with patch.object(frappe,"get_doc",return_value=intent), \
                 patch.object(razorpay,"ensure_payment_intent_action_permission"), \
                 patch.object(razorpay,"get_settings"), \
                 patch.object(razorpay,"RazorpayClient",return_value=client), \
                 patch.object(razorpay,"apply_unpaid_terminal_provider_status",return_value=False) as reconcile, \
                 patch.object(frappe,"as_json",return_value="RAW_SNAPSHOT"):
                result=route("PI1")
                self.assertEqual(result,{"status":"paid"})
                reconcile.assert_called_once_with(intent,"paid",payload)
                intent.db_set.assert_any_call("provider_payload_snapshot","RAW_SNAPSHOT")

    def test_pinelabs_link_processing_receives_raw_response(self):
        intent=MagicMock(gateway="Pine Labs",provider_link_id="LINK",amount_paid=0);intent.name="PI1"
        payload={"status":"PROCESSED","customer":{"mobile":"9876543210"}}
        client=MagicMock();client.get_payment_link.return_value=payload
        with patch.object(frappe,"get_doc",return_value=intent), \
             patch.object(pinelabs,"_require_payment_role"), \
             patch.object(pinelabs,"ensure_payment_intent_action_permission"), \
             patch.object(pinelabs,"get_settings"), \
             patch.object(pinelabs,"PineLabsOnlineClient",return_value=client), \
             patch.object(pinelabs,"create_payment_link_event",return_value=MagicMock()), \
             patch.object(pinelabs,"sync_payment_link") as sync, \
             patch.object(pinelabs,"payment_link_success_payload",return_value={}) as extract, \
             patch.object(pinelabs,"process_provider_payment_success",return_value={"payment_entry":"PE1","status":"Paid"}):
            result=pinelabs.fetch_payment_link("PI1")
            sync.assert_called_once_with(intent,payload);extract.assert_called_once_with(payload,intent)
            self.assertEqual(result["result"]["payment_entry"],"PE1")
            self.assertNotIn("9876543210",str(result))

    def test_pinelabs_pos_preserves_failure_flag_without_provider_text(self):
        intent=MagicMock(request_channel="POS",provider_pos_request_id="POS1");intent.name="PI1"
        payload={"ResponseCode":123,"ResponseMessage":"Declined 9876543210"}
        client=MagicMock();client.fetch_status.return_value=payload
        with patch.object(frappe,"get_doc",return_value=intent), \
             patch.object(frappe,"db",MagicMock(get_value=MagicMock(return_value="Failed"))), \
             patch.object(pinelabs,"_require_payment_role"), \
             patch.object(pinelabs,"ensure_payment_intent_action_permission"), \
             patch.object(pinelabs,"get_settings"), \
             patch.object(pinelabs,"is_pinelabs_pos_enabled",return_value=True), \
             patch.object(pinelabs,"PineLabsPOSAdapter",return_value=client), \
             patch.object(pinelabs,"apply_pos_terminal_failure") as reconcile:
            result=pinelabs.fetch_pos_payment_status("PI1")
            reconcile.assert_called_once_with(intent,payload)
            self.assertTrue(result["failed"]);self.assertNotIn("9876543210",str(result))
