"""Capability evaluation does not grant access to any document or action."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Capabilities:
    view_full: bool = False
    edit_original: bool = False


def evaluate(roles, rules, user=None):
    if not user or user == "Guest":
        return Capabilities()
    # Explicit administrative exception, not implicit System Manager access.
    if user == "Administrator":
        return Capabilities(True, True)
    roles = set(roles)
    matching = [r for r in rules if r.get("role") in roles]
    return Capabilities(
        any(r.get("view_full") in (1, True, "1") for r in matching),
        any(r.get("edit_original") in (1, True, "1") for r in matching),
    )


def current_capabilities(user=None):
    import frappe
    # Fresh settings read: no long-lived role/output cache that survives revocation.
    settings = frappe.get_single("SRIAAS Role Permission Settings")
    user = user or frappe.session.user
    return evaluate(frappe.get_roles(user), settings.get("privacy_number_roles") or [], user)
