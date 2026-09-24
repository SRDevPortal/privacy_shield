import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import frappe
from privacy_shield import notification_reads as reads
from sriaas_clinic.api.crm_lead import privacy_notifications as crm


class NotificationReadTests(unittest.TestCase):
    def setUp(self):
        for item in (patch.object(frappe, "conf", {"privacy_shield_desk_enabled": True}),
                     patch.object(frappe.local, "flags", frappe._dict(read_only=False), create=True),
                     patch.object(frappe.local, "session", frappe._dict(user="agent"), create=True),
                     patch("privacy_shield.policy.current_capabilities", return_value=SimpleNamespace(view_full=False))):
            item.start(); self.addCleanup(item.stop)

    def test_log_feed_is_owned_bounded_and_projected(self):
        row=frappe._dict(name="N1", document_type="Patient", document_name="P1", for_user="agent", from_user=None, subject="9876543210", email_content="9876543210", attached_file="9876543210", link="9876543210")
        with patch.object(frappe,"has_permission",return_value=True),patch.object(frappe,"get_all",return_value=[row]) as query:
            result=reads.get_notification_logs(100000)
            self.assertNotIn("9876543210",str(result))
            self.assertEqual(query.call_args.kwargs["filters"], {"for_user":"agent"})
            self.assertEqual(query.call_args.kwargs["limit_page_length"],100)
            self.assertEqual(row.subject,"9876543210")

    def test_feed_native_doctype_denial_stops_query(self):
        with patch.object(frappe,"has_permission",return_value=False),patch.object(frappe,"get_all") as query:
            with self.assertRaises(frappe.PermissionError): reads.get_notification_logs()
            query.assert_not_called()

    def test_log_mark_read_filters_owner_and_only_updates_read(self):
        with patch.object(frappe.local,"db",MagicMock(),create=True):
            reads.mark_as_read("N1")
            frappe.db.set_value.assert_called_once_with("Notification Log",{"name":"N1","for_user":"agent"},"read",1,update_modified=False)

    def test_crm_feed_drops_unknown_keys_preserves_route(self):
        row={"reference_doctype":"lead","reference_name":"L1","route_name":"Lead","hash":"#C1","notification_text":"9876543210","extra":"9876543210"}
        with patch("crm.api.notifications.get_notifications",return_value=[row]):
            result=crm.get_notifications()
            self.assertNotIn("9876543210",str(result))
            self.assertEqual(result[0]["hash"],"#C1")
            self.assertEqual(row["notification_text"],"9876543210")

    def test_crm_mark_read_rejects_other_user_before_query(self):
        with patch.object(frappe,"get_all") as query:
            with self.assertRaises(frappe.PermissionError): crm.mark_as_read(user="other")
            query.assert_not_called()

    def test_crm_mark_read_rechecks_ownership_in_update(self):
        with patch.object(frappe,"get_all",return_value=[frappe._dict(name="N1")]) as query,patch.object(frappe.local,"db",MagicMock(),create=True):
            crm.mark_as_read(doc="C1")
            self.assertEqual(query.call_args.kwargs["filters"],{"to_user":"agent","read":0})
            frappe.db.set_value.assert_called_once_with("CRM Notification",{"name":"N1","to_user":"agent"},"read",1,update_modified=False)

    def test_gate_off_and_full_delegate_native_feeds(self):
        for gate, full in ((False,False),(True,True)):
            with patch.object(frappe,"conf",{"privacy_shield_desk_enabled":gate}),patch("privacy_shield.policy.current_capabilities",return_value=SimpleNamespace(view_full=full)):
                with patch("frappe.desk.doctype.notification_log.notification_log.get_notification_logs",return_value="native") as original:
                    self.assertEqual(reads.get_notification_logs(7),"native");original.assert_called_once_with(7)
                with patch("crm.api.notifications.get_notifications",return_value=[{"notification_text":"9876543210"}]):
                    self.assertEqual(crm.get_notifications()[0]["notification_text"],"9876543210")

    def test_read_only_does_not_modify_notification_state(self):
        with patch.object(frappe.local,"flags",frappe._dict(read_only=True)),patch.object(frappe.local,"db",MagicMock(),create=True):
            reads.mark_as_read("N1");crm.mark_as_read()
            frappe.db.set_value.assert_not_called()
