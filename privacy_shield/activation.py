"""Explicit activation contract; compatibility adapters retain existing protection.

The pilot switch is not a global privacy kill switch. The two previously
installation-gated lookups remain protected independently of it. Unknown routes
and deferred records are never opted in by this policy.
"""
import frappe

CORE_DOCTYPES = frozenset({
    "CRM Lead", "Patient", "Contact", "Customer", "Address",
    "Patient Encounter", "Sales Invoice", "Clinic Appointment",
})
INSTALLATION_ADAPTERS = frozenset({
    "appointment_patient_details", "support_customer_details",
})


def enabled_for(route, doctype=None):
    if route == "core_document":
        return doctype in CORE_DOCTYPES and bool(
            frappe.conf.get("privacy_shield_desk_enabled", False)
        )
    if route in INSTALLATION_ADAPTERS and doctype is None:
        return "privacy_shield" in frappe.get_installed_apps()
    return False
