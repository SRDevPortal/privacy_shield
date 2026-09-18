"""Opt-in Desk adapters. Internal ORM values are never masked.

Coverage is intentionally explicit; this is not a generic response redactor.
"""
from copy import deepcopy
import json
import frappe
from privacy_shield.registry import DISPLAY_FIELDS, EXTRA_SENSITIVE_FIELDS
from privacy_shield.policy import current_capabilities
from privacy_shield.projections import project_numbers
from privacy_shield.guards import preserve_sources
from privacy_shield.child_rows import preserve_contact_rows

SCOPE = frozenset({"CRM Lead", "Patient", "Contact", "Customer", "Address", "Patient Encounter", "Sales Invoice"})


def enabled(doctype):
    return doctype in SCOPE and bool(frappe.conf.get("privacy_shield_desk_enabled", False))


def project_document(payload, capabilities):
    doc = deepcopy(payload)
    dt = doc.get("doctype")
    if dt not in SCOPE:
        return doc
    doc = project_numbers(doc, DISPLAY_FIELDS[dt], capabilities.view_full, EXTRA_SENSITIVE_FIELDS.get(dt, ()))
    if dt == "Contact":
        doc["phone_nos"] = [project_numbers(row, {"phone": "mask_phone"}, capabilities.view_full)
                            for row in doc.get("phone_nos", [])]
    if not capabilities.view_full:
        doc.pop("__onload", None)
    doc["__privacy_shield"] = {"view_full": capabilities.view_full, "edit_original": capabilities.edit_original}
    return doc


def prepare_payload(payload, stored, capabilities):
    from privacy_shield.lifecycle import strip_controls
    payload = strip_controls(payload)
    dt = payload["doctype"]
    if payload.get("name") != stored.get("name") or dt != stored.get("doctype"):
        raise PermissionError("Document identity mismatch")
    fields = tuple(DISPLAY_FIELDS[dt])
    result = preserve_sources(payload, stored, fields, capabilities.edit_original)
    # Normalized keys are derived by backend hooks, never editable role grants.
    result = preserve_sources(result, stored, EXTRA_SENSITIVE_FIELDS.get(dt, ()), False)
    for display in DISPLAY_FIELDS[dt].values():
        result.pop(display, None)
    result.pop("__privacy_shield", None)
    if dt == "Contact":
        if "phone_nos" not in payload:
            result["phone_nos"] = deepcopy(stored.get("phone_nos", []))
        else:
            result["phone_nos"] = preserve_contact_rows(payload["phone_nos"], stored.get("phone_nos", []), capabilities.edit_original)
        for row in result["phone_nos"]:
            row.pop("mask_phone", None)
    return result


def _prepare(doc, capabilities):
    data = json.loads(doc) if isinstance(doc, str) else deepcopy(doc)
    if not enabled(data.get("doctype")):
        return data
    from privacy_shield.lifecycle import prepare_new, strip_controls
    data = strip_controls(data)
    if data.get("__islocal") or not data.get("name"):
        return prepare_new(data, capabilities)
    stored = frappe.get_doc(data["doctype"], data["name"])
    stored.check_permission("read")
    stored.check_permission("write")
    if not data.get("modified"):
        raise frappe.TimestampMismatchError("Refresh before saving this document")
    try:
        return prepare_payload(data, stored.as_dict(), capabilities)
    except PermissionError as exc:
        raise frappe.PermissionError(str(exc)) from exc
    except ValueError as exc:
        raise frappe.ValidationError(str(exc)) from exc


def _project_response(capabilities):
    frappe.response["docs"] = [project_document(d.as_dict() if hasattr(d, "as_dict") else d, capabilities)
                               for d in frappe.response.get("docs", [])]
    if not capabilities.view_full and frappe.response.get("docinfo"):
        # Version data includes old and new original values.
        frappe.response["docinfo"]["versions"] = []
        # Support integrations copy provider replies into timeline comments.
        frappe.response["docinfo"]["comments"] = []


@frappe.whitelist()
def getdoc(doctype, name):
    from frappe.desk.form.load import getdoc as original
    result = original(doctype, name)
    if enabled(doctype):
        _project_response(current_capabilities())
    return result


@frappe.whitelist(methods=["POST", "PUT"])
def savedocs(doc, action):
    from frappe.desk.form.save import savedocs as original
    data = json.loads(doc) if isinstance(doc, str) else doc
    if not enabled(data.get("doctype")):
        return original(doc, action)
    capabilities = current_capabilities()
    data = _prepare(data, capabilities)
    result = original(frappe.as_json(data), action)
    _project_response(capabilities)
    return result


@frappe.whitelist()
def get(doctype, name=None, filters=None, parent=None):
    from frappe.client import get as original
    data = original(doctype, name, filters, parent)
    return project_document(data, current_capabilities()) if enabled(doctype) else data


@frappe.whitelist(methods=["POST", "PUT"])
def save(doc):
    from frappe.client import save as original
    data = json.loads(doc) if isinstance(doc, str) else doc
    if not enabled(data.get("doctype")):
        return original(doc)
    capabilities = current_capabilities()
    result = original(_prepare(data, capabilities))
    return project_document(result, capabilities)


@frappe.whitelist(methods=["POST", "PUT"])
def set_value(doctype, name, fieldname, value=None):
    from frappe.client import set_value as original
    if doctype == "Contact Phone" and enabled("Contact"):
        raise frappe.PermissionError("Update phone rows through their parent Contact")
    if not enabled(doctype):
        return original(doctype, name, fieldname, value)
    if isinstance(fieldname, dict):
        values = deepcopy(fieldname)
    elif value is not None:
        values = {fieldname: value}
    else:
        try:
            values = json.loads(fieldname)
        except (TypeError, ValueError):
            values = {fieldname: ""}
    if not isinstance(values, dict):
        raise frappe.ValidationError("Expected a field mapping")
    from frappe.model import default_fields, child_table_fields
    if set(values) & set(default_fields + child_table_fields):
        raise frappe.PermissionError("Cannot edit document identity fields")
    doc = frappe.get_doc(doctype, name)
    doc.check_permission("read")
    doc.check_permission("write")
    capabilities = current_capabilities()
    payload = {"doctype": doctype, "name": name, "modified": str(doc.modified), **values}
    try:
        checked = prepare_payload(payload, doc.as_dict(), capabilities)
    except PermissionError as exc:
        raise frappe.PermissionError(str(exc)) from exc
    except ValueError as exc:
        raise frappe.ValidationError(str(exc)) from exc
    # Use the same loaded document for permission, comparison and save concurrency.
    for field in values:
        if field in checked:
            doc.set(field, checked[field])
    doc.save()
    doc.apply_fieldlevel_read_permissions()
    return project_document(doc.as_dict(), capabilities)
