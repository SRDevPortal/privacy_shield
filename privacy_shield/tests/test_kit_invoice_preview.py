import unittest
from unittest.mock import patch, MagicMock
from copy import deepcopy
import frappe
from privacy_shield.kit_invoice_preview import project, render, load_context, UnsupportedInvoice


def fixture():
    return dict(name='PILOT-INV-A',company='Synthetic Clinic',customer='Synthetic Customer',
        posting_date='2026-09-23',due_date='2026-09-30',currency='INR',contact_mobile='2025550181',
        sr_kit_name='Care Kit',sr_kit_total_price=100,sr_non_kit_total_price=20,
        net_total=120,total_taxes_and_charges=21.6,grand_total=141.6,rounded_total=142,
        rounding_adjustment=.4,discount_amount=0,total_advance=40,write_off_amount=0,
        outstanding_amount=102,
        items=[dict(item_code='KIT-A',item_name='Care component',gst_hsn_code='3004',qty=2,rate=50,net_amount=100,amount=100),dict(item_code='SERVICE-A',item_name='Consultation',gst_hsn_code='9993',qty=1,rate=20,net_amount=20,amount=20)],
        taxes=[dict(description='CGST',rate=9,tax_amount=10.8),dict(description='SGST',rate=9,tax_amount=10.8)])

GROUPS={'KIT-A':'MEDICINES','SERVICE-A':'NON KIT ITEMS'}

class KitInvoicePreviewTests(unittest.TestCase):
    def test_masks_without_mutating_source(self):
        doc=fixture();before=deepcopy(doc);ctx=project(doc,{'mobile_no':'2025550182'},GROUPS)
        self.assertEqual(ctx['mobile'],'******0181');self.assertEqual(doc,before)
        self.assertNotIn('2025550181',str(ctx));self.assertNotIn('2025550182',str(ctx))

    def test_customer_fallback(self):
        doc=fixture();doc['contact_mobile']=''
        self.assertEqual(project(doc,{'mobile_no':'2025550182'},GROUPS)['mobile'],'******0182')

    def test_preserves_stored_financial_values(self):
        ctx=project(fixture(),item_groups=GROUPS)
        self.assertEqual(ctx['totals']['grand_total'],'141.6')
        self.assertEqual(ctx['totals']['outstanding_amount'],'102')
        self.assertEqual([r['amount'] for r in ctx['taxes']],['10.8','10.8'])
        self.assertEqual([r['group'] for r in ctx['items']],['Kit','Non Kit'])

    def test_unreviewed_content_is_rejected(self):
        for field in ['customer_address','shipping_address_name','address_display','contact_email']:
            doc=fixture();doc[field]='Needs review'
            with self.subTest(field=field),self.assertRaises(UnsupportedInvoice):project(doc,item_groups=GROUPS)

    def test_phone_in_display_text_rejected(self):
        doc=fixture();doc['customer_name']='Call +1 (202) 555-0181'
        with self.assertRaises(UnsupportedInvoice):project(doc,item_groups=GROUPS)

    def test_stored_html_not_used(self):
        doc=fixture();doc['gst_breakup_table']='<img src="https://example.invalid/2025550181">'
        html=render(project(doc,item_groups=GROUPS))
        self.assertNotIn('example.invalid',html);self.assertNotIn('2025550181',html)
        self.assertIn('CGST',html);self.assertIn('141.6',html)

    def test_unknown_group_rejected(self):
        with self.assertRaises(UnsupportedInvoice):project(fixture(),item_groups={})

    def test_nonfinite_amount_rejected(self):
        doc=fixture();doc['grand_total']='NaN'
        with self.assertRaises(UnsupportedInvoice):project(doc,item_groups=GROUPS)

    def test_read_denied_before_linked_lookup(self):
        with patch.object(frappe.local,'conf',frappe._dict(privacy_shield_desk_enabled=True),create=True),patch.object(frappe,'get_doc') as get:
            get.return_value.check_permission.side_effect=frappe.PermissionError
            with self.assertRaises(frappe.PermissionError):load_context('PILOT-INV-A')
            self.assertEqual(get.call_count,1)

    def test_gate_off_denied(self):
        with patch.object(frappe.local,'conf',frappe._dict(privacy_shield_desk_enabled=False),create=True):
            with self.assertRaises(frappe.PermissionError):load_context('PILOT-INV-A')

    def test_resolved_addresses_and_compliance_fields(self):
        doc=fixture();doc['customer_address']='Address-A';doc['address_display']='<p>2025550189</p>'
        doc['items'][0].update(sr_compliance_batch_no='BATCH-A',sr_compliance_mfg_date='2026-01-01',sr_compliance_expiry_date='2028-01-01')
        ctx=project(doc,item_groups=GROUPS,addresses={'customer_address':{'address_line1':'42 Test Street','pincode':'110001','phone':'2025550189'}})
        html=render(ctx)
        self.assertIn('******0189',html);self.assertNotIn('2025550189',html)
        self.assertIn('42 Test Street',html);self.assertIn('BATCH-A',html);self.assertIn('2028-01-01',html)

    def test_number_in_address_line_is_rejected(self):
        with self.assertRaises(UnsupportedInvoice):
            project(fixture(),item_groups=GROUPS,addresses={'customer_address':{'address_line1':'Call 2025550189'}})

    def test_typed_identifiers_preserved(self):
        doc=fixture();doc['name']='ACC-SINV-2026-00001';doc['items'][0]['gst_hsn_code']='30049099'
        ctx=project(doc,item_groups=GROUPS)
        self.assertEqual(ctx['name'],doc['name']);self.assertEqual(ctx['items'][0]['hsn'],'30049099')

    def test_plain_notes_and_terms_preserved_without_source_mutation(self):
        doc=fixture();doc.update(remarks='Handle with care.\nKeep dry.', terms='Payment within 30 days & receipt required.')
        before=deepcopy(doc);html=render(project(doc,item_groups=GROUPS))
        self.assertIn('Handle with care.\nKeep dry.',html)
        self.assertIn('Payment within 30 days &amp; receipt required.',html)
        self.assertEqual(doc,before)

    def test_notes_and_terms_reject_phone_and_rich_content(self):
        for field in ['remarks','terms']:
            for value in ['Call +1 (202) 555-0181', 'Call 202\n555\n0181', '<p>Payment due</p>', '<img src="https://example.invalid/pixel">', '&lt;script&gt;']:
                doc=fixture();doc[field]=value
                with self.subTest(field=field,value=value):
                    if value.startswith('&lt;'):
                        self.assertIn('&amp;lt;script&amp;gt;',render(project(doc,item_groups=GROUPS)))
                    else:
                        with self.assertRaises(UnsupportedInvoice):project(doc,item_groups=GROUPS)

    def test_shipping_and_company_sources_remain_distinct(self):
        doc=fixture();doc.update(company_address='Company-A',shipping_address_name='Shipping-A')
        ctx=project(doc,item_groups=GROUPS,addresses={
            'company_address':{'address_line1':'Company Street','phone':'2025550187'},
            'shipping_address_name':{'address_line1':'Shipping Street','phone':'2025550188'}})
        self.assertEqual(ctx['addresses']['company_address']['phone'],'******0187')
        self.assertEqual(ctx['addresses']['shipping_address_name']['phone'],'******0188')
        html=render(ctx)
        self.assertNotIn('2025550187',html);self.assertNotIn('2025550188',html)
