"""Idempotent display-only installation; does not activate enforcement."""
from privacy_shield.masking import virtual_expression
from privacy_shield.registry import DISPLAY_FIELDS


def build_fields():
    import frappe
    fields = {}
    # Preflight everything before any schema change. Never overwrite foreign fields.
    for doctype, mapping in DISPLAY_FIELDS.items():
        if not frappe.db.exists("DocType", doctype):
            continue
        meta = frappe.get_meta(doctype, cached=False)
        for source, target in mapping.items():
            if not meta.has_field(source):
                frappe.throw(f"Privacy Shield source missing: {doctype}.{source}")
            existing = meta.get_field(target)
            if existing:
                owner = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": target}, "module")
                if owner != "Privacy Shield" or not existing.is_virtual:
                    frappe.throw(f"Privacy Shield field conflict: {doctype}.{target}")
            fields.setdefault(doctype, []).append(dict(
                fieldname=target, label={"mask_mobile": "Masked Mobile", "mask_phone": "Masked Phone",
                                         "mask_alternate_mobile": "Masked Alternate Mobile"}[target],
                fieldtype="Data", insert_after=source, read_only=1, is_virtual=1,
                options=virtual_expression(source), module="Privacy Shield",
                no_copy=1, hidden=1, in_list_view=0, allow_on_submit=1,
                permlevel=meta.get_field(source).permlevel or 0,
                description="Number visibility is controlled by your assigned roles.",
            ))
    return fields


def before_install():
    import frappe
    if not frappe.get_meta("SRIAAS Role Permission Settings").has_field("privacy_number_roles"):
        frappe.throw("Sync the customer-number role schema before installing Privacy Shield.")
    build_fields()


def sync_fields():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
    create_custom_fields(build_fields())
