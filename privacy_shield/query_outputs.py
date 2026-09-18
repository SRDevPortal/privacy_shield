"""Pilot-only barriers for unreviewed report result routes."""
import frappe
from privacy_shield.import_access import restricted, TARGETS
from privacy_shield.report_outputs import check_report, check_prepared


def check_request(report_name, filters=None, user=None):
    if user and user != frappe.session.user:
        raise frappe.PermissionError("Report user must match the current session during this pilot")
    check_report(report_name)
    filters = frappe.parse_json(filters) if isinstance(filters, str) else filters
    if isinstance(filters, dict) and filters.get("prepared_report_name"):
        name = filters["prepared_report_name"]
        check_prepared(name)
        doc = frappe.get_doc("Prepared Report", name)
        if doc.report_name != report_name:
            raise frappe.PermissionError("Prepared output must belong to the requested report")


@frappe.whitelist()
def run(report_name, filters=None, user=None, ignore_prepared_report=False,
        custom_columns=None, is_tree=False, parent_field=None, are_default_filters=True):
    from frappe.desk.query_report import run as original
    if restricted():
        check_request(report_name, filters, user)
    return original(report_name, filters, user, ignore_prepared_report,
                    custom_columns, is_tree, parent_field, are_default_filters)


@frappe.whitelist()
def export_query():
    from frappe.desk.query_report import export_query as original
    if restricted():
        check_request(frappe.form_dict.get("report_name"), frappe.form_dict.get("filters"))
    return original()


@frappe.whitelist()
def get_data_for_custom_field(doctype, field, names=None):
    from frappe.desk.query_report import get_data_for_custom_field as original
    if restricted() and doctype in TARGETS:
        raise frappe.PermissionError("Custom report field lookups for this DocType are not reviewed")
    return original(doctype, field, names)
