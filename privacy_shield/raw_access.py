"""Pilot-only denial for unreviewed provider payload documents."""
import frappe

RAW_DOCTYPES = frozenset({
    "Shipment Tracking Sync Log", "Shipment Tracking Shipment", "Shipment Tracking Shipment Event",
    "Shipment Tracking Support Ticket", "Payment Provider Event", "Payment Intent Correction Log",
    "Payment Intent",
})


def restricted(user=None):
    if not frappe.conf.get("privacy_shield_desk_enabled", False):
        return False
    from privacy_shield.policy import current_capabilities
    return not current_capabilities(user).view_full


def check(doctype, user=None):
    if doctype in RAW_DOCTYPES and restricted(user):
        raise frappe.PermissionError("Raw provider records require full-number visibility during this pilot.")


def has_permission(doc, ptype=None, user=None, debug=False):
    # Frappe can restore a False permission through DocShare. An explicit
    # privacy denial must stop that fallback, without changing framework code.
    check(doc.doctype, user)
    return None  # Never grant access.


def query_condition(user=None):
    return "1=0" if restricted(user) else ""


def guard_request():
    if not frappe.conf.get("privacy_shield_desk_enabled", False):
        return
    # Supplement permission hooks for export/print and generic RPC paths.
    args = frappe.form_dict
    for key in ("doctype", "parent_doctype"):
        value = args.get(key)
        values = value if isinstance(value, list) else [value]
        for dt in values:
            if isinstance(dt, str):
                check(dt)
    request = getattr(frappe.local, "request", None)
    if request and request.path.startswith("/api/"):
        from frappe.api import API_URL_MAP
        from werkzeug.exceptions import HTTPException
        try:
            _, arguments = API_URL_MAP.bind_to_environ(request.environ).match()
        except HTTPException:
            return
        check(arguments.get("doctype"))
