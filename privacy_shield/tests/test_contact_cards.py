import unittest
from copy import deepcopy
from unittest.mock import patch
from privacy_shield.contact_cards import project_cards
from privacy_shield.desk import project_document
from privacy_shield.policy import Capabilities

class ContactCardsTests(unittest.TestCase):
    def test_contact_labels_emails_flags_and_alternate_numbers(self):
        data={"contact_list":[{"name":"CT1","first_name":"Test","last_name":"Person","designation":"Manager","email_id":"test@example.test","is_primary_contact":1,"mobile_no":"2025550181","phone":"2025550199","phone_nos":[{"phone":"2025550122","secret":"raw"}],"email_ids":[{"email_id":"other@example.test"}],"normalized_phone":"2025550181"}],"provider_secret":"2025550181"}
        original=deepcopy(data);result=project_cards(data);row=result["contact_list"][0]
        self.assertEqual(row["first_name"],"Test")
        self.assertEqual(row["email_id"],"test@example.test")
        self.assertEqual(row["is_primary_contact"],1)
        self.assertEqual(row["mobile_no"],"******0181")
        self.assertEqual(row["phone"],"******0199")
        self.assertEqual(row["phone_nos"],[{"phone":"******0122"}])
        self.assertNotIn("normalized_phone",row)
        self.assertNotIn("provider_secret",result)
        self.assertEqual(data,original)

    def test_address_format_retains_postcode_state_and_title(self):
        data={"addr_list":[{"name":"A1","address_title":"HLC-PAT-2026-43292","address_line1":"42 Test Road","city":"Delhi","pincode":"110071","gst_state_number":"07","phone":"2025550181","display":"RAW 2025550181","secret":"2025550181"}]}
        with patch("frappe.contacts.doctype.address.address.render_address",side_effect=lambda d:d["address_line1"]+"<br>"+d["pincode"]+"<br>"+d["phone"]) as render:
            result=project_cards(data)["addr_list"][0]
        self.assertEqual(result["address_title"],"HLC-PAT-2026-43292")
        self.assertEqual(result["pincode"],"110071")
        self.assertEqual(result["gst_state_number"],"07")
        self.assertIn("******0181",result["display"])
        self.assertNotIn("2025550181",str(result))
        self.assertNotIn("secret",render.call_args.args[0])

    def test_empty_and_full_view_contracts(self):
        self.assertEqual(project_cards(None),{})
        self.assertEqual(project_cards({"contact_list":[],"addr_list":[]}),{"contact_list":[],"addr_list":[]})
        payload={"doctype":"Customer","__onload":{"contact_list":[{"mobile_no":"2025550181"}]}}
        self.assertEqual(project_document(payload,Capabilities(True,False))["__onload"],payload["__onload"])
        self.assertEqual(project_document(payload,Capabilities())["__onload"]["contact_list"][0]["mobile_no"],"******0181")
