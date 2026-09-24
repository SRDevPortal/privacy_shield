"""Scoped Raven preview protection; native access checks run first.

Raven formats values under user-configurable labels. Drop protected entries
rather than parsing formatted HTML back into phone values.
"""
import frappe
from privacy_shield.activation import enabled_for
from privacy_shield.policy import current_capabilities
from privacy_shield.registry import DISPLAY_FIELDS, EXTRA_SENSITIVE_FIELDS


@frappe.whitelist(methods=["GET"])
def get_preview_data(doctype, docname):
    from raven.api.document_link import get_preview_data as original
    result = original(doctype, docname)
    if not result or not enabled_for("core_document", doctype):
        return result
    if current_capabilities().view_full:
        return result
    meta = frappe.get_meta(doctype)
    protected = set(DISPLAY_FIELDS.get(doctype, ()))
    protected.update(EXTRA_SENSITIVE_FIELDS.get(doctype, ()))
    result = dict(result)
    # Remove by metadata label, including duplicate labels, conservatively.
    for fieldname in protected:
        field = meta.get_field(fieldname)
        if field:
            result.pop(field.label, None)
    if meta.get_title_field() in protected:
        result["preview_title"] = "Restricted preview"
    if meta.image_field in protected:
        result["preview_image"] = None
    return result
