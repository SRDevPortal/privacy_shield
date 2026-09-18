import unittest
from types import SimpleNamespace
from unittest.mock import patch
import frappe
from privacy_shield import install

class InstallTests(unittest.TestCase):
    def test_foreign_field_aborts_before_schema_mutation(self):
        meta = SimpleNamespace(has_field=lambda name: True,
                               get_field=lambda name: SimpleNamespace(is_virtual=1, permlevel=0))
        db = SimpleNamespace(exists=lambda *args: True, get_value=lambda *args: "Another App")
        with patch.object(frappe, "db", db), patch.object(frappe, "get_meta", return_value=meta), \
             patch.object(frappe, "throw", side_effect=frappe.ValidationError), \
             patch("frappe.custom.doctype.custom_field.custom_field.create_custom_fields") as create:
            with self.assertRaises(frappe.ValidationError): install.sync_fields()
            create.assert_not_called()

    def test_hidden_virtual_fields_inherit_source_level(self):
        def field(name):
            return None if name.startswith("mask_") else SimpleNamespace(permlevel=2)
        meta = SimpleNamespace(has_field=lambda name: True, get_field=field)
        db = SimpleNamespace(exists=lambda *args: True)
        with patch.object(frappe, "db", db), patch.object(frappe, "get_meta", return_value=meta):
            fields = install.build_fields()
        self.assertEqual(sum(map(len, fields.values())), 13)
        for rows in fields.values():
            for row in rows:
                self.assertEqual((row["hidden"], row["read_only"], row["is_virtual"], row["permlevel"]), (1,1,1,2))
                self.assertFalse(row.get("search_index"))

    def test_missing_source_aborts(self):
        meta = SimpleNamespace(has_field=lambda name: False)
        with patch.object(frappe, "db", SimpleNamespace(exists=lambda *args: True)), \
             patch.object(frappe, "get_meta", return_value=meta), \
             patch.object(frappe, "throw", side_effect=frappe.ValidationError):
            with self.assertRaises(frappe.ValidationError): install.build_fields()
