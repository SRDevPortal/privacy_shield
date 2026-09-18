import unittest
from types import SimpleNamespace
from unittest.mock import patch
import frappe
from privacy_shield.policy import Capabilities
from privacy_shield.projections import project_numbers

class AdapterTests(unittest.TestCase):
    def setUp(self):
        p = patch.object(frappe.local, "flags", frappe._dict(in_test=True), create=True)
        p.start(); self.addCleanup(p.stop)
        self.values = {"mobile": "9876543210", "phone": "1234567890", "mobile_no": "9876543210",
                       "patient_name": "Synthetic", "sex": "Female", "sr_patient_id": "TEST-ID"}
        self.doc = SimpleNamespace(
            name="SYNTHETIC", customer_name="Synthetic", get=self.values.get,
            permitted_fieldnames=set(self.values), meta=SimpleNamespace(has_field=lambda name: False),
            check_permission=lambda permission: None)
        patches = [patch.object(frappe, "get_doc", return_value=self.doc),
                   patch.object(frappe, "get_installed_apps", return_value=["privacy_shield"]),
                   patch("privacy_shield.policy.current_capabilities", return_value=Capabilities())]
        self.mocks = [p.start() for p in patches]
        for p in patches: self.addCleanup(p.stop)

    def test_issue_omits_original_and_preserves_contract(self):
        from support_patch.issue import get_customer_details
        result = get_customer_details("SYNTHETIC")
        self.assertNotIn("mobile_no", result)
        self.assertEqual(result["mask_mobile"], "******3210")
        self.assertEqual(result["name"], "SYNTHETIC")

    def test_issue_full_view_and_field_permissions(self):
        from support_patch.issue import get_customer_details
        self.mocks[2].return_value = Capabilities(True, False)
        self.assertEqual(get_customer_details("SYNTHETIC")["mobile_no"], "9876543210")
        self.doc.permitted_fieldnames.remove("mobile_no")
        result = get_customer_details("SYNTHETIC")
        self.assertNotIn("mobile_no", result)
        self.assertNotIn("mask_mobile", result)

    def test_appointment_lookup_only_returns_masks(self):
        from clinic_appointments.api.patient_details import get_patient_details
        result = get_patient_details("SYNTHETIC")
        self.assertNotIn("mobile", result)
        self.assertNotIn("phone", result)
        self.assertEqual(result["mask_mobile"], "******3210")
        self.assertEqual(result["mask_phone"], "******7890")
        self.assertTrue(result["resolve_numbers_on_server"])

    def test_lookup_denies_unreadable_patient(self):
        from clinic_appointments.api.patient_details import get_patient_details
        def deny(permission): raise frappe.PermissionError()
        self.doc.check_permission = deny
        with self.assertRaises(frappe.PermissionError): get_patient_details("SYNTHETIC")

    def test_appointment_originals_still_resolve_on_server(self):
        from clinic_appointments.clinic_appointments.doctype.clinic_appointment.clinic_appointment import autofill_from_patient
        doc = SimpleNamespace(patient="SYNTHETIC", patient_name="", mobile_number="", alternate_mobile="")
        with patch.object(frappe, "db", SimpleNamespace(get_value=lambda *a, **kw: self.values)):
            autofill_from_patient(doc)
        self.assertEqual(doc.mobile_number, "9876543210")
        self.assertEqual(doc.alternate_mobile, "1234567890")

    def test_projection_does_not_mutate_backend_data(self):
        original = {"mobile_no": "9876543210", "sr_mobile_norm": "9876543210"}
        result = project_numbers(original, {"mobile_no": "mask_mobile"}, aliases=["sr_mobile_norm"])
        self.assertNotIn("9876543210", str(result))
        self.assertEqual(original["mobile_no"], "9876543210")

    def test_crm_extension_delegates_to_authorized_boundary(self):
        from sriaas_clinic.api.crm_lead.privacy import get_number_details
        with patch("privacy_shield.api.get_numbers", return_value={"numbers": []}) as boundary:
            self.assertEqual(get_number_details("SYNTHETIC"), {"numbers": []})
            boundary.assert_called_once_with("CRM Lead", "SYNTHETIC")
