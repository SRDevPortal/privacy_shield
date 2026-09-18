import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
import frappe
from botocore.exceptions import ClientError
from sriaas_clinic.api.s3 import access, presign

class SigningTests(unittest.TestCase):
    def setUp(self):
        for p in [patch.object(frappe.local,"flags",frappe._dict(in_test=True),create=True),
                  patch.object(frappe,"conf",{"aws_s3_region":"test-region"}),
                  patch.object(frappe,"session",SimpleNamespace(user="agent")),
                  patch.object(frappe,"get_all",return_value=[])]:
            p.start();self.addCleanup(p.stop)

    def test_foreign_hosts_signed_urls_and_traversal_rejected(self):
        for url in ["https://evil.invalid/key","https://bucket.s3.amazonaws.com/key?signature=x","s3://../key","s3://"]:
            with self.subTest(url=url),self.assertRaises(frappe.PermissionError):
                access.source_key(url,"bucket","test-region")

    def test_supported_sources_resolve_same_key(self):
        for url in ["s3://folder/a%20b.pdf","https://bucket.s3.amazonaws.com/folder/a%20b.pdf"]:
            self.assertEqual(access.source_key(url,"bucket","test-region"),"folder/a b.pdf")

    def test_unreferenced_key_denied(self):
        with self.assertRaises(frappe.PermissionError):
            access.authorize_source("s3://key","key","bucket","test-region")

    def test_readable_file_allowed_unreadable_denied(self):
        frappe.get_all.return_value=[frappe._dict(name="F1",attached_to_doctype=None)]
        doc=MagicMock()
        with patch.object(frappe,"get_doc",return_value=doc):
            doc.has_permission.return_value=True
            access.authorize_source("s3://key","key","bucket","test-region")
            doc.has_permission.return_value=False
            with self.assertRaises(frappe.PermissionError):
                access.authorize_source("s3://key","key","bucket","test-region")

    def test_guest_cannot_sign(self):
        with patch.object(frappe,"session",SimpleNamespace(user="Guest")),self.assertRaises(frappe.PermissionError):
            access.authorize_source("s3://key","key","bucket","test-region")
        frappe.get_all.assert_not_called()

    def test_parent_permission_checked_before_attachment_match(self):
        doc=MagicMock();doc.check_permission.side_effect=frappe.PermissionError
        with patch.object(frappe,"get_meta",return_value=SimpleNamespace(istable=False)),              patch.object(frappe,"get_doc",return_value=doc),              patch.object(access,"references_attachment") as refs:
            with self.assertRaises(frappe.PermissionError):
                access.authorize_source("s3://key","key","bucket","test-region","Patient Encounter","PE1")
            refs.assert_not_called()

    def test_child_attach_matches_but_arbitrary_text_does_not(self):
        child=frappe._dict(doctype="Child",proof="s3://key")
        doc=frappe._dict(doctype="Parent",rows=[child],notes="s3://other")
        parent=SimpleNamespace(fields=[frappe._dict(fieldname="rows",fieldtype="Table"),frappe._dict(fieldname="notes",fieldtype="Text")])
        cm=SimpleNamespace(fields=[frappe._dict(fieldname="proof",fieldtype="Attach")])
        with patch.object(frappe,"get_meta",side_effect=lambda dt:parent if dt=="Parent" else cm):
            self.assertTrue(access.references_attachment(doc,["s3://key"]))
            self.assertFalse(access.references_attachment(doc,["s3://other"]))

    def test_privacy_denial_precedes_storage_client(self):
        with patch.object(presign,"get_bucket",return_value="bucket"),              patch.object(presign,"authorize_source",side_effect=frappe.PermissionError),              patch.object(presign,"get_s3_client") as client:
            with self.assertRaises(frappe.PermissionError):presign.get_presigned_url("s3://key")
            client.assert_not_called()

    def test_invalid_expiry_never_contacts_storage(self):
        with patch.object(presign,"get_bucket",return_value="bucket"),              patch.object(presign,"authorize_source"),patch.object(presign,"get_s3_client") as client:
            for expires in [0,-1,901,"bad"]:
                with self.subTest(expires=expires),self.assertRaises(frappe.ValidationError):
                    presign.get_presigned_url("s3://key",expires)
            client.assert_not_called()

    def test_allowed_signing_and_missing_object_no_raw_fallback(self):
        client=MagicMock();client.generate_presigned_url.return_value="https://example.invalid/synthetic"
        with patch.object(presign,"get_bucket",return_value="bucket"),patch.object(presign,"authorize_source"),              patch.object(presign,"get_s3_client",return_value=client):
            self.assertEqual(presign.get_presigned_url("s3://key",60),"https://example.invalid/synthetic")
            self.assertEqual(client.generate_presigned_url.call_args.kwargs["ExpiresIn"],60)
            client.head_object.side_effect=ClientError({"Error":{"Code":"404"}},"HeadObject")
            with self.assertRaises(frappe.ValidationError):presign.get_presigned_url("s3://key")

    def test_restricted_scoped_parent_denied_before_read(self):
        with patch.object(frappe,"conf",{"privacy_shield_desk_enabled":True}),              patch("privacy_shield.import_access.restricted",return_value=True),              patch("privacy_shield.import_access.check_import_urls"),              patch("privacy_shield.report_outputs.check_attachment_urls"),              patch.object(frappe,"get_doc") as get_doc:
            with self.assertRaises(frappe.PermissionError):
                access.authorize_source("s3://key","key","bucket","test-region","Patient Encounter","PE1")
            get_doc.assert_not_called()
