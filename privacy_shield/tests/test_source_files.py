import unittest
from unittest.mock import patch, MagicMock
import frappe
from privacy_shield import import_access as access, private_files, imports

class SourceFilesTests(unittest.TestCase):
    def setUp(self):
        for p in [patch.object(frappe,"conf",{"privacy_shield_desk_enabled":True}),
                  patch.object(frappe,"db",MagicMock())]:
            p.start();self.addCleanup(p.stop)
        frappe.db.sql.return_value=[]

    def test_reverse_source_query_and_aliases_share_one_lookup(self):
        access.protected_urls(["/private/files/x.csv"])
        sql,args=frappe.db.sql.call_args.args
        self.assertIn("src.import_file IN",sql)
        self.assertIn("f.attached_to_doctype='Data Import'",sql)
        self.assertEqual(args[0],args[2])

    def test_owner_access_cannot_override_reverse_source_denial(self):
        frappe.db.sql.return_value=[(1,)]
        doc=frappe._dict(doctype="File",file_url="/private/files/x.csv",owner="agent")
        with patch.object(access,"restricted",return_value=True):
            self.assertIs(access.has_permission(doc,user="agent"),False)

    def test_empty_urls_skip_query_and_unrelated_urls_do_not_grant_access(self):
        self.assertFalse(access.protected_urls([None,""]))
        frappe.db.sql.assert_not_called()
        with patch.object(access,"restricted",return_value=True):
            self.assertIsNone(access.has_permission(frappe._dict(doctype="File",file_url="/private/files/ok.txt")))

    def test_public_insert_rejected_before_core_file_write(self):
        doc=MagicMock()
        values={"attached_to_doctype":"Data Import","attached_to_name":"I1","is_private":0}
        doc.get.side_effect=lambda k:values.get(k)
        doc.is_new.return_value=True
        frappe.db.get_value.return_value="Address"
        with patch.object(private_files.File,"before_insert") as original:
            with self.assertRaises(frappe.ValidationError):private_files.PrivacyFile.before_insert(doc)
            original.assert_not_called()

    def test_detach_and_make_public_checks_original_url_before_move(self):
        doc=MagicMock(name="file")
        doc.get.side_effect=lambda k:None
        doc.is_new.return_value=False
        frappe.db.get_value.return_value="/private/files/old.csv"
        frappe.db.sql.return_value=[(1,)]
        with patch.object(private_files.File,"validate") as original:
            with self.assertRaises(frappe.ValidationError):private_files.PrivacyFile.validate(doc)
            original.assert_not_called()
        self.assertIn("/private/files/old.csv",frappe.db.sql.call_args.args[1][0])

    def test_private_and_gate_off_file_delegate(self):
        doc=object.__new__(private_files.PrivacyFile);doc.get=lambda k:1 if k=="is_private" else None
        with patch.object(private_files.File,"before_insert",return_value="ok"):
            self.assertEqual(private_files.PrivacyFile.before_insert(doc),"ok")
        frappe.db.sql.assert_not_called()
        with patch.object(frappe,"conf",{}):
            private_files.validate_private_source(doc)

    def test_new_source_requires_private_local_url(self):
        for url in ["/files/x.csv","https://example.invalid/x.csv"]:
            with self.subTest(url=url),self.assertRaises(frappe.ValidationError):
                imports.validate_source(frappe._dict(reference_doctype="Address",import_file=url))
        imports.validate_source(frappe._dict(reference_doctype="Address",import_file="/private/files/x.csv"))
        imports.validate_source(frappe._dict(reference_doctype="ToDo",import_file="/files/x.csv"))


    def test_core_file_or_branches_obey_appended_denial(self):
        import sqlite3
        from frappe.core.doctype.file import file as core_file
        with patch.object(frappe,"get_roles",return_value=[core_file.SYSTEM_USER_ROLE]),              patch.object(core_file,"get_doctypes_with_read",return_value=["Address"]):
            frappe.db.escape.side_effect=lambda value:"'" + value + "'"
            condition=core_file.get_permission_query_conditions("agent")
        db=sqlite3.connect(":memory:")
        try:
            db.execute("CREATE TABLE tabFile (name TEXT, is_private INT, attached_to_doctype TEXT, owner TEXT, privacy_allowed INT)")
            db.executemany("INSERT INTO tabFile VALUES (?,?,?,?,?)",[
                ("public-denied",0,None,"other",0),("owner-denied",1,None,"agent",0),
                ("linked-denied",1,"Address","other",0),("public-ok",0,None,"other",1),
                ("owner-ok",1,None,"agent",1),("linked-ok",1,"Address","other",1),
                ("ordinary-denied",1,None,"other",1)])
            names={row[0] for row in db.execute("SELECT name FROM tabFile WHERE "+condition+" AND privacy_allowed=1")}
            self.assertEqual(names,{"public-ok","owner-ok","linked-ok"})
        finally:db.close()
