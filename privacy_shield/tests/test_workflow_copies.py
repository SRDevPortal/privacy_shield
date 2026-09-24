import unittest
from types import SimpleNamespace
from unittest.mock import patch
import frappe
from privacy_shield.desk import project_document, prepare_payload, enabled
from privacy_shield.lifecycle import prepare_new
from privacy_shield.policy import Capabilities
from privacy_shield.address_views import support_address

class WorkflowCopyTests(unittest.TestCase):
    def setUp(self):
        self.appointment = {"doctype":"Clinic Appointment","name":"SYNTHETIC","patient":"P1",
                            "mobile_number":"2025550101","alternate_mobile":"2025550199"}

    def test_appointment_omits_distinct_originals_and_preserves_save(self):
        response=project_document(self.appointment,Capabilities())
        self.assertEqual(response["mask_mobile"],"******0101")
        self.assertEqual(response["mask_alternate_mobile"],"******0199")
        self.assertNotIn("2025550101",str(response))
        self.assertNotIn("2025550199",str(response))
        restored=prepare_payload(response,self.appointment,Capabilities())
        self.assertEqual(restored,self.appointment)

    def test_appointment_full_and_gate_off_contract(self):
        self.assertEqual(project_document(self.appointment,Capabilities(True,False))["mobile_number"],"2025550101")
        with patch.object(frappe,"conf",{}):self.assertFalse(enabled("Clinic Appointment"))
        with patch.object(frappe,"conf",{"privacy_shield_desk_enabled":True}):self.assertTrue(enabled("Clinic Appointment"))

    def test_changed_patient_is_authorized_and_resolved_without_stale_numbers(self):
        values={"mobile":"2025550111","phone":"2025550122","patient_name":"Second Synthetic"}
        source=SimpleNamespace(get=values.get,check_permission=lambda kind:None)
        response=project_document(self.appointment,Capabilities());response["patient"]="P2"
        with patch.object(frappe,"get_doc",return_value=source) as lookup:
            saved=prepare_payload(response,self.appointment,Capabilities())
        lookup.assert_called_once_with("Patient","P2")
        self.assertEqual(saved["mobile_number"],values["mobile"])
        self.assertEqual(saved["alternate_mobile"],values["phone"])
        self.assertEqual(saved["patient_name"],values["patient_name"])

    def test_new_and_changed_patient_require_native_read_permission(self):
        def deny(kind):raise frappe.PermissionError()
        source=SimpleNamespace(check_permission=deny)
        with patch.object(frappe,"get_doc",return_value=source):
            with self.assertRaises(frappe.PermissionError):prepare_new({"doctype":"Clinic Appointment","patient":"DENIED"},Capabilities())
            data=project_document(self.appointment,Capabilities());data["patient"]="DENIED"
            with self.assertRaises(frappe.PermissionError):prepare_payload(data,self.appointment,Capabilities())

    def test_direct_copy_changes_remain_forbidden(self):
        for field in ("mobile_number","alternate_mobile"):
            with self.subTest(field=field),self.assertRaises(PermissionError):
                prepare_payload({**self.appointment,field:"2025550000"},self.appointment,Capabilities())

    def test_customer_formatted_address_is_derived_sensitive_data(self):
        stored={"doctype":"Customer","name":"SYNTHETIC","mobile_no":"2025550101",
                "primary_address":"Street<br>Phone: 2025550101"}
        response=project_document(stored,Capabilities())
        self.assertNotIn("primary_address",response)
        self.assertEqual(prepare_payload(response,stored,Capabilities())["primary_address"],stored["primary_address"])
        self.assertEqual(project_document(stored,Capabilities(True,False))["primary_address"],stored["primary_address"])

    def test_support_address_uses_permitted_mailing_fields_not_phone_html(self):
        customer=SimpleNamespace(permitted_fieldnames={"customer_primary_address"},get=lambda key:"ADDRESS")
        values={"address_line1":"42 Test <Street>","city":"Test City","pincode":"110001","phone":"2025550101"}
        address=SimpleNamespace(permitted_fieldnames=set(values),get=values.get,has_permission=lambda kind:True)
        with patch.object(frappe,"get_doc",return_value=address):result=support_address(customer)
        self.assertEqual(result,"42 Test &lt;Street&gt;<br>Test City<br>110001")
        self.assertNotIn("2025550101",result)
        address.permitted_fieldnames.remove("pincode")
        with patch.object(frappe,"get_doc",return_value=address):self.assertNotIn("110001",support_address(customer))

    def test_support_address_does_not_expose_unreadable_links(self):
        customer=SimpleNamespace(permitted_fieldnames={"customer_primary_address"},get=lambda key:"ADDRESS")
        with patch.object(frappe,"get_doc",return_value=SimpleNamespace(has_permission=lambda kind:False)):
            self.assertEqual(support_address(customer),"")
        customer.permitted_fieldnames=set()
        with patch.object(frappe,"get_doc") as lookup:
            self.assertEqual(support_address(customer),"");lookup.assert_not_called()

    def test_new_viewer_intake_accepts_only_authorized_patient_autofill(self):
        values={"mobile":"2025550101","phone":"2025550199"}
        source=SimpleNamespace(get=values.get,check_permission=lambda kind:None)
        with patch.object(frappe,"get_doc",return_value=source):
            data=prepare_new({"doctype":"Clinic Appointment","patient":"P1",
                              "mobile_number":values["mobile"],"alternate_mobile":values["phone"]},Capabilities(True,False))
            self.assertNotIn("mobile_number",data)
            self.assertNotIn("alternate_mobile",data)
            for value in ("2025550000","******0101"):
                with self.subTest(value=value),self.assertRaises(frappe.PermissionError):
                    prepare_new({"doctype":"Clinic Appointment","patient":"P1","mobile_number":value},Capabilities(True,False))

    def test_full_viewer_can_save_unchanged_formatted_address_with_asterisks(self):
        stored={"doctype":"Customer","name":"SYNTHETIC","primary_address":"Building * Wing<br>Phone: 2025550101"}
        self.assertEqual(prepare_payload(stored,stored,Capabilities(True,False))["primary_address"],stored["primary_address"])
        with self.assertRaises(PermissionError):
            prepare_payload({**stored,"primary_address":"Changed"},stored,Capabilities(True,True))

    def test_desk_save_response_supports_frappe_dict_and_document_objects(self):
        from privacy_shield.desk import _project_response
        for value in (dict(self.appointment), frappe._dict(self.appointment),
                      SimpleNamespace(as_dict=lambda:dict(self.appointment))):
            response={"docs":[value]}
            with self.subTest(kind=type(value).__name__),patch.object(frappe,"response",response):
                _project_response(Capabilities())
                self.assertEqual(response["docs"][0]["mask_mobile"],"******0101")
                self.assertNotIn("2025550101",str(response))
