import unittest
from copy import deepcopy
from unittest.mock import patch
from types import SimpleNamespace
import frappe
from sriaas_clinic.api.crm_lead import privacy_views as adapter

class CRMViewTests(unittest.TestCase):
    def setUp(self):
        self.defaults={"columns":[{"key":"mobile_no","label":"Mobile"},{"key":"phone"}],
          "rows":["name","mobile_no","phone"],"kanban_fields":'["mobile_no", "phone"]'}
        self.args=dict(doctype="CRM Lead",filters={},order_by="modified desc",view={"view_type":"list"})
        self.payload={"data":[{"name":"L1","mobile_no":"9876543210","phone":"1234567890", "sr_mobile_norm":"9876543210"}],
          "columns":[{"key":"mobile_no","label":"Mobile"},{"key":"phone","label":"Phone"}],
          "rows":["name","mobile_no","phone","sr_mobile_norm"],
          "fields":[{"fieldname":"mobile_no"},{"fieldname":"phone"},{"fieldname":"sr_mobile_norm"}],
          "kanban_fields":["mobile_no","phone"],"views":[],"total_count":50,"row_count":1,"view_type":"list"}

    def test_list_columns_values_and_counts_agree(self):
        before=deepcopy(self.payload)
        result=adapter.project_layout(self.payload,False)
        self.assertEqual(result["columns"][0]["key"],"mask_mobile")
        self.assertEqual(result["data"][0]["mask_mobile"],"******3210")
        self.assertEqual(result["data"][0]["mask_phone"],"******7890")
        self.assertEqual(result["total_count"],50)
        self.assertNotIn("9876543210",str(result))
        self.assertEqual(self.payload,before)

    def test_kanban_identity_order_and_counts_preserved(self):
        payload={**self.payload,"view_type":"kanban","data":[{"column":{"name":"New","order":["L1"],"all_count":8},"fields":["mobile_no"],"data":self.payload["data"]}]}
        result=adapter.project_layout(payload,False)
        bucket=result["data"][0]
        self.assertEqual(bucket["column"],payload["data"][0]["column"])
        self.assertEqual(bucket["fields"],["mask_mobile"])
        self.assertEqual(bucket["data"][0]["name"],"L1")
        self.assertNotIn("9876543210",str(result))

    def test_explicit_virtual_request_translated(self):
        args={**self.args,"columns":[{"key":"mask_mobile"}],"rows":["name","mask_mobile"],"kanban_fields":["mask_phone"]}
        result=adapter.prepare(args,False,self.defaults)
        self.assertEqual(result["rows"],["name","mobile_no"])
        self.assertEqual(result["columns"][0]["key"],"mobile_no")
        self.assertEqual(result["kanban_fields"],["phone"])
        self.assertEqual(args["rows"],["name","mask_mobile"])

    def test_saved_virtual_columns_resolved_without_mutation(self):
        saved={"columns":'[{"key":"mask_phone"}]',"rows":'["name","mask_phone"]'}
        result=adapter.prepare(self.args,False,self.defaults,saved)
        self.assertEqual(result["rows"],["name","phone"])
        self.assertIn("mask_phone",saved["rows"])

    def test_full_view_retains_original_and_computes_masks(self):
        result=adapter.project_layout(self.payload,True)
        self.assertEqual(result["data"][0]["mobile_no"],"9876543210")
        self.assertEqual(result["data"][0]["mask_mobile"],"******3210")

    def test_protected_grouping_titles_filters_and_sorting_rejected(self):
        cases=[{"column_field":"mobile_no"},{"title_field":"phone"},
               {"view":{"group_by_field":"sr_mobile_norm"}},
               {"filters":{"mobile_no":["like","98%"]}}, {"order_by":"mask_mobile asc"}]
        for change in cases:
            with self.subTest(change=change),self.assertRaises((frappe.PermissionError,frappe.ValidationError)):
                adapter.prepare({**self.args,**change},False,self.defaults)

    def test_alias_and_unbounded_pagination_rejected(self):
        for change in [{"rows":["mobile_no as other"]},{"page_length":0},
                       {"kanban_columns":[{"name":"New","page_length":10000}]}]:
            with self.subTest(change=change),self.assertRaises(frappe.ValidationError):
                adapter.prepare({**self.args,**change},False,self.defaults)

    def test_sensitive_saved_view_omitted_instead_of_broadening(self):
        payload={**self.payload,"views":[{"name":"private-filter","filters":'{"phone":"1234567890"}'},
           {"name":"normal","filters":"{}","rows":'["mobile_no"]',"columns":'[{"key":"mobile_no"}]'}]}
        result=adapter.project_layout(payload,False)
        self.assertEqual([v["name"] for v in result["views"]],["normal"])
        self.assertIn("mask_mobile",result["views"][0]["rows"])
        self.assertNotIn("1234567890",str(result))

    def test_empty_list_retains_columns(self):
        result=adapter.project_layout({**self.payload,"data":[]},False)
        self.assertEqual(result["columns"][0]["key"],"mask_mobile")

    def test_disabled_wrapper_delegates_unchanged(self):
        with patch.object(frappe.local,"flags",frappe._dict(in_test=True),create=True), \
             patch.object(adapter,"enabled",return_value=False), \
             patch.object(frappe,"get_installed_apps",return_value=[]), \
             patch("crm.api.doc.get_data",return_value=self.payload) as original:
            self.assertEqual(adapter.get_data("CRM Lead",{},"modified desc"),self.payload)
            self.assertEqual(original.call_args.kwargs["doctype"],"CRM Lead")

    def test_dedupe_filters_remain_in_the_call_chain(self):
        with patch.object(frappe.local,"flags",frappe._dict(in_test=True),create=True), \
             patch.object(adapter,"enabled",return_value=False), \
             patch.object(frappe,"get_installed_apps",return_value=["crm_lead_dedupe"]), \
             patch("crm_lead_dedupe.api.crm_doc_guard.is_enabled",return_value=True), \
             patch("crm_lead_dedupe.api.crm_doc_guard.crm_get_data",return_value=self.payload) as original:
            adapter.get_data("CRM Lead",{"sr_is_archived":1,"converted":1},"modified desc")
            self.assertEqual(original.call_args.kwargs["filters"]["sr_is_archived"],0)
            self.assertEqual(original.call_args.kwargs["filters"]["converted"],0)


class CRMSidepanelTests(unittest.TestCase):
    def test_masked_fields_match_document_and_remain_read_only(self):
        from privacy_shield.desk import project_document
        layout = [{"name": "contact", "columns": [{"fields": [
            {"fieldname": "mobile_no", "options": "Phone", "reqd": 1, "hidden": 0},
            {"fieldname": "phone", "read_only_depends_on": "eval:doc.enabled"},
            {"fieldname": "sr_mobile_norm"},
            {"fieldname": "first_name", "label": "First Name"},
        ]}]}]
        before = deepcopy(layout)
        result = adapter.project_sidepanel(layout)
        fields = result[0]["columns"][0]["fields"]
        doc = project_document({"doctype": "CRM Lead", "mobile_no": "9876543210",
                                "phone": "1234567890"},
                               SimpleNamespace(view_full=False, edit_original=False))
        self.assertEqual([f["fieldname"] for f in fields], ["mask_mobile", "mask_phone", "first_name"])
        self.assertEqual([doc[f["fieldname"]] for f in fields[:2]], ["******3210", "******7890"])
        for field in fields[:2]:
            self.assertEqual(field["read_only"], 1)
            self.assertEqual(field["reqd"], 0)
            self.assertIsNone(field["options"])
            self.assertIsNone(field["read_only_depends_on"])
        self.assertEqual(layout, before)
        self.assertEqual(fields[-1], before[0]["columns"][0]["fields"][-1])

    def test_existing_visibility_restrictions_are_preserved(self):
        layout = [{"columns": [{"fields": [{"fieldname": "phone", "hidden": 1,
                                            "depends_on": "eval:doc.enabled"}]}]}]
        field = adapter.project_sidepanel(layout)[0]["columns"][0]["fields"][0]
        self.assertEqual(field["hidden"], 1)
        self.assertEqual(field["depends_on"], "eval:doc.enabled")

    def test_sidepanel_wrapper_gating_and_full_view(self):
        path = "crm.fcrm.doctype.crm_fields_layout.crm_fields_layout.get_sidepanel_sections"
        layout = [{"columns": [{"fields": [{"fieldname": "phone"}]}]}]
        for dt, active, full, expected in [
            ("CRM Lead", False, False, "phone"),
            ("CRM Deal", True, False, "phone"),
            ("CRM Lead", True, True, "phone"),
            ("CRM Lead", True, False, "mask_phone"),
        ]:
            with self.subTest(dt=dt, active=active, full=full),                  patch.object(frappe.local, "flags", frappe._dict(in_test=True), create=True), patch(path, return_value=layout) as original,                  patch.object(adapter, "enabled", return_value=active),                  patch.object(adapter, "current_capabilities", return_value=SimpleNamespace(view_full=full)):
                actual = adapter.get_sidepanel_sections(dt)
                self.assertEqual(actual[0]["columns"][0]["fields"][0]["fieldname"], expected)
                original.assert_called_once_with(dt)
