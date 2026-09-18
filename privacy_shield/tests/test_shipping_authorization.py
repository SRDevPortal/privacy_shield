import unittest
from unittest.mock import MagicMock, patch
import frappe
from shipment_tracking.api import tracking, order
from sriaas_clinic.api.integrations import shipkia_sales_invoice as manual


class ShippingAuthorizationTests(unittest.TestCase):
    def setUp(self):
        flags = patch.object(frappe.local, "flags", frappe._dict(in_test=True), create=True)
        flags.start()
        self.addCleanup(flags.stop)

    def test_all_routes_deny_before_provider_or_mutation(self):
        routes = [(tracking.sync_tracking_for_shipment, tracking),
                  (tracking.sync_tracking_by_order_id, tracking),
                  (tracking.sync_tracking_for_invoice, tracking),
                  (tracking.sync_tracking_for_encounter, tracking),
                  (order.create_order_for_sales_invoice, order),
                  (manual.send_sales_invoice_to_shipkia, manual)]
        for route, module in routes:
            for denied in ("read", "write"):
                with self.subTest(route=route.__name__, denied=denied):
                    doc = MagicMock()
                    def check(permission):
                        if permission == denied:
                            raise frappe.PermissionError("denied")
                    doc.check_permission.side_effect = check
                    with patch.object(frappe, "get_doc", return_value=doc), \
                         patch.object(frappe, "db", MagicMock()), \
                         patch.object(tracking, "_sync_tracking") as sync, \
                         patch.object(tracking, "repair_shipment_links") as repair, \
                         patch.object(tracking, "get_or_create_shipment") as lookup, \
                         patch.object(order.requests, "post") as post, \
                         patch.object(manual, "_post_shipkia") as manual_post:
                        with self.assertRaises(frappe.PermissionError):
                            route("synthetic")
                        sync.assert_not_called(); repair.assert_not_called()
                        lookup.assert_not_called(); post.assert_not_called()
                        manual_post.assert_not_called(); doc.save.assert_not_called()

    def test_source_actions_authorize_before_resolving_and_repairing(self):
        for route in (tracking.sync_tracking_for_invoice, tracking.sync_tracking_for_encounter):
            events = []
            source = MagicMock()
            source.check_permission.side_effect = lambda permission: events.append(permission)
            shipment = MagicMock()
            with patch.object(frappe, "get_doc", return_value=source), \
                 patch.object(tracking, "validate_manual_tracking_refresh_enabled", side_effect=lambda: events.append("setting")), \
                 patch.object(tracking, "get_or_create_shipment", side_effect=lambda **kw: (events.append("lookup") or shipment)), \
                 patch.object(tracking, "repair_shipment_links", side_effect=lambda *a, **kw: events.append("repair")), \
                 patch.object(tracking, "_sync_tracking", return_value={"success": True}) as sync:
                self.assertEqual(route("synthetic"), {"success": True})
                self.assertEqual(events, ["read", "write", "setting", "lookup", "repair"])
                sync.assert_called_once_with(shipment)

    def test_manual_disabled_blocks_direct_shipment_routes(self):
        for route in (tracking.sync_tracking_for_shipment, tracking.sync_tracking_by_order_id):
            with patch.object(frappe, "get_doc", return_value=MagicMock()), \
                 patch.object(frappe, "db", MagicMock()), \
                 patch.object(tracking, "validate_manual_tracking_refresh_enabled", side_effect=frappe.ValidationError), \
                 patch.object(tracking, "_sync_tracking") as sync:
                with self.assertRaises(frappe.ValidationError): route("synthetic")
                sync.assert_not_called()

    def test_scheduler_uses_internal_operation_without_manual_gate(self):
        shipment = MagicMock()
        with patch.object(frappe, "get_all", return_value=["synthetic"]), \
             patch.object(frappe, "get_doc", return_value=shipment), \
             patch.object(tracking, "_sync_tracking") as sync, \
             patch.object(tracking, "validate_manual_tracking_refresh_enabled") as gate:
            tracking.sync_active_shipments()
            sync.assert_called_once_with(shipment)
            gate.assert_not_called(); shipment.check_permission.assert_not_called()
        self.assertNotIn(tracking._sync_tracking, frappe.whitelisted)
        self.assertNotIn(tracking.sync_active_shipments, frappe.whitelisted)

    def test_authorized_tracking_returns_summary_not_raw_provider_payload(self):
        shipment = MagicMock(); shipment.name = "SYNTHETIC"; shipment.shipkia_order_id = "ORDER"
        shipment.shipkia_status = "Transit"
        log = MagicMock(); log.insert.return_value = log
        response = MagicMock(status_code=200)
        body = {"result": {"mobile": "9876543210", "status": "Transit"}}
        with patch.object(frappe, "get_doc", return_value=log), \
             patch.object(tracking, "get_settings", return_value=MagicMock(enabled=True)), \
             patch.object(tracking, "make_auth_headers", return_value={}), \
             patch.object(tracking.requests, "post", return_value=response) as post, \
             patch.object(tracking, "safe_response_json", return_value=body), \
             patch.object(tracking, "apply_tracking_response") as apply:
            result = tracking._sync_tracking(shipment)
            self.assertTrue(result["success"])
            self.assertNotIn("9876543210", str(result))
            apply.assert_called_once_with(shipment, body);post.assert_called_once()

    def test_shipping_mutation_routes_are_post_only(self):
        for route in [tracking.sync_tracking_for_shipment, tracking.sync_tracking_by_order_id,
                      tracking.sync_tracking_for_invoice, tracking.sync_tracking_for_encounter,
                      order.create_order_for_sales_invoice, manual.send_sales_invoice_to_shipkia]:
            self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[route], ["POST"])

    def test_authorized_manual_send_preserves_success(self):
        invoice = MagicMock(docstatus=1); invoice.name = "SYNTHETIC"
        response = MagicMock(status_code=200)
        with patch.object(frappe, "get_doc", return_value=invoice), \
             patch.object(frappe, "db", MagicMock()), \
             patch.object(manual, "_settings", return_value=MagicMock(enable_sync=True)), \
             patch.object(manual, "_build_payload_from_so", return_value={"synthetic": True}), \
             patch.object(manual, "_post_shipkia", return_value=response) as post:
            self.assertTrue(manual.send_sales_invoice_to_shipkia("SYNTHETIC")["success"])
            self.assertEqual([c.args for c in invoice.check_permission.call_args_list], [("read",), ("write",)])
            post.assert_called_once_with({"synthetic": True})

    def test_authorized_order_creation_preserves_success(self):
        invoice = MagicMock(docstatus=1); invoice.name = "SYNTHETIC"; invoice.si_shipkia_order_id = ""
        log = MagicMock(); shipment = MagicMock(); shipment.name = "SHIPMENT"
        response = MagicMock(status_code=200)
        with patch.object(frappe, "get_doc", return_value=invoice), \
             patch.object(frappe, "db", MagicMock()), \
             patch.object(order, "get_settings", return_value=MagicMock(enabled=True)), \
             patch.object(order, "build_payload_from_sales_invoice", return_value={}), \
             patch.object(order, "make_sync_log", return_value=log), \
             patch.object(order, "make_auth_headers", return_value={}), \
             patch.object(order.requests, "post", return_value=response) as post, \
             patch.object(order, "safe_response_json", return_value={}), \
             patch.object(order, "first_order_id", return_value="ORDER"), \
             patch.object(order, "get_linked_encounter", return_value=None), \
             patch.object(order, "create_or_update_shipment_from_order_response", return_value=shipment):
            result = order.create_order_for_sales_invoice("SYNTHETIC")
            self.assertTrue(result["success"]); self.assertEqual(result["order_id"], "ORDER")
            self.assertEqual([c.args for c in invoice.check_permission.call_args_list], [("read",), ("write",)])
            post.assert_called_once()

    def test_order_provider_rejections_do_not_echo_customer_data(self):
        for status in (400, 200):
            invoice=MagicMock(docstatus=1);invoice.si_shipkia_order_id=""
            body={"error":"Invalid recipient 9876543210"}
            with patch.object(frappe,"get_doc",return_value=invoice), \
                 patch.object(frappe,"db",MagicMock()), \
                 patch.object(frappe,"throw",side_effect=lambda message: (_ for _ in ()).throw(frappe.ValidationError(message))), \
                 patch.object(order,"get_settings",return_value=MagicMock(enabled=True)), \
                 patch.object(order,"build_payload_from_sales_invoice",return_value={}), \
                 patch.object(order,"make_sync_log",return_value=MagicMock()), \
                 patch.object(order,"make_auth_headers",return_value={}), \
                 patch.object(order.requests,"post",return_value=MagicMock(status_code=status)), \
                 patch.object(order,"safe_response_json",return_value=body), \
                 patch.object(order,"first_order_id",return_value=None):
                with self.assertRaises(frappe.ValidationError) as raised:
                    order.create_order_for_sales_invoice("SYNTHETIC")
                self.assertNotIn("9876543210",str(raised.exception))

    def test_tracking_network_exception_is_not_returned_to_client(self):
        shipment=MagicMock();log=MagicMock();log.insert.return_value=log
        with patch.object(frappe,"get_doc",return_value=log), \
             patch.object(frappe,"db",MagicMock()), \
             patch.object(frappe,"get_traceback",return_value="private server diagnostic"), \
             patch.object(frappe,"throw",side_effect=lambda message: (_ for _ in ()).throw(frappe.ValidationError(message))), \
             patch.object(tracking,"get_settings",return_value=MagicMock(enabled=True)), \
             patch.object(tracking,"make_auth_headers",return_value={}), \
             patch.object(tracking.requests,"post",side_effect=RuntimeError("recipient 9876543210")):
            with self.assertRaises(frappe.ValidationError) as raised:tracking._sync_tracking(shipment)
            self.assertNotIn("9876543210",str(raised.exception))
            self.assertEqual(log.error_message,"private server diagnostic")
