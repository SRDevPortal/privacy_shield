import unittest
from copy import deepcopy
from unittest.mock import Mock, patch
import frappe
from privacy_shield.policy import Capabilities
from privacy_shield.raven_views import get_preview_data

NATIVE = "raven.api.document_link.get_preview_data"


class RavenPreviewTests(unittest.TestCase):
    def setUp(self):
        for item in (patch.object(frappe.local, "flags", frappe._dict(in_test=True), create=True),
                     patch.object(frappe, "conf", {"privacy_shield_desk_enabled": True})):
            item.start()
            self.addCleanup(item.stop)
        self.meta = Mock(image_field="image")
        self.meta.get_title_field.return_value = "patient_name"
        labels = {"mobile_number": "Mobile", "alternate_mobile": "Alternate"}
        self.meta.get_field.side_effect = lambda name: frappe._dict(label=labels[name]) if name in labels else None
        self.data = {"Mobile": '<a href="tel:2025550101">2025550101</a>',
                     "Alternate": "2025550199", "Status": "Scheduled", "id": "SYNTHETIC",
                     "preview_title": "Synthetic patient", "preview_image": None}

    def test_protected_formatted_fields_removed_without_mutation(self):
        before = deepcopy(self.data)
        with patch(NATIVE, return_value=self.data) as native, \
             patch("privacy_shield.raven_views.current_capabilities", return_value=Capabilities()), \
             patch.object(frappe, "get_meta", return_value=self.meta):
            result = get_preview_data("Clinic Appointment", "SYNTHETIC")
            native.assert_called_once_with("Clinic Appointment", "SYNTHETIC")
            self.assertNotIn("202555", str(result))
            self.assertEqual(result["Status"], "Scheduled")
            self.assertEqual(self.data, before)

    def test_title_and_image_cannot_carry_protected_fields(self):
        self.meta.get_title_field.return_value = "mobile_number"
        self.meta.image_field = "alternate_mobile"
        data = {"preview_title": "2025550101", "preview_image": "2025550199"}
        with patch(NATIVE, return_value=data), \
             patch("privacy_shield.raven_views.current_capabilities", return_value=Capabilities()), \
             patch.object(frappe, "get_meta", return_value=self.meta):
            result = get_preview_data("Clinic Appointment", "SYNTHETIC")
            self.assertEqual(result, {"preview_title": "Restricted preview", "preview_image": None})

    def test_native_permission_failure_propagates(self):
        with patch(NATIVE, side_effect=frappe.PermissionError), \
             patch("privacy_shield.raven_views.current_capabilities") as policy:
            with self.assertRaises(frappe.PermissionError):
                get_preview_data("Patient", "DENIED")
            policy.assert_not_called()

    def test_full_view_preserves_native_result(self):
        with patch(NATIVE, return_value=self.data), \
             patch("privacy_shield.raven_views.current_capabilities", return_value=Capabilities(True, False)):
            self.assertIs(get_preview_data("Clinic Appointment", "SYNTHETIC"), self.data)

    def test_gate_off_and_excluded_types_do_not_evaluate_policy(self):
        with patch(NATIVE, return_value=self.data), \
             patch("privacy_shield.raven_views.current_capabilities") as policy:
            for dt in ("Chat Contact", "Vobiz Call Log", "Task"):
                self.assertIs(get_preview_data(dt, "SYNTHETIC"), self.data)
            with patch.object(frappe, "conf", {}):
                self.assertIs(get_preview_data("Patient", "SYNTHETIC"), self.data)
            policy.assert_not_called()

    def test_empty_native_result_unchanged(self):
        with patch(NATIVE, return_value=None), \
             patch("privacy_shield.raven_views.current_capabilities") as policy:
            self.assertIsNone(get_preview_data("Patient", "SYNTHETIC"))
            policy.assert_not_called()

    def test_derived_alias_label_removed(self):
        self.meta.get_field.side_effect = lambda name: frappe._dict(label="Normalized") if name == "sr_mobile_norm" else None
        with patch(NATIVE, return_value={"Normalized": "2025550101", "Status": "Open"}), \
             patch("privacy_shield.raven_views.current_capabilities", return_value=Capabilities()), \
             patch.object(frappe, "get_meta", return_value=self.meta):
            self.assertEqual(get_preview_data("CRM Lead", "SYNTHETIC"), {"Status": "Open"})
