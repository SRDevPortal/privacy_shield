import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import frappe
from shipment_tracking.api import privacy, support


class LinkedSupportSummaryTests(unittest.TestCase):
    def setUp(self):
        for item in [patch.object(frappe,"conf",{"privacy_shield_desk_enabled":True}),
                     patch.object(frappe,"session",SimpleNamespace(user="agent")),
                     patch.object(frappe,"get_roles",return_value=["Agent"]),
                     patch("privacy_shield.policy.current_capabilities",return_value=SimpleNamespace(view_full=False))]:
            item.start();self.addCleanup(item.stop)

    def source(self,dt="Sales Invoice"):
        source=MagicMock();source.doctype=dt;source.name="SOURCE1";source.get.return_value="ORDER1"
        return source

    def ticket(self,**values):
        return frappe._dict(name="TICKET1",owner="agent",creation="2026-09-18",shipkia_order_id="ORDER1",**values)

    def test_both_source_types_return_metadata_without_loading_raw_ticket(self):
        for dt,field in [("Sales Invoice","sales_invoice"),("Patient Encounter","patient_encounter")]:
            source=self.source(dt)
            db=MagicMock();db.get_value.return_value=self.ticket(**{field:"SOURCE1"})
            with patch.object(frappe,"db",db),patch.object(frappe,"get_doc") as load:
                result=support.get_existing_support_state(source,"TICKET1")
                self.assertTrue(result["has_existing_ticket"]);self.assertTrue(result["details_restricted"])
                self.assertEqual(result["latest_ticket"],"TICKET1");source.check_permission.assert_called_once_with("read")
                load.assert_not_called()
                self.assertEqual(db.get_value.call_args.args[1],{"name":"TICKET1","owner":"agent"})
                self.assertEqual(set(db.get_value.call_args.args[2]),{"name","owner","creation","shipkia_order_id",field})

    def test_source_denial_precedes_ticket_lookup(self):
        source=self.source();source.check_permission.side_effect=frappe.PermissionError
        with patch.object(frappe,"db",MagicMock()) as db:
            with self.assertRaises(frappe.PermissionError):privacy.linked_support_summary(source,"TICKET1")
            db.get_value.assert_not_called()

    def test_conflicting_source_is_denied_despite_matching_order(self):
        with patch.object(frappe,"db",MagicMock(get_value=MagicMock(return_value=self.ticket(sales_invoice="OTHER")))):
            with self.assertRaises(frappe.PermissionError):privacy.linked_support_summary(self.source(),"TICKET1")

    def test_missing_explicit_or_unrelated_order_is_denied(self):
        for ticket in [None,frappe._dict(name="TICKET1",sales_invoice=None,shipkia_order_id="OTHER")]:
            with patch.object(frappe,"db",MagicMock(get_value=MagicMock(return_value=ticket))):
                with self.assertRaises(frappe.PermissionError):privacy.linked_support_summary(self.source(),"TICKET1")

    def test_legacy_order_binding_and_absent_ticket(self):
        with patch.object(frappe,"db",MagicMock(get_value=MagicMock(return_value=self.ticket(sales_invoice=None)))):
            self.assertTrue(privacy.linked_support_summary(self.source(),"TICKET1")["has_existing_ticket"])
        with patch.object(frappe,"db",MagicMock(get_value=MagicMock(return_value=None))):
            self.assertFalse(privacy.linked_support_summary(self.source())["has_existing_ticket"])

    def test_gate_off_or_full_view_keeps_original_lookup(self):
        for enabled,full in [(False,False),(True,True)]:
            with patch.object(frappe,"conf",{"privacy_shield_desk_enabled":enabled}), \
                 patch("privacy_shield.policy.current_capabilities",return_value=SimpleNamespace(view_full=full)), \
                 patch.object(support,"existing_visible_ticket",return_value=None) as original, \
                 patch.object(support,"linked_support_summary") as projection:
                support.get_existing_support_state(self.source(),"TICKET1")
                original.assert_called_once();projection.assert_not_called()
