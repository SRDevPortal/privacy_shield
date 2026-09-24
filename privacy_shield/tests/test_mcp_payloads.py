import json
import unittest
from privacy_shield.mcp_payloads import has_protected_reference

class MCPPayloadTests(unittest.TestCase):
    def test_nested_core_reference(self):
        for field in ("request_summary_json", "response_summary_json", "diff_json"):
            self.assertTrue(has_protected_reference({field:json.dumps({"rows":[{"doctype":"Patient","mobile":"2025550101"}]})}))

    def test_unrelated_deferred_and_nonreference_text(self):
        for value in ({"doctype":"Chat Contact"},{"doctype":"ToDo"},{"description":"Patient"},{"mobile":"2025550101"}):
            self.assertFalse(has_protected_reference({"response_summary_json":json.dumps(value)}))

    def test_unknown_payloads_withheld(self):
        for value in ('{', ' ' * 65537):
            self.assertTrue(has_protected_reference({"diff_json":value}))
        self.assertFalse(has_protected_reference({"diff_json":None}))
