"""Capability evaluation does not grant access to any document or action."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Capabilities:
    view_full: bool = False
    edit_original: bool = False
    enter_new_numbers: bool = False
    add_contact_numbers: bool = False
    change_primary_number: bool = False
    bypass_privacy: bool = False


def evaluate(roles, rules, user=None):
    if not user or user == "Guest":
        return Capabilities()
    # Explicit administrative exception, not implicit System Manager access.
    if user == "Administrator":
        return Capabilities(True, True, True, True, True, True)
    roles = set(roles)
    matching = [r for r in rules if r.get("role") in roles]
    return Capabilities(
        # Only users with a listed effective role are subject to number masking.
        not matching or any(r.get("view_full") in (1, True, "1") for r in matching),
        any(r.get("edit_original") in (1, True, "1") for r in matching),
        any(r.get("enter_new_numbers") in (1, True, "1") for r in matching),
        any(r.get("add_contact_numbers") in (1, True, "1") for r in matching),
        any(r.get("change_primary_number") in (1, True, "1") for r in matching),
    )


def current_capabilities(user=None):
    import frappe
    # Frappe materializes Role Profile roles on User; use the native effective roles.
    # Profile edits take effect after Frappe propagates them to its users.
    # Fresh settings read: no long-lived role/output cache that survives revocation.
    user = user or frappe.session.user
    if user == "Administrator":
        return evaluate([], [], user)
    settings = frappe.get_single("SRIAAS Role Permission Settings")
    return evaluate(frappe.get_roles(user), settings.get("privacy_number_roles") or [], user)
