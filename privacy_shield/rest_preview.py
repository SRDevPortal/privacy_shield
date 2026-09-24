"""Narrow v1 SDK preview reads routed through reviewed core RPC projections.

The original Raven SDK fetches the latest name, then reads that document.
No dependency on Raven source, headers, or browser-side secrecy.
"""
import json
import frappe


def route_preview_read(endpoint, arguments):
    from frappe.api.v1 import document_list, read_doc
    from privacy_shield.activation import CORE_DOCTYPES
    if frappe.request.method != "GET" or arguments.get("doctype") not in CORE_DOCTYPES:
        return False
    args = dict(frappe.form_dict)
    if endpoint is document_list:
        if set(args) - {"fields", "order_by", "limit", "as_dict"}:
            return False
        try:
            fields = json.loads(args.get("fields", "null"))
        except (TypeError, ValueError):
            return False
        if fields != ["name"] or args.get("order_by") != "creation desc" or str(args.get("limit")) != "1":
            return False
        if str(args.get("as_dict", "true")).lower() not in ("true", "1"):
            return False
        kind = "latest"
    elif endpoint is read_doc and not args:
        kind = "document"
    else:
        return False
    frappe.local.privacy_preview_read = (frappe.local.request, kind, arguments["doctype"], arguments.get("name"))
    frappe.form_dict.clear()
    frappe.form_dict["cmd"] = "privacy_shield.rest_preview.read"
    return True


@frappe.whitelist(methods=["GET"])
def read():
    route = getattr(frappe.local, "privacy_preview_read", None)
    if not route or route[0] is not frappe.local.request:
        raise frappe.PermissionError("Use the reviewed preview read route")
    _, kind, doctype, name = route
    if kind == "latest":
        # Only the identifier is needed; no arbitrary filters or SQL expressions.
        from frappe.client import get_list
        result = get_list(doctype, fields=["name"], order_by="creation desc", limit_page_length=1)
    else:
        from privacy_shield.desk import get
        result = get(doctype, name)
    # Keep the v1 SDK's data envelope instead of an RPC message envelope.
    frappe.response["data"] = result
