import unittest
from unittest.mock import patch
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request
import frappe
from privacy_shield import request_guards
from privacy_shield.policy import Capabilities


class RequestGuardTests(unittest.TestCase):
    def setUp(self):
        for p in [patch.object(frappe.local, "flags", frappe._dict(in_test=True), create=True),
                  patch.object(frappe, "conf", {"privacy_shield_desk_enabled": True}),
                  patch.object(frappe, "form_dict", {}),
                  patch.object(request_guards, "current_capabilities", return_value=Capabilities())]:
            p.start(); self.addCleanup(p.stop)

    def check_route(self, path, method="GET", denied=True):
        request = Request(EnvironBuilder(path=path, method=method).get_environ())
        with patch.object(frappe.local, "request", request, create=True):
            if denied:
                with self.assertRaises(frappe.PermissionError): request_guards.guard_rest()
            else:
                request_guards.guard_rest()

    def test_v1_aliases_and_mutations(self):
        for prefix in ["/api", "/api/v1"]:
            for method in ["PUT", "DELETE", "POST"]:
                self.check_route(prefix + "/resource/CRM%20Lead/L1", method)
            self.check_route(prefix + "/resource/Patient", "POST")
            self.check_route(prefix + "/resource/Patient")

    def test_v2_reads_copy_count_and_mutations(self):
        for path in ["/api/v2/document/Patient", "/api/v2/document/Patient/P1/",
                     "/api/v2/document/Patient/P1/copy", "/api/v2/doctype/Patient/count",
                     "/api/v2/document/Patient/P1/method/custom"]:
            self.check_route(path)
        self.check_route("/api/v2/document/Patient/P1", "PATCH")

    def test_direct_contact_child_is_scoped(self):
        self.check_route("/api/resource/Contact%20Phone/ROW1")

    def test_v2_in_memory_method(self):
        with patch.object(frappe, "form_dict", {"document": '{"doctype":"Patient"}'}):
            self.check_route("/api/v2/method/run_doc_method", "POST")

    def test_rpc_unrelated_and_deferred_are_unchanged(self):
        for path in ["/api/method/frappe.client.get", "/api/v2/method/frappe.client.get",
                     "/api/resource/ToDo", "/api/resource/Chat%20Contact/C1",
                     "/api/resource/Vobiz%20Call%20Log/V1", "/api/unknown"]:
            self.check_route(path, denied=False)

    def test_gate_off_skips_policy(self):
        with patch.object(frappe, "conf", {}), patch.object(request_guards, "current_capabilities") as policy:
            self.check_route("/api/resource/Patient/P1", denied=False)
            policy.assert_not_called()

    def test_full_view_without_edit_is_not_write_bypass(self):
        with patch.object(request_guards, "current_capabilities", return_value=Capabilities(True, False)):
            self.check_route("/api/resource/Patient/P1", "PUT")

    def test_full_view_editor_retains_framework_route(self):
        with patch.object(request_guards, "current_capabilities", return_value=Capabilities(True, True)):
            self.check_route("/api/resource/Patient/P1", "PUT", denied=False)

    def test_sdk_preview_reads_are_routed_not_passed_through(self):
        for prefix in ("/api", "/api/v1"):
            with patch.object(frappe, "form_dict", {}):
                self.check_route(prefix + "/resource/Patient/P1", denied=False)
                self.assertEqual(frappe.form_dict["cmd"], "privacy_shield.rest_preview.read")
            with patch.object(frappe, "form_dict", {"fields": '["name"]', "order_by":"creation desc", "limit":"1", "as_dict":"true"}):
                self.check_route(prefix + "/resource/Patient", denied=False)
                self.assertEqual(frappe.form_dict["cmd"], "privacy_shield.rest_preview.read")

    def test_preview_rejects_additional_arguments_and_phone_queries(self):
        for changes in ({"fields": '["mobile"]'}, {"filters": '[ ["mobile", "=", "123"] ]'}, {"limit":"0"}, {"order_by":"mobile desc"}, {"cmd":"frappe.client.get"}, {"debug":"1"}):
            args={"fields": '["name"]', "order_by":"creation desc", "limit":"1", **changes}
            with patch.object(frappe, "form_dict", args):
                self.check_route("/api/resource/Patient")
        with patch.object(frappe, "form_dict", {"run_method":"custom"}):
            self.check_route("/api/resource/Patient/P1")
