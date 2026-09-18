import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
import frappe
from privacy_shield import import_access as access
from privacy_shield.policy import Capabilities


class ImportAccessTests(unittest.TestCase):
    def setUp(self):
        for p in [patch.object(frappe.local, "flags", frappe._dict(in_test=True), create=True),
                  patch.object(frappe, "conf", {"privacy_shield_desk_enabled": True}),
                  patch.object(access, "current_capabilities", return_value=Capabilities()),
                  patch.object(frappe, "db", MagicMock())]:
            p.start(); self.addCleanup(p.stop)
        frappe.db.escape.side_effect = lambda value: "'" + value.replace("'", "''") + "'"

    def test_import_denial_is_not_a_permission_grant(self):
        self.assertIs(access.has_permission(frappe._dict(doctype="Data Import", reference_doctype="Patient")), False)
        self.assertIsNone(access.has_permission(frappe._dict(doctype="Data Import", reference_doctype="ToDo")))

    def test_log_checks_linked_import_and_orphans_fail_closed(self):
        doc = frappe._dict(doctype="Data Import Log", data_import="I1")
        for target in ["Contact", None]:
            frappe.db.get_value.return_value = target
            self.assertIs(access.has_permission(doc), False)
        frappe.db.get_value.return_value = "ToDo"
        self.assertIsNone(access.has_permission(doc))

    def test_attached_file_denies_owner_and_public_metadata(self):
        frappe.db.get_value.return_value = "Patient"
        doc = frappe._dict(doctype="File", attached_to_doctype="Data Import", attached_to_name="I1", is_private=0, owner="agent")
        self.assertIs(access.has_permission(doc), False)

    def test_unrelated_files_do_not_trigger_import_lookup(self):
        self.assertIsNone(access.has_permission(frappe._dict(doctype="File", attached_to_doctype="Chat Contact")))
        frappe.db.get_value.assert_not_called()

    def test_explicit_user_policy_not_session_policy(self):
        access.import_condition(user="another-user")
        access.current_capabilities.assert_called_once_with("another-user")

    def test_full_view_and_gate_off_do_not_grant_or_query(self):
        doc = frappe._dict(doctype="Data Import Log", data_import="I1")
        with patch.object(access, "current_capabilities", return_value=Capabilities(True, False)):
            self.assertIsNone(access.has_permission(doc))
            self.assertEqual(access.log_condition(), "")
        with patch.object(frappe, "conf", {}):
            self.assertIsNone(access.has_permission(doc))
            self.assertEqual(access.file_condition(), "")
        frappe.db.get_value.assert_not_called()

    def test_query_conditions_include_all_scoped_targets(self):
        for fn in [access.import_condition, access.log_condition, access.file_condition]:
            condition = fn()
            self.assertIn("'Contact Phone'", condition)
            self.assertIn("'Patient'", condition)
            self.assertNotIn("'Chat Contact'", condition)

    def test_private_url_checks_all_duplicates_before_delivery(self):
        frappe.db.sql.return_value = [(1,)]
        with patch.object(frappe.local, "request", SimpleNamespace(path="/private/files/test.csv"), create=True):
            with self.assertRaises(frappe.PermissionError): access.guard_private_file()
        sql, params = frappe.db.sql.call_args.args
        self.assertIn("LIMIT 1", sql)
        self.assertEqual(params[0], ("/private/files/test.csv",))

    def test_unrelated_private_file_uses_existing_authorization(self):
        frappe.db.sql.return_value = []
        with patch.object(frappe.local, "request", SimpleNamespace(path="/private/files/test.csv"), create=True):
            access.guard_private_file()

    def test_public_paths_not_claimed_as_protected(self):
        with patch.object(frappe.local, "request", SimpleNamespace(path="/files/test.csv"), create=True):
            access.guard_private_file()
        frappe.db.sql.assert_not_called()
