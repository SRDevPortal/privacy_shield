import unittest
from unittest.mock import patch, MagicMock
import frappe
from privacy_shield import link_fetch
from privacy_shield.policy import Capabilities


class LinkFetchTests(unittest.TestCase):
    def setUp(self):
        p = patch.object(frappe.local, "flags", frappe._dict(in_test=True), create=True)
        p.start(); self.addCleanup(p.stop)

    def test_restricted_fetch_never_passes_fields_to_native_internal_reader(self):
        with patch.object(link_fetch, "enabled", return_value=True), \
             patch.object(link_fetch, "current_capabilities", return_value=Capabilities()), \
             patch("frappe.client.validate_link", return_value={"name": "P1"}) as native, \
             patch("privacy_shield.listing.get_value", return_value={"mask_mobile": "******0101", "patient_name": "Test"}) as read:
            result = link_fetch.validate_link("Patient", "P1", '["mobile","patient_name"]')
            native.assert_called_once_with("Patient", "P1")
            read.assert_called_once_with("Patient", ["mobile", "patient_name"], filters={"name": "P1"})
            self.assertNotIn("mobile", result)
            self.assertEqual(result["mask_mobile"], "******0101")
            self.assertEqual(result["patient_name"], "Test")

    def test_no_fetch_does_not_add_read_requirement(self):
        with patch.object(link_fetch, "enabled", return_value=True), \
             patch.object(link_fetch, "current_capabilities", return_value=Capabilities()), \
             patch("frappe.client.validate_link", return_value={"name": "P1"}), \
             patch("privacy_shield.listing.get_value") as read:
            self.assertEqual(link_fetch.validate_link("Patient", "P1"), {"name": "P1"})
            read.assert_not_called()

    def test_full_viewer_retains_native_fetch(self):
        with patch.object(link_fetch, "enabled", return_value=True), \
             patch.object(link_fetch, "current_capabilities", return_value=Capabilities(True, False)), \
             patch("frappe.client.validate_link", return_value={"mobile": "2025550101"}) as native:
            self.assertEqual(link_fetch.validate_link("Patient", "P1", '["mobile"]')["mobile"], "2025550101")
            native.assert_called_once_with("Patient", "P1", '["mobile"]')

    def test_patient_details_require_read_and_project_numbers(self):
        doc = MagicMock()
        with patch.object(link_fetch, "enabled", return_value=True), \
             patch.object(link_fetch, "current_capabilities", return_value=Capabilities()), \
             patch.object(frappe, "get_doc", return_value=doc), \
             patch("healthcare.healthcare.doctype.patient.patient.get_patient_detail", return_value={"name":"P1", "mobile":"2025550101", "phone":"2025550102", "patient_name":"Test"}) as native:
            result = link_fetch.get_patient_detail("P1")
            self.assertNotIn("2025550101", str(result))
            self.assertNotIn("2025550102", str(result))
            self.assertEqual(result["patient_name"], "Test")
            doc.check_permission.assert_called_once_with("read")
            doc.check_permission.side_effect = frappe.PermissionError
            with self.assertRaises(frappe.PermissionError): link_fetch.get_patient_detail("P1")
            self.assertEqual(native.call_count, 1)

    def test_encounter_context_returns_only_mask_and_policy(self):
        doc = MagicMock(); doc.get.return_value = "2025550101"
        with patch.object(link_fetch, "enabled", return_value=True), \
             patch.object(link_fetch, "current_capabilities", return_value=Capabilities()), \
             patch.object(frappe, "get_doc", return_value=doc):
            result = link_fetch.encounter_context("P1")
            self.assertEqual(result["mask_mobile"], "******0101")
            self.assertNotIn("2025550101", str(result))
            doc.check_permission.assert_called_once_with("read")

    def test_appointment_context_returns_mask_only_for_restricted_user(self):
        doc = MagicMock()
        doc.get.return_value = "2025550101"
        with patch.object(link_fetch, "enabled", return_value=True), \
             patch.object(link_fetch, "current_capabilities", return_value=Capabilities()), \
             patch.object(frappe, "get_doc", return_value=doc):
            result = link_fetch.appointment_context("P1")
        self.assertEqual(result["mask_mobile"], "******0101")
        self.assertNotIn("2025550101", str(result))
        doc.check_permission.assert_called_once_with("read")

    def test_appointment_context_does_not_read_mobile_for_full_viewer(self):
        with patch.object(link_fetch, "enabled", return_value=True), \
             patch.object(link_fetch, "current_capabilities",
                          return_value=Capabilities(True, False)), \
             patch.object(frappe, "get_doc") as get_doc:
            result = link_fetch.appointment_context("P1")
        self.assertTrue(result["view_full"])
        self.assertEqual(result["mask_mobile"], "")
        get_doc.assert_not_called()

    def test_direct_child_fetch_is_not_an_escape_route(self):
        with patch.object(link_fetch, "enabled", return_value=True):
            with self.assertRaises(frappe.PermissionError):
                link_fetch.validate_link("Contact Phone", "ROW1", '["phone"]')
