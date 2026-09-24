import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import frappe
from payment_orchestrator.api.common.privacy_response import project_payment_response
from payment_orchestrator.api import razorpay
from payment_orchestrator.logic import _publish_payment_completion


class PaymentCreationPrivacyTests(unittest.TestCase):
    def setUp(self):
        for item in (patch.object(frappe.local, "flags", frappe._dict(in_test=True), create=True),
                     patch.object(frappe, "conf", {"privacy_shield_desk_enabled": True}),
                     patch("privacy_shield.policy.current_capabilities", return_value=SimpleNamespace(view_full=False))):
            item.start()
            self.addCleanup(item.stop)

    def test_qr_projection_preserves_display_and_drops_provider_data(self):
        source = {"payment_intent": "PI1", "qr_code_url": "https://example.invalid/qr1", "qr_status": "active", "provider_status": "customer 9876543210", "provider_qr_id": "9876543210", "response": {"customer": "9876543210"}}
        result = project_payment_response("qr_creation", source)
        self.assertNotIn("9876543210", str(result))
        self.assertEqual(result["qr_code_url"], source["qr_code_url"])
        self.assertEqual(result["qr_status"], "active")
        self.assertEqual(source["response"]["customer"], "9876543210")

    def test_gate_off_and_full_qr_contract_unchanged(self):
        source = {"response": {"customer": "9876543210"}}
        with patch.object(frappe, "conf", {}):
            self.assertIs(project_payment_response("qr_creation", source), source)
        with patch("privacy_shield.policy.current_capabilities", return_value=SimpleNamespace(view_full=True)):
            self.assertIs(project_payment_response("qr_creation", source), source)

    def test_qr_endpoint_projects_only_after_authorization_and_adapter(self):
        intent = SimpleNamespace(name="PI1", gateway="Razorpay", payment_mode="QR Code", qr_code_url="https://example.invalid/qr1", provider_qr_id="9876543210", qr_status="active", payment_status="created")
        context = {"mobile": "9876543210"}
        adapter = MagicMock()
        adapter.create.return_value = {"customer": "9876543210"}
        with patch.object(razorpay, "ensure_payment_action_permission") as permission, patch.object(razorpay, "get_settings", return_value={}), patch.object(razorpay, "is_razorpay_qr_code_enabled", return_value=True), patch("payment_orchestrator.api.common.validation.validate_reference_payment_request") as validate, patch.object(razorpay, "create_payment_intent_doc", return_value=(intent, context)), patch.object(razorpay, "RazorpayQRCodeAdapter", return_value=adapter):
            result = razorpay.create_qr_code("Sales Invoice", "SI1", 10)
            permission.assert_called_once()
            validate.assert_called_once_with("Sales Invoice", "SI1", 10, settings={})
            adapter.create.assert_called_once_with(intent, context)
            self.assertNotIn("9876543210", str(result))
            permission.side_effect = frappe.PermissionError
            adapter.reset_mock()
            with self.assertRaises(frappe.PermissionError):
                razorpay.create_qr_code("Sales Invoice", "SI1", 10)
            adapter.create.assert_not_called()

    def test_completion_never_broadcasts_without_recipient(self):
        with patch.object(frappe, "publish_realtime") as publish:
            _publish_payment_completion(SimpleNamespace(name="PI1", requested_by=None))
            publish.assert_not_called()

    def test_completion_is_addressed_and_deferred_until_commit(self):
        intent = SimpleNamespace(name="PI1", requested_by="agent@example.invalid", amount_paid=10)
        with patch.object(frappe.local, "db", MagicMock(), create=True), patch.object(frappe, "publish_realtime") as publish:
            frappe.db.get_value.return_value = "Paid"
            _publish_payment_completion(intent, "PE1", 10)
            self.assertEqual(publish.call_args.kwargs, {"user": intent.requested_by, "after_commit": True})
            self.assertEqual(publish.call_args.args[1]["payment_entry"], "PE1")
