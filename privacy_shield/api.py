"""Explicit number boundary for clients; not a replacement for all Frappe APIs.

No arbitrary field/document serialization, caller-provided bypass or provider call.
Phone-derived identities and call logs require their own scoped adapters.
"""
import frappe
from frappe.utils import get_datetime
from privacy_shield.masking import mask_number
from privacy_shield.policy import current_capabilities
from privacy_shield.registry import DISPLAY_FIELDS
from privacy_shield.guards import preserve_sources

SUPPORTED = frozenset({"CRM Lead", "Patient", "Contact", "Patient Encounter",
                       "Sales Invoice", "Customer", "Address"})


def _load(doctype, name):
    if frappe.session.user == "Guest":
        raise frappe.PermissionError("Authentication required")
    if doctype not in SUPPORTED or not isinstance(name, str) or not name:
        raise frappe.ValidationError("Unsupported number source")
    doc = frappe.get_doc(doctype, name)
    doc.check_permission("read")
    return doc


def _visible_fields(doc):
    return {source: target for source, target in DISPLAY_FIELDS[doc.doctype].items()
            if source in doc.permitted_fieldnames}


def _render(doc, capabilities):
    # Build a new allowlisted response. Never mutate a loaded document or shared cache.
    numbers = []
    for source, target in _visible_fields(doc).items():
        value = doc.get(source)
        item = {"source_field": source, "display_field": target, "masked": mask_number(value)}
        if capabilities.view_full:
            item["value"] = value
        numbers.append(item)
    return {"numbers": numbers, "modified": str(doc.modified),
            "can_view_full": capabilities.view_full}


@frappe.whitelist()
def get_numbers(doctype, name):
    return _render(_load(doctype, name), current_capabilities())


@frappe.whitelist(methods=["POST"])
def update_number(doctype, name, source_field, value, modified):
    doc = _load(doctype, name)
    doc.check_permission("write")
    capabilities = current_capabilities()
    if not capabilities.edit_original:
        raise frappe.PermissionError("Number editing is not permitted")
    if source_field not in _visible_fields(doc):
        raise frappe.PermissionError("Number field is not accessible")
    df = doc.meta.get_field(source_field)
    if df.read_only or df.fetch_from or not doc.has_permlevel_access_to(source_field, permission_type="write"):
        raise frappe.PermissionError("Number field is not editable")
    if not isinstance(value, (str, type(None))):
        raise frappe.ValidationError("Number must be text or empty")
    if not modified or get_datetime(modified) != get_datetime(doc.modified):
        raise frappe.TimestampMismatchError("Document changed; refresh before editing")
    try:
        checked = preserve_sources({source_field: value}, {source_field: doc.get(source_field)},
                                   [source_field], can_edit=True)
    except ValueError as exc:
        raise frappe.ValidationError(str(exc)) from exc
    doc.set(source_field, checked[source_field])
    # Keep normal hooks, normalization, permissions and optimistic concurrency checks.
    doc.save()
    return _render(doc, capabilities)
