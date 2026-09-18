import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock,patch
import frappe
from payment_orchestrator.api.common import intents
from payment_orchestrator.api.common.privacy_response import project_payment_response

class IntentProjectionTests(unittest.TestCase):
    def setUp(self):
        for p in [patch.object(frappe.local,"flags",frappe._dict(in_test=True),create=True),
                  patch.object(frappe,"conf",{"privacy_shield_desk_enabled":True}),
                  patch("privacy_shield.policy.current_capabilities",return_value=SimpleNamespace(view_full=False))]:
            p.start();self.addCleanup(p.stop)

    def test_sensitive_payload_omitted_and_polling_presence_preserved(self):
        data={"name":"PI1","status":"Requested","gateway":"Razorpay","payment_mode":"Payment Link","amount_paid":0,
              "party_mobile":"9876543210","provider_link_id":"9876543210","notes":"9876543210",
              "provider_payload_snapshot":{"contact":"9876543210"},"future_field":"9876543210"}
        result=project_payment_response("intent",data)
        self.assertNotIn("9876543210",str(result));self.assertTrue(result["has_provider_link"])
        self.assertEqual(result["payment_mode"],"Payment Link");self.assertEqual(data["party_mobile"],"9876543210")

    def test_failure_prose_is_generic_but_failure_semantics_remain(self):
        for reason in ["Declined 9876543210","Invalid recipient 9876543210","ERROR 9876543210"]:
            result=project_payment_response("intent",{"status":"Requested","payment_status":reason})
            self.assertIn("failed",result["pos_failure_reason"]);self.assertNotIn("9876543210",str(result))
        result=project_payment_response("intent",{"status":"Paid","amount_paid":25,"payment_status":"captured"})
        self.assertEqual(result["amount_paid"],25);self.assertEqual(result["payment_status"],"captured")

    def test_gate_off_and_view_full_retain_original_contract(self):
        data={"party_mobile":"9876543210"}
        with patch.object(frappe,"conf",{}):self.assertIs(project_payment_response("intent",data),data)
        with patch("privacy_shield.policy.current_capabilities",return_value=SimpleNamespace(view_full=True)):
            self.assertIs(project_payment_response("intent",data),data)

    def test_reference_denial_precedes_sync_and_projection(self):
        with patch.object(frappe,"get_doc",return_value=MagicMock()), \
             patch.object(intents,"ensure_reference_read_permission",side_effect=frappe.PermissionError), \
             patch.object(intents,"sync_payment_whatsapp_delivery_status") as sync:
            with self.assertRaises(frappe.PermissionError):intents.get_payment_intent("PI1")
            sync.assert_not_called()

    def test_authorized_endpoint_projects_after_sync_reload(self):
        doc=MagicMock();doc.as_dict.return_value={"name":"PI1","party_mobile":"9876543210","status":"Paid","amount_paid":10}
        with patch.object(frappe,"get_doc",return_value=doc), \
             patch.object(intents,"ensure_reference_read_permission") as auth, \
             patch.object(intents,"sync_payment_whatsapp_delivery_status") as sync:
            result=intents.get_payment_intent("PI1")
            auth.assert_called_once_with(doc.reference_doctype,doc.reference_name)
            sync.assert_called_once_with(doc);doc.reload.assert_called_once()
            self.assertEqual(result["amount_paid"],10);self.assertNotIn("9876543210",str(result))
