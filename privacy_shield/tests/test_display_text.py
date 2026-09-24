import unittest
from copy import deepcopy
from privacy_shield.display_text import mask_display, preserve_display
from privacy_shield.desk import project_document,prepare_payload
from privacy_shield.policy import Capabilities
from privacy_shield.listing import project_rows
from privacy_shield.duplicate_views import project_duplicate_rows
from sriaas_clinic.api.crm_lead.privacy_views import project_layout

class DisplayTextTests(unittest.TestCase):
    def fixture(self):
        return dict(doctype='CRM Lead',name='CRM-LEAD-2026-00001',first_name='2025550181',lead_name='Call +1 (202) 555-0181',mobile_no='2025550181',phone='2025550182')

    def test_multiple_formats_and_embedded_digits(self):
        for text in ['Call 2025550181','+1 (202) 555-0181','Name2025550181','202-555-0181']:
            with self.subTest(text=text):
                self.assertNotIn('2025550181',mask_display(text));self.assertIn('*',mask_display(text))
        self.assertEqual(mask_display('Name 42'),'Name 42')
        self.assertEqual(mask_display('******0181'),'******0181')

    def test_document_masks_names_without_changing_source(self):
        source=self.fixture();before=deepcopy(source);result=project_document(source,Capabilities())
        self.assertEqual(result['first_name'],'******0181');self.assertNotIn('2025550181',str(result));self.assertEqual(source,before)
        self.assertEqual(result['name'],source['name'])
        self.assertIn('first_name',result['__privacy_shield']['masked_display_fields'])

    def test_full_view_unchanged(self):
        source=self.fixture();result=project_document(source,Capabilities(True,False))
        self.assertEqual(result['first_name'],source['first_name']);self.assertEqual(result['lead_name'],source['lead_name'])

    def test_list_without_phone_column(self):
        rows=project_rows('CRM Lead',[{'first_name':'2025550181'}],['first_name'],['first_name'])
        self.assertEqual(rows,[{'first_name':'******0181'}])
        self.assertEqual(project_rows('CRM Lead',[{'first_name':'2025550181'}],['first_name'],['first_name'],as_dict=False),[['******0181']])

    def test_crm_list_and_kanban(self):
        for result in [{'view_type':'list','data':[self.fixture()]},{'view_type':'kanban','data':[{'data':[self.fixture()]}]}]:
            self.assertNotIn('2025550181',str(project_layout(result,False)))

    def test_duplicates(self):
        self.assertNotIn('2025550181',str(project_duplicate_rows([self.fixture()])))

    def test_ordinary_save_restores_original_names(self):
        stored=self.fixture();data=project_document(stored,Capabilities());data['city']='Synthetic city'
        result=prepare_payload(data,stored,Capabilities())
        self.assertEqual(result['first_name'],stored['first_name']);self.assertEqual(result['lead_name'],stored['lead_name']);self.assertEqual(result['city'],'Synthetic city')

    def test_redacted_name_cannot_be_changed_or_cleared(self):
        for value in ['', 'Different name','******9999']:
            with self.assertRaises(PermissionError):preserve_display({'first_name':value},self.fixture())

    def test_omitted_name_preserved(self):
        self.assertEqual(preserve_display({},self.fixture())['first_name'],'2025550181')

    def test_new_copy_cannot_persist_masks(self):
        with self.assertRaises(ValueError):preserve_display({'first_name':'******0181'},{})

    def test_all_core_document_display_names(self):
        for dt,field in [('Patient','patient_name'),('Contact','first_name'),('Customer','customer_name'),('Address','address_title'),('Patient Encounter','patient_name'),('Sales Invoice','customer_name'),('Clinic Appointment','patient_name')]:
            with self.subTest(doctype=dt):
                self.assertEqual(project_document({'doctype':dt,field:'2025550181'},Capabilities())[field],'******0181')

    def test_lead_notes_preserve_markup_and_storage(self):
        stored=self.fixture();stored['sr_lead_notes']='<p>Call +1 (202) 555-0181 for followup</p>'
        projected=project_document(stored,Capabilities())
        self.assertIn('<p>Call ',projected['sr_lead_notes']);self.assertNotIn('555-0181',projected['sr_lead_notes'])
        self.assertEqual(prepare_payload(projected,stored,Capabilities())['sr_lead_notes'],stored['sr_lead_notes'])

    def test_grouping_by_redacted_titles_denied(self):
        import frappe
        from sriaas_clinic.api.crm_lead.privacy_views import prepare
        defaults={'rows':['name','lead_name'],'columns':[],'kanban_fields':[]}
        with self.assertRaises(frappe.PermissionError):
            prepare({'column_field':'lead_name'},False,defaults)
