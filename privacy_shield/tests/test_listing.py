import unittest
from unittest.mock import patch
import frappe
from privacy_shield import listing
from privacy_shield.policy import Capabilities

class ListingTests(unittest.TestCase):
    def setUp(self):
        for p in [patch.object(frappe.local,"flags",frappe._dict(in_test=True),create=True),
                  patch.object(frappe,"conf",{"privacy_shield_desk_enabled":True}),
                  patch("privacy_shield.listing.current_capabilities",return_value=Capabilities())]:
            p.start();self.addCleanup(p.stop)

    def test_virtual_columns_translated_before_query(self):
        with patch("frappe.client.get_list",return_value=[{"name":"L1","mobile_no":"9876543210"}]) as query:
            result=listing.get_list("CRM Lead",["name","mask_mobile"])
            self.assertEqual(query.call_args.args[1],["name","mobile_no"])
            self.assertEqual(result,[{"name":"L1","mask_mobile":"******3210"}])

    def test_alias_expression_and_wildcard_rejected(self):
        for field in ["mobile_no as x","*","right(mobile_no,10)","Contact.phone","`mobile_no`"]:
            with self.subTest(field=field),self.assertRaises(frappe.ValidationError):
                listing.columns("CRM Lead",[field])

    def test_positional_results_preserve_shape(self):
        result=listing.project_rows("CRM Lead",[{"mobile_no":"9876543210"}],
             ["name","mobile_no"],["name","mobile_no"],as_dict=False)
        self.assertEqual(result,[[None,"******3210"]])

    def test_normalized_alias_not_disclosed(self):
        result=listing.project_rows("CRM Lead",[{"sr_mobile_norm":"9876543210"}],
             ["sr_mobile_norm"],["sr_mobile_norm"])
        self.assertEqual(result,[{}])

    def test_protected_filter_and_unbounded_query_rejected(self):
        with self.assertRaises(frappe.PermissionError):
            listing.validate_query("CRM Lead",{"mobile_no":["like","98%"]},None,None,None,False)
        with self.assertRaises(frappe.ValidationError):
            listing.get_list("CRM Lead",["name"],limit_page_length=0)

    def test_single_value_shape_and_mask(self):
        with patch("frappe.client.get_list",return_value=[{"mobile_no":"9876543210"}]):
            self.assertEqual(listing.get_value("CRM Lead","mobile_no","L1",as_dict=False),"******3210")
            self.assertEqual(listing.get_value("CRM Lead","mobile_no","L1"),{"mask_mobile":"******3210"})

    def test_full_view_keeps_original_but_virtual_stays_masked(self):
        result=listing.project_rows("CRM Lead",[{"mobile_no":"9876543210"}],
             ["mobile_no","mask_mobile"],["mobile_no","mobile_no"],full=True)
        self.assertEqual(result,[{"mobile_no":"9876543210","mask_mobile":"******3210"}])

    def test_search_drops_supplementary_numbers_and_forces_permissions(self):
        with patch.object(frappe,"get_hooks",return_value={}), \
             patch("frappe.desk.search.search_widget",return_value=[["L1","9876543210"]]) as query:
            self.assertEqual(listing.search_link("CRM Lead","L",ignore_user_permissions=True),
                             [{"value":"L1","description":""}])
            self.assertFalse(query.call_args.args[-1])

    def test_custom_search_rejected(self):
        with self.assertRaises(frappe.PermissionError):
            listing.search_widget("CRM Lead","L",query="custom.query")

    def test_gate_off_passes_through(self):
        with patch.object(frappe,"conf",{}),patch("frappe.client.get_list",return_value=[{"mobile_no":"raw"}]):
            self.assertEqual(listing.get_list("CRM Lead"),[{"mobile_no":"raw"}])

    def test_compressed_desk_rows_and_request_restoration(self):
        params=frappe._dict(doctype="CRM Lead",fields='["name", "mask_mobile"]',page_length=20)
        response={"keys":["name","mobile_no"],"values":[["L1","9876543210"]],"user_info":{}}
        with patch.object(frappe.local,"form_dict",params,create=True), \
             patch.object(frappe,"form_dict",params), \
             patch("frappe.desk.reportview.get",return_value=response):
            result=listing.reportview_get()
            self.assertIs(frappe.local.form_dict,params)
            self.assertEqual(result["keys"],["name","mask_mobile"])
            self.assertEqual(result["values"],[["L1","******3210"]])
            self.assertEqual(response["values"],[["L1","9876543210"]])

    def test_report_request_restored_on_framework_error(self):
        params=frappe._dict(doctype="CRM Lead",fields='["name"]',page_length=20)
        with patch.object(frappe.local,"form_dict",params,create=True), \
             patch.object(frappe,"form_dict",params), \
             patch("frappe.desk.reportview.get",side_effect=frappe.PermissionError):
            with self.assertRaises(frappe.PermissionError): listing.reportview_get()
            self.assertIs(frappe.local.form_dict,params)

    def test_desk_link_title_uses_selected_link_id_without_join(self):
        parent = frappe._dict(get_field=lambda field: frappe._dict(fieldtype="Link", options="Patient"))
        linked = frappe._dict(show_title_field_in_link=1, title_field="patient_name")
        with patch.object(frappe, "get_meta", side_effect=lambda dt: parent if dt == "Patient Encounter" else linked):
            fields = ["`tabPatient Encounter`.`name`", "`tabPatient Encounter`.`patient`", "patient.patient_name as patient_patient_name"]
            self.assertEqual(listing.desk_columns("Patient Encounter", fields), (["name", "patient"], ["name", "patient"]))
            for bad in ["patient.mobile as patient_mobile", "patient.patient_name as leaked", "patient.patient_name as patient_patient_name, mobile"]:
                with self.subTest(bad=bad), self.assertRaises(frappe.ValidationError):
                    listing.desk_columns("Patient Encounter", ["name", "patient", bad])
            with self.assertRaises(frappe.ValidationError):
                listing.desk_columns("Patient Encounter", ["name", "patient.patient_name as patient_patient_name"])

    def test_desk_non_link_title_alias_rejected(self):
        meta = frappe._dict(get_field=lambda field: frappe._dict(fieldtype="Data", options="Patient"))
        with patch.object(frappe, "get_meta", return_value=meta), self.assertRaises(frappe.ValidationError):
            listing.desk_columns("Patient Encounter", ["patient", "patient.patient_name as patient_patient_name"])

    def test_desk_title_supplement_removed_before_query_and_masks_retained(self):
        params = frappe._dict(doctype="Customer", fields=["name", "mobile_no", "customer_primary_contact", "customer_primary_contact.full_name as customer_primary_contact_full_name"], page_length=20)
        parent = frappe._dict(get_field=lambda field: frappe._dict(fieldtype="Link", options="Contact"))
        linked = frappe._dict(show_title_field_in_link=1, title_field="full_name")
        def original():
            self.assertEqual(frappe.local.form_dict.fields, ["name", "mobile_no", "customer_primary_contact"])
            return {"keys": ["name", "mobile_no", "customer_primary_contact"], "values": [["C1", "2025550181", "CT1"]]}
        with patch.object(frappe.local,"form_dict",params,create=True), patch.object(frappe,"form_dict",params), patch.object(frappe,"get_meta",side_effect=lambda dt: parent if dt=="Customer" else linked), patch("frappe.desk.reportview.get",side_effect=original):
            result = listing.reportview_get()
            self.assertEqual(result["keys"], ["name", "mask_mobile", "customer_primary_contact"])
            self.assertEqual(result["values"], [["C1", "******0181", "CT1"]])
            self.assertIs(frappe.local.form_dict, params)
