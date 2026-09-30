import unittest
from privacy_shield.child_rows import preserve_contact_rows

class InlineContactTests(unittest.TestCase):
    def setUp(self):
        self.old=[dict(name="old",phone="9876501234",parent="CONTACT",parenttype="Contact",parentfield="phone_nos",doctype="Contact Phone",is_primary_mobile_no=1,is_primary_phone=0)]
        self.visible=[dict(self.old[0])];self.visible[0].pop("phone")
        self.new=dict(name="new-local",__islocal=1,doctype="Contact Phone",mask_phone="9876501235",is_primary_mobile_no=0,is_primary_phone=0)

    def test_add_preserves_original_and_strips_client_identity(self):
        rows=preserve_contact_rows(self.visible+[self.new],self.old,can_add=True)
        self.assertEqual(rows[0]['phone'],'9876501234')
        self.assertEqual(rows[1]['phone'],'9876501235')
        self.assertNotIn('name',rows[1])

    def test_add_without_grant_rejected(self):
        with self.assertRaises(PermissionError):preserve_contact_rows(self.visible+[self.new],self.old)

    def test_primary_requires_separate_grant(self):
        self.new['is_primary_mobile_no']=1
        with self.assertRaises(PermissionError):preserve_contact_rows(self.visible+[self.new],self.old,can_add=True)

    def test_old_number_replacement_rejected_even_with_both_grants(self):
        self.visible[0]['phone']='9876501236'
        with self.assertRaises(PermissionError):preserve_contact_rows(self.visible,self.old,can_add=True,can_primary=True)

    def test_old_row_deletion_rejected(self):
        with self.assertRaises(PermissionError):preserve_contact_rows([self.new],self.old,can_add=True,can_primary=True)

    def test_foreign_existing_row_rejected(self):
        self.new.pop('__islocal')
        with self.assertRaises(PermissionError):preserve_contact_rows(self.visible+[self.new],self.old,can_add=True)

    def test_primary_selection_preserves_old_number(self):
        self.visible[0]['is_primary_phone']=1
        rows=preserve_contact_rows(self.visible,self.old,can_primary=True)
        self.assertEqual(rows[0]['phone'],'9876501234')
        self.assertEqual(rows[0]['is_primary_phone'],1)
