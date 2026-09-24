"""Synthetic regression cases for alias and activation boundaries; no providers."""
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from privacy_shield.activation import enabled_for
from privacy_shield.desk import prepare_payload, project_document
from privacy_shield.lifecycle import prepare_new
from privacy_shield.listing import get_list, get_value, project_rows, validate_query
from privacy_shield.policy import Capabilities, current_capabilities, evaluate

ALIASES = {
    "Patient": ("vobiz_normalized_phone", "vobiz_mobile_last10", "vobiz_phone_last10"),
    "Customer": ("vobiz_normalized_phone", "vobiz_mobile_last10"),
    "CRM Lead": ("vobiz_normalized_phone",),
}
SOURCE = {"Patient": "mobile", "Customer": "mobile_no", "CRM Lead": "mobile_no"}


class PriorityOneTests(unittest.TestCase):
    def setUp(self):
        for item in (
            patch.object(frappe.local, "flags", frappe._dict(in_test=True), create=True),
            patch.object(frappe, "conf", {"privacy_shield_desk_enabled": True}),
        ):
            item.start()
            self.addCleanup(item.stop)

    def records(self):
        for doctype, aliases in ALIASES.items():
            yield doctype, aliases, {
                "doctype": doctype, "name": "SYNTHETIC-PRIORITY-ONE",
                SOURCE[doctype]: "2025550101", "modified": "2026-09-21",
                **{alias: "2025550101" for alias in aliases},
            }

    def test_restricted_projection_removes_all_six_aliases_without_mutating_source(self):
        for dt, aliases, stored in self.records():
            with self.subTest(doctype=dt):
                before = deepcopy(stored)
                result = project_document(stored, Capabilities())
                self.assertFalse(set(aliases).intersection(result))
                self.assertNotIn("2025550101", str(result))
                self.assertEqual(result["mask_mobile"], "******0101")
                self.assertEqual(stored, before)

    def test_full_view_retains_aliases(self):
        for dt, aliases, stored in self.records():
            with self.subTest(doctype=dt):
                result = project_document(stored, Capabilities(True, False))
                self.assertTrue(all(result[alias] == stored[alias] for alias in aliases))

    def test_unrelated_save_restores_all_aliases_and_original_source(self):
        for dt, aliases, stored in self.records():
            with self.subTest(doctype=dt):
                submitted = project_document(stored, Capabilities())
                submitted["synthetic_description"] = "Edited without number access"
                result = prepare_payload(submitted, stored, Capabilities())
                self.assertTrue(all(result[key] == stored[key] for key in (*aliases, SOURCE[dt])))
                self.assertEqual(result["synthetic_description"], submitted["synthetic_description"])
                self.assertNotIn("mask_mobile", result)

    def test_alias_tampering_denied_even_for_original_number_editor(self):
        for dt, aliases, stored in self.records():
            for alias in aliases:
                for value in (None, "", "2025550199"):
                    with self.subTest(doctype=dt, field=alias, value=value):
                        with self.assertRaises(PermissionError):
                            prepare_payload({**stored, alias: value}, stored, Capabilities(True, True))

    def test_new_record_aliases_must_be_generated_by_server(self):
        for dt, aliases, stored in self.records():
            for alias in aliases:
                with self.subTest(doctype=dt, field=alias), self.assertRaises(frappe.PermissionError):
                    prepare_new({"doctype": dt, alias: stored[alias]}, Capabilities(True, True))
            result = prepare_new({"doctype": dt, **dict.fromkeys(aliases, "")}, Capabilities())
            self.assertFalse(set(aliases).intersection(result))

    def test_selected_alias_lists_and_single_values_do_not_disclose(self):
        with patch("privacy_shield.listing.current_capabilities", return_value=Capabilities()):
            for dt, aliases, stored in self.records():
                with self.subTest(doctype=dt), patch("frappe.client.get_list", return_value=[stored]):
                    self.assertEqual(get_list(dt, list(aliases)), [{}])
                    self.assertEqual(get_value(dt, aliases[0], stored["name"]), {})
                    self.assertIsNone(get_value(dt, aliases[0], stored["name"], as_dict=False))

    def test_positional_alias_projection_retains_column_shape(self):
        for dt, aliases, stored in self.records():
            with self.subTest(doctype=dt):
                self.assertEqual(project_rows(dt, [stored], aliases, aliases, as_dict=False),
                                 [[None] * len(aliases)])
                self.assertEqual(project_rows(dt, [stored], aliases, aliases, full=True),
                                 [{alias: stored[alias] for alias in aliases}])

    def test_alias_filters_cannot_be_used_as_a_number_oracle(self):
        for dt, aliases, stored in self.records():
            for alias in aliases:
                with self.subTest(doctype=dt, field=alias), self.assertRaises(frappe.PermissionError):
                    validate_query(dt, {alias: ["like", "202%"]}, None, None, None, False)
                validate_query(dt, {alias: stored[alias]}, None, None, None, True)

    def test_document_reader_still_enforces_native_permission(self):
        from privacy_shield.desk import get
        with patch("frappe.client.get", side_effect=frappe.PermissionError), \
             patch("privacy_shield.desk.current_capabilities") as policy:
            with self.assertRaises(frappe.PermissionError):
                get("Patient", "SYNTHETIC-NO-ACCESS")
            policy.assert_not_called()

    def test_compatibility_adapters_remain_enabled_with_main_switch_off(self):
        with patch.object(frappe, "conf", {}), \
             patch.object(frappe, "get_installed_apps", return_value=["privacy_shield"]):
            self.assertFalse(enabled_for("core_document", "Patient"))
            self.assertTrue(enabled_for("appointment_patient_details"))
            self.assertTrue(enabled_for("support_customer_details"))

    def test_unknown_or_deferred_routes_never_enabled(self):
        with patch.object(frappe, "get_installed_apps", return_value=["privacy_shield"]):
            for dt in ("Chat Contact", "Vobiz Call Log", "Voice AI Encounter Queue", "Vobiz Blocked Number"):
                self.assertFalse(enabled_for("core_document", dt))
            self.assertFalse(enabled_for("wa_chat_hub"))
            self.assertFalse(enabled_for("support_customer_details", "Chat Contact"))

    def test_compatibility_adapter_requires_installation(self):
        with patch.object(frappe, "get_installed_apps", return_value=[]):
            self.assertFalse(enabled_for("appointment_patient_details"))
            self.assertFalse(enabled_for("support_customer_details"))

    def test_role_matrix_preserves_separate_view_and_edit_grants(self):
        rules = [
            {"role": "Agent", "view_full": 0, "edit_original": 0},
            {"role": "Team Leader", "view_full": 1, "edit_original": 0},
            {"role": "System Manager", "view_full": 1, "edit_original": 1},
        ]
        for roles, user, expected in (
            (["Agent"], "synthetic", Capabilities()),
            (["Agent", "Team Leader"], "synthetic", Capabilities(True, False)),
            (["System Manager"], "synthetic", Capabilities(True, True)),
            ([], "synthetic", Capabilities()),
            (["System Manager"], "Guest", Capabilities()),
            ([], "Administrator", Capabilities(True, True)),
        ):
            with self.subTest(roles=roles, user=user):
                self.assertEqual(evaluate(roles, rules, user), expected)

    def test_capabilities_reread_effective_roles_and_rules_after_revocation(self):
        rules = [{"role": "Profile Viewer", "view_full": 1, "edit_original": 0}]
        settings = SimpleNamespace(get=lambda key: rules)
        with patch.object(frappe, "get_single", return_value=settings) as reader, \
             patch.object(frappe, "get_roles", side_effect=[
                 ["Agent", "Profile Viewer"], ["Agent"], ["Agent", "Profile Viewer"]
             ]) as role_reader:
            self.assertEqual(current_capabilities("synthetic"), Capabilities(True, False))
            self.assertEqual(current_capabilities("synthetic"), Capabilities())
            rules.clear()
            self.assertEqual(current_capabilities("synthetic"), Capabilities())
            self.assertEqual(reader.call_count, 3)
            self.assertEqual(role_reader.call_count, 3)

    def test_legacy_lookup_responses_stay_masked_when_pilot_off(self):
        from clinic_appointments.api.patient_details import get_patient_details
        from support_patch.issue import get_customer_details
        values = {"mobile": "2025550101", "phone": "2025550102", "mobile_no": "2025550101"}
        doc = SimpleNamespace(name="SYNTHETIC", customer_name="Synthetic", get=values.get,
                              permitted_fieldnames=set(values),
                              meta=SimpleNamespace(has_field=lambda key: False),
                              check_permission=lambda kind: None)
        with patch.object(frappe, "conf", {}), \
             patch.object(frappe, "get_installed_apps", return_value=["privacy_shield"]), \
             patch.object(frappe, "get_doc", return_value=doc), \
             patch("privacy_shield.policy.current_capabilities", return_value=Capabilities()):
            appointment = get_patient_details("SYNTHETIC")
            support = get_customer_details("SYNTHETIC")
            self.assertEqual(appointment["mask_mobile"], "******0101")
            self.assertEqual(appointment["mask_phone"], "******0102")
            self.assertTrue(appointment["resolve_numbers_on_server"])
            self.assertEqual(support["mask_mobile"], "******0101")
            self.assertNotIn("2025550101", str((appointment, support)))

    def test_save_wrapper_passes_preserved_aliases_to_native_save(self):
        from privacy_shield.desk import save
        for dt, aliases, stored in self.records():
            native_doc = SimpleNamespace(check_permission=lambda kind: None,
                                         as_dict=lambda: deepcopy(stored))
            submitted = project_document(stored, Capabilities())
            with self.subTest(doctype=dt), \
                 patch.object(frappe, "get_doc", return_value=native_doc), \
                 patch("privacy_shield.desk.current_capabilities", return_value=Capabilities()), \
                 patch("frappe.client.save", side_effect=lambda value: value) as native_save:
                result = save(submitted)
                passed = native_save.call_args.args[0]
                self.assertTrue(all(passed[field] == stored[field] for field in (*aliases, SOURCE[dt])))
                self.assertNotIn("2025550101", str(result))
