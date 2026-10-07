import unittest
from privacy_shield.masking import mask_number, virtual_expression
from privacy_shield.policy import evaluate
from privacy_shield.guards import preserve_sources
from privacy_shield.registry import DISPLAY_FIELDS

class FoundationTests(unittest.TestCase):
    def test_masking(self):
        cases = [("9876543210 1234567890", "[masked]"), (None, ""), ("", ""), ("1234", "****"), ("9876543210", "******3210"),
                 ("+91 (98765) 43210", "********3210"), ("123456/987654", "[masked]"),
                 ("call 9876543210", "[masked]"), ("---", "[masked]")]
        for value, expected in cases:
            with self.subTest(value=value): self.assertEqual(mask_number(value), expected)

    def test_roles(self):
        rules = [{"role": "Viewer", "view_full": 1}, {"role": "Editor", "edit_original": 1}]
        self.assertTrue(evaluate(["System Manager"], [], "manager").view_full)
        self.assertTrue(evaluate(["Agent", "Viewer"], rules, "user").view_full)
        self.assertFalse(evaluate(["Viewer"], rules, "user").edit_original)
        self.assertTrue(evaluate(["Editor"], rules, "user").edit_original)
        self.assertFalse(evaluate(["Viewer"], rules, "Guest").view_full)
        self.assertTrue(evaluate([], [], "Administrator").view_full)
        self.assertTrue(evaluate(["Viewer"], [], "user").view_full)

    def test_only_listed_roles_are_masked(self):
        rules = [{"role": "Agent", "view_full": 0},
                 {"role": "Viewer", "view_full": 1}]
        for roles, full in [(["Repeat Agent"], True), (["Agent"], False),
                            (["Viewer"], True), (["Repeat Agent", "Agent"], False),
                            (["Repeat Agent", "Agent", "Viewer"], True)]:
            with self.subTest(roles=roles):
                caps = evaluate(roles, rules, "staff")
                self.assertEqual(caps.view_full, full)
                unlisted = not any(rule["role"] in roles for rule in rules)
                self.assertEqual(caps.edit_original, unlisted)
                self.assertEqual(caps.enter_new_numbers, unlisted)
                self.assertEqual(caps.add_contact_numbers, unlisted)
                self.assertEqual(caps.change_primary_number, unlisted)
                self.assertEqual(caps.bypass_privacy, unlisted)

    def test_unlisted_guest_does_not_receive_full_visibility(self):
        for user in (None, "Guest"):
            self.assertFalse(evaluate(["Repeat Agent"], [], user).view_full)

    def test_role_visibility_reaches_patient_list_and_form(self):
        from privacy_shield.listing import project_rows
        from privacy_shield.desk import project_document
        rules = [{"role": "Agent", "view_full": 0}, {"role": "Viewer", "view_full": 1}]
        for role, full in [("Repeat Agent", True), ("Agent", False), ("Viewer", True)]:
            with self.subTest(role=role):
                caps = evaluate([role], rules, "staff")
                expected = "9876543210" if full else "******3210"
                key = "mobile" if full else "mask_mobile"
                rows = project_rows("Patient", [{"mobile": "9876543210"}],
                                    ["mobile"], ["mobile"], caps.view_full)
                self.assertEqual(rows[0][key], expected)
                doc = project_document({"doctype": "Patient", "mobile": "9876543210"}, caps)
                self.assertEqual(doc[key], expected)
                if caps.bypass_privacy:
                    self.assertNotIn("__privacy_shield", doc)
                else:
                    self.assertEqual(doc["__privacy_shield"]["view_full"], full)

    def test_save_boundary(self):
        stored = {"mobile_no": "9876543210"}
        submitted = {"first_name": "Changed"}
        self.assertEqual(preserve_sources(submitted, stored, ["mobile_no"])["mobile_no"], stored["mobile_no"])
        self.assertNotIn("mobile_no", submitted)
        for value in [None, "", "1234567890"]:
            with self.assertRaises(PermissionError):
                preserve_sources({"mobile_no": value}, stored, ["mobile_no"])
        for value in ["******3210", "[masked]"]:
            with self.assertRaises(ValueError):
                preserve_sources({"mobile_no": value}, stored, ["mobile_no"], True)
        self.assertEqual(preserve_sources({"mobile_no": "123"}, stored, ["mobile_no"], True)["mobile_no"], "123")

    def test_phone_mobile_are_distinct(self):
        self.assertEqual(DISPLAY_FIELDS["Contact"], {"mobile_no": "mask_mobile", "phone": "mask_phone"})
        self.assertEqual(DISPLAY_FIELDS["Contact Phone"], {"phone": "mask_phone"})
        self.assertEqual(DISPLAY_FIELDS["Patient Appointment"], {"apt_mobile_number": "mask_mobile"})

    def test_virtual_expression_in_frappe(self):
        from frappe.utils.safe_exec import safe_eval, get_python_builtins
        globals_for_virtual = {**get_python_builtins(), "_getiter_": iter}
        for value in ["9876543210 1234567890", None, "", "12", "1234", "9876543210", "+91 (98765) 43210", "123/456", "---"]:
            with self.subTest(value=value):
                self.assertEqual(safe_eval(virtual_expression("phone"), eval_globals=globals_for_virtual.copy(), eval_locals={"doc": {"phone": value}}), mask_number(value))

    def test_unlisted_users_keep_native_contact_and_encounter_edits(self):
        from privacy_shield.desk import prepare_payload
        from privacy_shield.lifecycle import prepare_new
        caps = evaluate(["Repeat Agent"], [{"role": "Agent"}], "staff")
        stored = {"doctype": "Contact", "name": "C1", "phone_nos": [
            {"name": "R1", "phone": "2025550101"}]}
        self.assertEqual(prepare_payload({"doctype": "Contact", "name": "C1", "phone_nos": []}, stored, caps)["phone_nos"], [])
        data = {"doctype": "Patient Encounter", "sr_pe_mobile": "2025550199"}
        self.assertEqual(prepare_new(data, caps), data)
        self.assertNotIn("ignore_permissions", prepare_new({**data, "ignore_permissions": True}, caps))
