import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
import frappe
from privacy_shield.desk import project_document, prepare_payload, enabled
from privacy_shield.policy import Capabilities

class DeskTests(unittest.TestCase):
    def setUp(self):
        self.stored = {"doctype": "Contact", "name": "C-TEST", "modified": "2026-09-16",
            "mobile_no": "9876543210", "phone": "1234567890", "first_name": "Synthetic",
            "phone_nos": [{"name": "row-1", "phone": "9876543210", "is_primary_phone": 1}]}
        self.restricted = Capabilities()

    def test_read_projection_never_changes_source_document(self):
        before = deepcopy(self.stored)
        result = project_document(self.stored, self.restricted)
        self.assertNotIn("9876543210", str(result))
        self.assertNotIn("1234567890", str(result))
        self.assertEqual(result["mask_mobile"], "******3210")
        self.assertEqual(self.stored, before)

    def test_round_trip_unrelated_edit_preserves_originals_and_children(self):
        payload = project_document(self.stored, self.restricted)
        payload["first_name"] = "Updated"
        saved = prepare_payload(payload, self.stored, self.restricted)
        self.assertEqual(saved["mobile_no"], self.stored["mobile_no"])
        self.assertEqual(saved["phone"], self.stored["phone"])
        self.assertEqual(saved["phone_nos"], self.stored["phone_nos"])
        self.assertEqual(saved["first_name"], "Updated")
        self.assertNotIn("mask_mobile", saved)

    def test_omitted_child_table_restored(self):
        payload = {"doctype": "Contact", "name": "C-TEST"}
        self.assertEqual(prepare_payload(payload,self.stored,self.restricted)["phone_nos"],self.stored["phone_nos"])

    def test_clearing_number_or_removing_row_is_not_omission(self):
        for changes in [{"phone": None}, {"mobile_no": ""}, {"phone_nos": []}]:
            payload = {"doctype": "Contact", "name": "C-TEST", **changes}
            with self.assertRaises(PermissionError): prepare_payload(payload,self.stored,self.restricted)

    def test_full_view_is_not_edit_permission(self):
        payload = deepcopy(self.stored);payload["phone"] = "9999999999"
        with self.assertRaises(PermissionError): prepare_payload(payload,self.stored,Capabilities(True,False))

    def test_normalized_aliases_removed_and_restored(self):
        stored = {"doctype": "CRM Lead", "name": "L-TEST", "mobile_no": "9876543210",
                  "sr_mobile_norm": "9876543210", "vobiz_mobile_last10": "9876543210"}
        response = project_document(stored,self.restricted)
        self.assertNotIn("9876543210", str(response))
        self.assertEqual(prepare_payload(response,stored,self.restricted)["sr_mobile_norm"],stored["sr_mobile_norm"])

    def test_deferred_doctypes_not_projected(self):
        for dt in ["Chat Contact", "Vobiz Call Log", "Voice AI Encounter Queue"]:
            payload = {"doctype": dt, "phone_number": "9876543210"}
            self.assertEqual(project_document(payload,self.restricted),payload)

    def test_switch_is_off_by_default_and_scope_is_bounded(self):
        with patch.object(frappe, "conf", {}): self.assertFalse(enabled("Contact"))
        with patch.object(frappe, "conf", {"privacy_shield_desk_enabled": True}):
            self.assertTrue(enabled("CRM Lead"))
            self.assertFalse(enabled("Chat Contact"))

    def test_editor_cannot_tamper_with_derived_keys(self):
        stored = {"doctype": "CRM Lead", "name": "L-TEST", "sr_mobile_norm": "9876543210"}
        payload = {**stored, "sr_mobile_norm": "1234567890"}
        with self.assertRaises(PermissionError): prepare_payload(payload,stored,Capabilities(True,True))

    def test_wrapper_passes_through_when_disabled(self):
        from privacy_shield.desk import get
        p = patch.object(frappe.local,"flags",frappe._dict(in_test=True),create=True)
        with p, patch.object(frappe,"conf",{}), patch("frappe.client.get",return_value={"phone":"1234567890"}) as original:
            self.assertEqual(get("Contact","C-TEST"),{"phone":"1234567890"})
            original.assert_called_once_with("Contact","C-TEST",None,None)

    def test_save_wrapper_restores_before_calling_framework(self):
        from privacy_shield.desk import save
        payload = project_document(self.stored,self.restricted)
        fake = SimpleNamespace(check_permission=lambda kind: None,as_dict=lambda:deepcopy(self.stored))
        p = patch.object(frappe.local,"flags",frappe._dict(in_test=True),create=True)
        with p, patch.object(frappe,"conf",{"privacy_shield_desk_enabled":True}), \
             patch.object(frappe,"get_doc",return_value=fake), \
             patch("privacy_shield.desk.current_capabilities",return_value=self.restricted), \
             patch("frappe.client.save",side_effect=lambda d:d) as original:
            response = save(payload)
            self.assertEqual(original.call_args.args[0]["mobile_no"],"9876543210")
            self.assertNotIn("9876543210",str(response))

    def test_encounter_normalized_mobile_is_protected(self):
        stored = {"doctype":"Patient Encounter", "name":"E-TEST", "sr_pe_mobile":"2025550101", "sr_pe_mobile_norm":"2025550101"}
        projected = project_document(stored, self.restricted)
        self.assertNotIn("sr_pe_mobile_norm", projected)
        self.assertNotIn("2025550101", str(projected))
        self.assertEqual(projected["mask_mobile"], "******0101")
        restored = prepare_payload(projected, stored, self.restricted)
        self.assertEqual(restored["sr_pe_mobile_norm"], stored["sr_pe_mobile_norm"])
        with self.assertRaises(PermissionError):
            prepare_payload({**stored,"sr_pe_mobile_norm":"2025550199"},stored,Capabilities(True,True))
