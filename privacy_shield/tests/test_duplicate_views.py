import unittest
from copy import deepcopy
from unittest.mock import patch
import frappe
from privacy_shield.duplicate_views import project_duplicate_rows
from privacy_shield.policy import Capabilities
from sriaas_clinic.api.crm_lead.privacy_duplicates import get_duplicates_for_crm_lead

NATIVE = "crm_lead_dedupe.api.crm_lead_duplicates.get_duplicates_for_crm_lead"


class DuplicateViewTests(unittest.TestCase):
    def setUp(self):
        for item in (
            patch.object(frappe.local, "flags", frappe._dict(in_test=True), create=True),
            patch.object(frappe, "conf", {"privacy_shield_desk_enabled": True}),
        ):
            item.start(); self.addCleanup(item.stop)
        self.rows = [{"name": "SYNTHETIC-2", "mobile_no": "2025550101", "phone": "2025550199",
                      "score": 100.0, "stage": "New", "sr_mobile_norm": "2025550101",
                      "vobiz_normalized_phone": "2025550101", "vobiz_mobile_last10": "2025550101",
                      "vobiz_phone_last10": "2025550199"}]

    def test_masked_column_contract_and_alias_removal(self):
        before = deepcopy(self.rows)
        result = project_duplicate_rows(self.rows)
        self.assertEqual(result[0]["mobile_no"], "******0101")
        self.assertEqual(result[0]["phone"], "******0199")
        self.assertEqual(result[0]["mask_mobile"], result[0]["mobile_no"])
        self.assertEqual(result[0]["mask_phone"], result[0]["phone"])
        self.assertEqual(result[0]["score"], 100.0)
        self.assertEqual(result[0]["name"], "SYNTHETIC-2")
        self.assertNotIn("2025550101", str(result))
        self.assertNotIn("2025550199", str(result))
        self.assertEqual(self.rows, before)

    def test_absent_columns_not_invented_and_order_preserved(self):
        rows = [{"name": "B", "score": 100}, {"name": "A", "score": 80}]
        self.assertEqual(project_duplicate_rows(rows), rows)
        self.assertEqual(project_duplicate_rows([]), [])

    def test_empty_short_and_ambiguous_display_values(self):
        for value, expected in [(None, ""), ("", ""), ("1234", "****"),
                                ("2025550101 / 2025550199", "[masked]")]:
            with self.subTest(value=value):
                self.assertEqual(project_duplicate_rows([{"mobile_no": value}])[0]["mobile_no"], expected)

    def test_restricted_wrapper_delegates_arguments_and_projects_after_native(self):
        with patch(NATIVE, return_value=self.rows) as native, \
             patch("privacy_shield.policy.current_capabilities", return_value=Capabilities()):
            result = get_duplicates_for_crm_lead("SYNTHETIC-1", ["mobile_no", "phone"])
            native.assert_called_once_with("SYNTHETIC-1", ["mobile_no", "phone"])
            self.assertEqual(result, project_duplicate_rows(self.rows))

    def test_full_view_and_gate_off_preserve_native_contract(self):
        with patch(NATIVE, return_value=self.rows), \
             patch("privacy_shield.policy.current_capabilities", return_value=Capabilities(True, False)) as policy:
            self.assertIs(get_duplicates_for_crm_lead("SYNTHETIC-1"), self.rows)
            policy.reset_mock()
            with patch.object(frappe, "conf", {}):
                self.assertIs(get_duplicates_for_crm_lead("SYNTHETIC-1"), self.rows)
                policy.assert_not_called()

    def test_native_authorization_failure_never_returns_rows(self):
        with patch(NATIVE, side_effect=frappe.PermissionError), \
             patch("privacy_shield.policy.current_capabilities") as policy:
            with self.assertRaises(frappe.PermissionError):
                get_duplicates_for_crm_lead("SYNTHETIC-DENIED")
            policy.assert_not_called()

    def test_request_policy_is_not_cached_between_calls(self):
        with patch(NATIVE, return_value=self.rows), \
             patch("privacy_shield.policy.current_capabilities", side_effect=[Capabilities(True, False), Capabilities()]):
            self.assertEqual(get_duplicates_for_crm_lead("SYNTHETIC-1")[0]["mobile_no"], "2025550101")
            self.assertEqual(get_duplicates_for_crm_lead("SYNTHETIC-1")[0]["mobile_no"], "******0101")

    def test_native_empty_result_stays_empty(self):
        with patch(NATIVE, return_value=[]), \
             patch("privacy_shield.policy.current_capabilities", return_value=Capabilities()):
            self.assertEqual(get_duplicates_for_crm_lead("SYNTHETIC-1"), [])
