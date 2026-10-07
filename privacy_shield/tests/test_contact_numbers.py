import unittest
from unittest.mock import patch
import frappe
from privacy_shield.policy import Capabilities, evaluate
from privacy_shield.contact_numbers import plan_rows, normalize

class ContactNumberTests(unittest.TestCase):
    def setUp(self):
        self.rows = [{"name": "old", "phone": "9876501234", "is_primary_mobile_no": 1, "is_primary_phone": 1}]

    def test_add_does_not_grant_read(self):
        caps = evaluate(["Agent"], [{"role": "Agent", "add_contact_numbers": 1, "change_primary_number": 1}], "agent")
        self.assertFalse(caps.view_full)
        self.assertFalse(caps.edit_original)
        self.assertTrue(caps.add_contact_numbers)

    def test_preserves_old_and_separates_primary_flags(self):
        caps = Capabilities(add_contact_numbers=True, change_primary_number=True)
        result = plan_rows(self.rows, ["+91 9876501235"], "@new:0", None, caps)
        self.assertEqual(result[0]["phone"], "9876501234")
        self.assertEqual(result[0]["is_primary_mobile_no"], 0)
        self.assertEqual(result[0]["is_primary_phone"], 1)
        self.assertEqual(result[1]["phone"], "9876501235")
        self.assertEqual(result[1]["is_primary_mobile_no"], 1)
        self.assertEqual(self.rows[0]["is_primary_mobile_no"], 1)

    def test_add_only_cannot_change_primary(self):
        with self.assertRaises(frappe.PermissionError):
            plan_rows(self.rows, ["9876501235"], "@new:0", None, Capabilities(add_contact_numbers=True))

    def test_primary_only_cannot_add(self):
        with self.assertRaises(frappe.PermissionError):
            plan_rows(self.rows, ["9876501235"], None, None, Capabilities(change_primary_number=True))

    def test_select_existing_without_raw_value(self):
        result = plan_rows(self.rows, [], "old", "old", Capabilities(change_primary_number=True))
        self.assertEqual(result[0]["phone"], self.rows[0]["phone"])

    def test_foreign_row_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            plan_rows(self.rows, [], "foreign", None, Capabilities(change_primary_number=True))

    def test_duplicate_normalized_input_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            plan_rows(self.rows, ["+91 9876501234"], None, None, Capabilities(add_contact_numbers=True))

    def test_masks_and_invalid_numbers_rejected(self):
        for value in ["******1234", "1234", "1e123456789", "1234567890123456"]:
            with self.subTest(value=value), self.assertRaises(frappe.ValidationError):
                normalize(value)

    def test_form_encoded_keep_primary_phone(self):
        result = plan_rows(self.rows, ["9876501235"], "@new:0", "",
                           Capabilities(add_contact_numbers=True, change_primary_number=True))
        self.assertEqual(result[0]["is_primary_phone"], 1)
        self.assertEqual(result[1]["is_primary_mobile_no"], 1)

    def test_form_encoded_add_only_keeps_both_primaries(self):
        result = plan_rows(self.rows, ["9876501235"], "", "",
                           Capabilities(add_contact_numbers=True))
        self.assertEqual(result[0], self.rows[0])

    def test_new_primary_requires_an_added_number(self):
        with self.assertRaises(frappe.ValidationError):
            plan_rows(self.rows, [], "@new:0", "", Capabilities(change_primary_number=True))

    def test_context_disables_actions_without_record_write(self):
        from privacy_shield.contact_numbers import context
        with patch('privacy_shield.contact_numbers.load_contact', side_effect=[object(), frappe.PermissionError()]), patch('privacy_shield.contact_numbers.describe', return_value={"can_add": True, "can_primary": True}):
            self.assertEqual(context('Contact', 'test'), {"can_add": False, "can_primary": False})

    def test_update_checks_record_write_before_mutation(self):
        from privacy_shield.contact_numbers import update
        with patch('privacy_shield.contact_numbers.load_contact', side_effect=frappe.PermissionError()) as load, patch('privacy_shield.contact_numbers.plan_rows') as plan:
            with self.assertRaises(frappe.PermissionError):
                update('Contact', 'test', 'version', ['9876501235'], '@new:0')
            load.assert_called_once_with('Contact', 'test', write=True)
            plan.assert_not_called()

    def test_new_number_cannot_have_both_primary_flags(self):
        with self.assertRaises(frappe.ValidationError):
            plan_rows(self.rows, ["9876501235"], "@new:0", "@new:0",
                      Capabilities(add_contact_numbers=True, change_primary_number=True))

    def test_new_phone_keeps_old_mobile(self):
        result = plan_rows(self.rows, ["9876501235"], None, "@new:0",
                           Capabilities(add_contact_numbers=True, change_primary_number=True))
        self.assertEqual(result[0]["is_primary_mobile_no"], 1)
        self.assertEqual(result[1]["is_primary_phone"], 1)
        self.assertEqual(result[1]["is_primary_mobile_no"], 0)

    def test_inline_new_number_cannot_have_both_primary_flags(self):
        from privacy_shield.child_rows import preserve_contact_rows
        row = dict(name="new-row", __islocal=1, phone="9876501235",
                   is_primary_mobile_no=1, is_primary_phone=1)
        with self.assertRaises(ValueError):
            preserve_contact_rows(self.rows + [row], self.rows, can_add=True, can_primary=True)

    def test_administrator_bypasses_contact_row_restrictions(self):
        from privacy_shield.desk import prepare_payload, project_document
        caps = evaluate([], [], 'Administrator')
        self.assertTrue(caps.bypass_privacy)
        self.assertTrue(caps.enter_new_numbers)
        stored = dict(doctype='Contact', name='test', phone_nos=self.rows)
        submitted = dict(stored, phone_nos=[])
        self.assertEqual(prepare_payload(submitted, stored, caps)['phone_nos'], [])
        self.assertNotIn('__privacy_shield', project_document(stored, caps))
        self.assertFalse(evaluate(['System Manager'], [{'role': 'System Manager'}], 'manager').bypass_privacy)

    def test_administrator_can_use_both_primary_types(self):
        result = plan_rows(self.rows, ['9876501235'], '@new:0', '@new:0', evaluate([], [], 'Administrator'))
        self.assertTrue(result[-1]['is_primary_mobile_no'])
        self.assertTrue(result[-1]['is_primary_phone'])
