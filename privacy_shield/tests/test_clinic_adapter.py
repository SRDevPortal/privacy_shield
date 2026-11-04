import importlib
import unittest
from types import SimpleNamespace
from unittest.mock import patch, Mock
import frappe
from privacy_shield import clinic


class ClinicAdapterTests(unittest.TestCase):
    def resolve(self, registrations, installed):
        return patch.multiple(frappe, get_hooks=Mock(return_value=registrations), get_installed_apps=Mock(return_value=installed))

    def test_site_selection_is_not_cached_across_clinics(self):
        for app in ("sriaas_clinic", "siya_clinic", "sriaas_clinic"):
            module = SimpleNamespace(__name__=app + ".privacy_adapter", ENDPOINTS={"action": app + ".api.action"})
            with self.resolve([app + ".privacy_adapter"], [app]), patch.object(importlib, "import_module", return_value=module), patch.object(frappe, "get_attr", return_value="callable") as lookup:
                self.assertEqual(clinic.endpoint("action"), "callable")
                lookup.assert_called_once_with(app + ".api.action")

    def test_missing_multiple_or_uninstalled_adapters_are_rejected(self):
        for entries, installed in [([], []), (["a.adapter", "b.adapter"], ["a", "b"]), (["a.adapter"], [])]:
            with self.resolve(entries, installed), self.assertRaises(frappe.ValidationError):
                clinic.adapter()

    def test_duplicate_registration_of_same_adapter_is_harmless(self):
        with self.resolve(["a.adapter", "a.adapter"], ["a"]), patch.object(importlib, "import_module", return_value="module"):
            self.assertEqual(clinic.adapter(), "module")

    def test_unsupported_actions_and_cross_app_endpoints_are_rejected(self):
        module = SimpleNamespace(__name__="siya_clinic.privacy_adapter", ENDPOINTS={"bad": "sriaas_clinic.api.action"})
        with patch.object(clinic, "adapter", return_value=module), patch.object(frappe, "get_attr") as lookup:
            for action in ("missing", "bad"):
                with self.assertRaises(frappe.ValidationError):
                    clinic.endpoint(action)
            lookup.assert_not_called()

    def test_encounter_route_forwards_only_selected_patient(self):
        fn = Mock(return_value={"enabled": False})
        with patch.object(clinic, "endpoint", return_value=fn):
            self.assertEqual(clinic.get_encounter_context.__wrapped__("PAT-TEST"), {"enabled": False})
            fn.assert_called_once_with(patient="PAT-TEST")

    def test_missing_and_traversal_templates_are_rejected(self):
        for template in (None, "../other/file.html", "/tmp/file.html"):
            module = SimpleNamespace(__name__="siya_clinic.privacy_adapter", TEMPLATES={"preview": template})
            with patch.object(clinic, "adapter", return_value=module), self.assertRaises(frappe.ValidationError):
                clinic.template_path("preview")
