"""Structured support address display, excluding phone-bearing rendered HTML.

Address free text is not classified/redacted here; this avoids the standard
phone/contact slots and preserves the mailing address fields for the support UI.
"""
from html import escape
import frappe

ADDRESS_FIELDS = ("address_line1", "address_line2", "city", "county", "state", "pincode", "country")


def support_address(customer):
    if "customer_primary_address" not in customer.permitted_fieldnames:
        return ""
    name = customer.get("customer_primary_address")
    if not name:
        return ""
    address = frappe.get_doc("Address", name)
    if not address.has_permission("read"):
        return ""
    allowed = set(address.permitted_fieldnames)
    return "<br>".join(escape(str(address.get(field))) for field in ADDRESS_FIELDS
                       if field in allowed and address.get(field))
