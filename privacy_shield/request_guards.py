"""Pilot-only barrier for REST paths that bypass RPC adapters.

This is an explicit unsupported-route denial, not a REST masking adapter.
Use the framework router itself to respect decoded paths and slash behavior.
"""
import frappe
from werkzeug.exceptions import HTTPException
from privacy_shield.desk import enabled
from privacy_shield.policy import current_capabilities


def guard_rest():
    if not frappe.conf.get("privacy_shield_desk_enabled", False):
        return
    request = getattr(frappe.local, "request", None)
    if not request or not request.path.startswith("/api/"):
        return
    from frappe.api import API_URL_MAP
    try:
        endpoint, arguments = API_URL_MAP.bind_to_environ(request.environ).match()
    except HTTPException:
        return  # Preserve framework handling of missing routes and wrong verbs.
    dt = arguments.get("doctype")
    # v2 in-memory document methods use a lambda endpoint without route arguments.
    if request.path.rstrip("/") == "/api/v2/method/run_doc_method":
        document = frappe.form_dict.get("document")
        if isinstance(document, str):
            document = frappe.parse_json(document)
        dt = document.get("doctype") if isinstance(document, dict) else None
    elif getattr(endpoint, "__name__", "") == "handle_rpc_call":
        return  # Ordinary RPC continues through the existing override mechanism.
    if not (enabled(dt) or (dt == "Contact Phone" and enabled("Contact"))):
        return
    capabilities = current_capabilities()
    # Full visibility alone does not authorize writes; conservatively require both
    # capabilities on this unsupported surface. Framework permissions still apply.
    if capabilities.view_full and capabilities.edit_original:
        return
    raise frappe.PermissionError(
        "This REST route is not supported by the customer-number privacy pilot. "
        "Use the reviewed Desk/RPC actions."
    )
