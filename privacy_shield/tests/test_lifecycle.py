import unittest
from unittest.mock import patch, MagicMock
from copy import deepcopy
import frappe
from privacy_shield import lifecycle
from privacy_shield.policy import Capabilities

class LifecycleTests(unittest.TestCase):
    def setUp(self):
        for p in [patch.object(frappe.local,"flags",frappe._dict(in_test=True),create=True),
                  patch.object(frappe,"conf",{"privacy_shield_desk_enabled":True}),
                  patch("privacy_shield.lifecycle.current_capabilities",return_value=Capabilities())]:
            p.start();self.addCleanup(p.stop)

    def test_create_requires_edit_for_supplied_originals(self):
        with self.assertRaises(frappe.PermissionError):
            lifecycle.prepare_new({"doctype":"Patient","mobile":"9876543210"},Capabilities())
        result=lifecycle.prepare_new({"doctype":"Patient","mobile":"9876543210"},Capabilities(False,True))
        self.assertEqual(result["mobile"],"9876543210")

    def test_blank_new_fields_can_be_resolved_by_backend(self):
        result=lifecycle.prepare_new({"doctype":"Patient Encounter","sr_pe_mobile":"","patient":"P1"},Capabilities())
        self.assertNotIn("sr_pe_mobile",result)
        self.assertEqual(result["patient"],"P1")

    def test_masks_and_derived_keys_rejected(self):
        for data in [{"doctype":"Patient","mobile":"******3210"},
                     {"doctype":"CRM Lead","sr_mobile_norm":"9876543210"}]:
            with self.assertRaises((frappe.PermissionError,frappe.ValidationError)):
                lifecycle.prepare_new(data,Capabilities(True,True))

    def test_client_bypass_flags_removed_recursively(self):
        data={"doctype":"Contact","flags":{"ignore_permissions":True},"ignore_permissions":True,
              "phone_nos":[{"phone":"9876543210","flags":{"ignore_validate":True}}]}
        result=lifecycle.prepare_new(data,Capabilities(False,True))
        self.assertNotIn("flags",result)
        self.assertNotIn("ignore_permissions",result)
        self.assertNotIn("flags",result["phone_nos"][0])
        self.assertIn("flags",data)

    def test_new_contact_children_get_new_identities(self):
        data={"doctype":"Contact","name":"new-contact-1","phone_nos":[{"name":"old-row",
              "parent":"new-contact-1","parenttype":"Contact","parentfield":"phone_nos","phone":"9876543210"}]}
        result=lifecycle.prepare_new(data,Capabilities(False,True))
        self.assertNotIn("name",result["phone_nos"][0])
        data["phone_nos"][0]["parent"]="Another Contact"
        with self.assertRaises(frappe.PermissionError): lifecycle.prepare_new(data,Capabilities(True,True))

    def test_insert_masks_response_and_uses_framework(self):
        with patch("privacy_shield.lifecycle.current_capabilities",return_value=Capabilities(False,True)), \
             patch("frappe.client.insert",side_effect=lambda d:{**d,"name":"P1"}) as original:
            result=lifecycle.insert({"doctype":"Patient","mobile":"9876543210"})
            self.assertNotIn("9876543210",str(result))
            self.assertEqual(original.call_args.args[0]["mobile"],"9876543210")

    def test_insert_many_preflights_before_first_insert(self):
        with patch("frappe.client.insert_many") as original:
            with self.assertRaises(frappe.PermissionError):
                lifecycle.insert_many([{"doctype":"Patient"},{"doctype":"Patient","mobile":"9876543210"}])
            original.assert_not_called()

    def test_submit_projects_framework_result(self):
        stored={"doctype":"Patient Encounter","name":"E1","sr_pe_mobile":"9876543210"}
        with patch("privacy_shield.lifecycle._prepare",return_value=stored), \
             patch("frappe.client.submit",return_value={**stored,"docstatus":1}) as original:
            result=lifecycle.submit({"doctype":"Patient Encounter","name":"E1"})
            self.assertEqual(result["docstatus"],1)
            self.assertNotIn("9876543210",str(result))
            original.assert_called_once_with(stored)

    def test_cancel_checks_read_and_cancel_permission(self):
        doc=MagicMock();doc.as_dict.return_value={"doctype":"Sales Invoice","name":"I1","contact_mobile":"9876543210"}
        with patch.object(frappe,"get_doc",return_value=doc):
            result=lifecycle.cancel("Sales Invoice","I1")
            self.assertEqual([c.args[0] for c in doc.check_permission.call_args_list],["read","cancel"])
            doc.cancel.assert_called_once()
            self.assertNotIn("9876543210",str(result))

    def test_bulk_denial_happens_before_any_save(self):
        doc=MagicMock();doc.as_dict.return_value={"doctype":"Patient","name":"P1","mobile":"9876543210"}
        with patch.object(frappe,"get_doc",return_value=doc):
            with self.assertRaises(frappe.PermissionError):
                lifecycle.bulk_update([{"doctype":"Patient","docname":"P1","patient_name":"Changed"},
                                       {"doctype":"Patient","docname":"P1","mobile":""}])
            doc.save.assert_not_called()

    def test_deferred_insert_passes_through(self):
        with patch("frappe.client.insert",return_value={"doctype":"Chat Contact","phone_number":"raw"}) as original:
            data={"doctype":"Chat Contact","phone_number":"raw"}
            self.assertEqual(lifecycle.insert(data),data)
            original.assert_called_once_with(data)

    def test_direct_contact_child_insert_rejected(self):
        with self.assertRaises(frappe.PermissionError): lifecycle.insert({"doctype":"Contact Phone","phone":"12345"})

    def test_existing_save_payload_also_drops_client_flags(self):
        from privacy_shield.desk import prepare_payload
        stored={"doctype":"Patient","name":"P1","mobile":"9876543210"}
        result=prepare_payload({"doctype":"Patient","name":"P1","flags":{"ignore_validate":True}},stored,Capabilities())
        self.assertNotIn("flags",result)
        self.assertEqual(result["mobile"],"9876543210")
