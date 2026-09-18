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
        self.assertFalse(evaluate(["System Manager"], [], "manager").view_full)
        self.assertTrue(evaluate(["Agent", "Viewer"], rules, "user").view_full)
        self.assertFalse(evaluate(["Viewer"], rules, "user").edit_original)
        self.assertTrue(evaluate(["Editor"], rules, "user").edit_original)
        self.assertFalse(evaluate(["Viewer"], rules, "Guest").view_full)
        self.assertTrue(evaluate([], [], "Administrator").view_full)
        self.assertFalse(evaluate(["Viewer"], [], "user").view_full)

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

    def test_virtual_expression_in_frappe(self):
        from frappe.utils.safe_exec import safe_eval, get_python_builtins
        globals_for_virtual = {**get_python_builtins(), "_getiter_": iter}
        for value in ["9876543210 1234567890", None, "", "12", "1234", "9876543210", "+91 (98765) 43210", "123/456", "---"]:
            with self.subTest(value=value):
                self.assertEqual(safe_eval(virtual_expression("phone"), eval_globals=globals_for_virtual.copy(), eval_locals={"doc": {"phone": value}}), mask_number(value))
