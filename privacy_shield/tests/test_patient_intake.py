import unittest
from unittest.mock import MagicMock, patch
import frappe
from privacy_shield import patient_intake, lifecycle, desk
from privacy_shield.policy import Capabilities, evaluate


class PatientIntakeTests(unittest.TestCase):
    def setUp(self):
        for p in [patch.object(frappe.local, "flags", frappe._dict(in_test=True), create=True),
                  patch.object(frappe, "conf", {"privacy_shield_desk_enabled": True}),
                  patch.object(frappe, "has_permission", return_value=True)]:
            p.start(); self.addCleanup(p.stop)
        self.values = {"doctype": "CRM Lead", "name": "L1", "first_name": "Test",
                       "mobile_no": "2025550101", "phone": "2025550102"}
        self.lead = MagicMock(name="lead")
        self.lead.name = "L1"
        self.lead.mobile_no = self.values["mobile_no"]
        self.lead.get.side_effect = self.values.get
        self.lead.as_dict.return_value = self.values

    def test_source_creation_copies_separate_numbers_and_projects_response(self):
        with patch.object(frappe, "get_doc", return_value=self.lead), \
             patch.object(lifecycle, "current_capabilities", return_value=Capabilities()), \
             patch("frappe.client.insert", side_effect=lambda d: {**d, "name": "P1"}) as insert:
            result = lifecycle.insert({"doctype": "Patient", "__privacy_source_lead": "L1", "first_name": "Test"})
        data = insert.call_args.args[0]
        self.assertEqual((data["mobile"], data["phone"]), ("2025550101", "2025550102"))
        self.assertNotIn("__privacy_source_lead", data)
        self.assertNotIn("2025550101", str(result))
        self.assertNotIn("2025550102", str(result))
        self.lead.check_permission.assert_called_with("read")

    def test_inaccessible_source_is_rejected(self):
        self.lead.check_permission.side_effect = frappe.PermissionError
        with patch.object(frappe, "get_doc", return_value=self.lead):
            with self.assertRaises(frappe.PermissionError):
                lifecycle.prepare_new({"doctype": "Patient", "__privacy_source_lead": "L1"}, Capabilities())

    def test_source_requires_patient_create_permission(self):
        with patch.object(frappe, "has_permission", side_effect=frappe.PermissionError):
            with self.assertRaises(frappe.PermissionError):
                patient_intake.copy_source_numbers({}, "L1")

    def test_source_does_not_accept_client_number_overrides(self):
        with patch.object(frappe, "get_doc", return_value=self.lead):
            for caps in [Capabilities(), Capabilities(True, True), Capabilities(False, False, True)]:
                with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
                    lifecycle.prepare_new({"doctype": "Patient", "__privacy_source_lead": "L1", "mobile": "2025550199"}, caps)

    def test_linked_or_missing_source_number_is_rejected(self):
        with patch.object(frappe, "get_doc", return_value=self.lead):
            self.values["sr_source_patient"] = "P1"
            with self.assertRaises(frappe.ValidationError): patient_intake.copy_source_numbers({}, "L1")
            self.values.pop("sr_source_patient")
            self.values["mobile_no"] = ""
            with self.assertRaises(frappe.ValidationError): patient_intake.copy_source_numbers({}, "L1")

    def test_intake_grant_does_not_grant_view_or_existing_edit(self):
        caps = evaluate(["Agent"], [{"role": "Agent", "enter_new_numbers": 1}], "agent")
        self.assertEqual(caps, Capabilities(False, False, True))
        data = {"doctype": "Patient", "mobile": "2025550101"}
        self.assertEqual(lifecycle.prepare_new(data, caps)["mobile"], data["mobile"])
        with self.assertRaises(frappe.PermissionError): lifecycle.prepare_new(data, Capabilities())
        with self.assertRaises(frappe.PermissionError):
            lifecycle.prepare_new({"doctype": "CRM Lead", "mobile_no": "2025550101"}, caps)
        with self.assertRaises(PermissionError):
            desk.prepare_payload({**data, "name": "P1"}, {"doctype": "Patient", "name": "P1", "mobile": "2025550199"}, caps)
        with self.assertRaises(frappe.ValidationError):
            lifecycle.prepare_new({"doctype": "Patient", "mobile": "******0101"}, caps)

    def test_source_reference_cannot_change_existing_patient_numbers(self):
        with self.assertRaises(PermissionError):
            desk.prepare_payload({"doctype": "Patient", "name": "P1", "__privacy_source_lead": "L1"},
                                 {"doctype": "Patient", "name": "P1", "mobile": "2025550101"}, Capabilities())

    def test_context_contains_masks_and_safe_defaults_only(self):
        with patch.object(frappe, "get_doc", return_value=self.lead), \
             patch.object(patient_intake, "current_capabilities", return_value=Capabilities()):
            result = patient_intake.context("L1")
        self.assertNotIn("2025550101", str(result))
        self.assertEqual(result["mask_mobile"], "******0101")
        self.assertEqual(result["defaults"]["first_name"], "Test")

    def test_encounter_patient_switch_uses_selected_patient(self):
        patient = MagicMock(); patient.get.return_value = "2025550199"
        with patch.object(frappe, "get_doc", return_value=patient):
            for kind in ["Appointment", "FollowUp", "Order"]:
                result = desk.prepare_payload({"doctype": "Patient Encounter", "name": "E1", "patient": "P2", "sr_encounter_type": kind},
                    {"doctype": "Patient Encounter", "name": "E1", "patient": "P1", "sr_pe_mobile": "2025550101"}, Capabilities())
                self.assertEqual(result["sr_pe_mobile"], "2025550199")
            patient.check_permission.side_effect = frappe.PermissionError
            with self.assertRaises(frappe.PermissionError):
                lifecycle.prepare_new({"doctype": "Patient Encounter", "patient": "P2"}, Capabilities())
