import unittest
from unittest.mock import patch
import frappe
from sriaas_clinic.api.s3 import delete

class RetiredS3DeleteTests(unittest.TestCase):
    def test_rpc_is_not_whitelisted(self):
        self.assertNotIn(delete.delete_s3_by_url, frappe.whitelisted)
        with patch.object(frappe.local,"flags",frappe._dict(in_test=True),create=True),              patch.object(frappe,"_",side_effect=lambda value, **kwargs:value), patch.object(frappe,"session",{"user":"test"}), patch.object(frappe,"throw",side_effect=frappe.PermissionError),              patch.object(delete,"delete_file_from_s3") as operation:
            with self.assertRaises(frappe.PermissionError):
                frappe.is_whitelisted(delete.delete_s3_by_url)
            operation.assert_not_called()

    def test_stale_direct_calls_never_delete_any_source(self):
        with patch.object(delete,"delete_file_from_s3") as operation,              patch.object(delete,"get_s3_client") as client:
            for url in ["s3://synthetic/shared.pdf","https://example.invalid/key","",None]:
                with self.subTest(url=url),self.assertRaises(frappe.PermissionError):
                    delete.delete_s3_by_url(url)
            operation.assert_not_called()
            client.assert_not_called()

    def test_internal_cleanup_helper_is_not_public(self):
        self.assertNotIn(delete.delete_file_from_s3, frappe.whitelisted)
