import unittest
from types import SimpleNamespace
from unittest.mock import patch
import frappe
from privacy_shield import api
from privacy_shield.policy import Capabilities
from privacy_shield.child_rows import preserve_contact_rows

class Doc:
    doctype = "Contact"
    modified = "2026-09-16 10:00:00"
    permitted_fieldnames = {"mobile_no", "phone"}
    def __init__(self):
        self.values = {"mobile_no": "9876543210", "phone": "1234567890"}
        self.meta = SimpleNamespace(get_field=lambda name: SimpleNamespace(read_only=0, fetch_from=None))
        self.saved = False
        self.permissions = []
    def get(self, field): return self.values.get(field)
    def set(self, field, value): self.values[field] = value
    def check_permission(self, kind): self.permissions.append(kind)
    def has_permlevel_access_to(self, *args, **kwargs): return True
    def save(self): self.saved = True

class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.doc = Doc()
        context = patch.object(frappe.local, "flags", frappe._dict(in_test=True), create=True)
        context.start()
        self.addCleanup(context.stop)
        self.patches = [patch.object(api.frappe, "session", SimpleNamespace(user="agent")),
                        patch.object(api.frappe, "get_doc", return_value=self.doc),
                        patch.object(api, "current_capabilities", return_value=Capabilities())]
        self.mocks = [p.start() for p in self.patches]
        for p in self.patches: self.addCleanup(p.stop)

    def test_restricted_response_has_no_originals(self):
        response = api.get_numbers("Contact", "C-1")
        self.assertNotIn("9876543210", str(response))
        self.assertNotIn("1234567890", str(response))
        self.assertEqual(self.doc.values["mobile_no"], "9876543210")
        self.assertEqual(self.doc.permissions, ["read"])

    def test_full_view_still_checks_record_and_field_access(self):
        self.mocks[2].return_value = Capabilities(True, False)
        self.doc.permitted_fieldnames = {"phone"}
        response = api.get_numbers("Contact", "C-1")
        self.assertEqual(len(response["numbers"]), 1)
        self.assertEqual(response["numbers"][0]["value"], "1234567890")
        self.doc.check_permission = lambda kind: (_ for _ in ()).throw(frappe.PermissionError())
        with self.assertRaises(frappe.PermissionError): api.get_numbers("Contact", "C-1")

    def test_no_phone_identity_or_arbitrary_doctype_endpoint(self):
        for doctype in ["Chat Contact", "Contact Phone", "Vobiz Blocked Number", "User"]:
            with self.assertRaises(frappe.ValidationError): api.get_numbers(doctype, "x")
        self.mocks[1].assert_not_called()

    def test_edit_only_user_does_not_receive_original(self):
        self.mocks[2].return_value = Capabilities(False, True)
        response = api.update_number("Contact", "C-1", "phone", "5555551234", self.doc.modified)
        self.assertTrue(self.doc.saved)
        self.assertNotIn("5555551234", str(response))
        self.assertEqual(self.doc.permissions, ["read", "write"])
        self.assertEqual(self.doc.values["mobile_no"], "9876543210")

    def test_denied_and_stale_writes_do_not_save(self):
        with self.assertRaises(frappe.PermissionError):
            api.update_number("Contact", "C-1", "phone", "5555551234", self.doc.modified)
        self.mocks[2].return_value = Capabilities(False, True)
        with self.assertRaises(frappe.TimestampMismatchError):
            api.update_number("Contact", "C-1", "phone", "5555551234", "2026-09-15")
        with self.assertRaises(frappe.ValidationError):
            api.update_number("Contact", "C-1", "phone", "******1234", self.doc.modified)
        self.assertFalse(self.doc.saved)

    def test_fetched_field_not_editable(self):
        self.mocks[2].return_value = Capabilities(True, True)
        self.doc.meta.get_field = lambda name: SimpleNamespace(read_only=0, fetch_from="contact.mobile_no")
        with self.assertRaises(frappe.PermissionError):
            api.update_number("Contact", "C-1", "phone", "5555551234", self.doc.modified)
        self.assertFalse(self.doc.saved)

    def test_guest_denied(self):
        api.frappe.session.user = "Guest"
        with self.assertRaises(frappe.PermissionError): api.get_numbers("Contact", "C-1")
        self.mocks[1].assert_not_called()

class ChildTests(unittest.TestCase):
    def setUp(self):
        self.stored = [{"name": "row1", "phone": "9876543210", "parent": "C-1",
                        "parenttype": "Contact", "parentfield": "phone_nos",
                        "doctype": "Contact Phone", "is_primary_phone": 1, "is_primary_mobile_no": 0}]
    def test_omitted_values_and_flags_preserved(self):
        submitted = [{"name": "row1"}]
        self.assertEqual(preserve_contact_rows(submitted, self.stored), self.stored)
        self.assertEqual(submitted, [{"name": "row1"}])
    def test_child_tampering(self):
        for rows in [[], [{"name": "foreign"}], [{"name": "row1"}, {"name": "row1"}],
                     [{"name": "row1", "phone": ""}], [{"name": "row1", "parent": "C-2"}],
                     [{"name": "row1", "is_primary_phone": 0}]]:
            with self.subTest(rows=rows), self.assertRaises(PermissionError):
                preserve_contact_rows(rows, self.stored)
    def test_editor_still_cannot_write_mask(self):
        with self.assertRaises(ValueError):
            preserve_contact_rows([{"name": "row1", "phone": "******3210"}], self.stored, True)
