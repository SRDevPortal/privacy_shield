"""Reviewed link/autofill boundaries; original numbers stay on the server."""
import frappe
from privacy_shield.desk import enabled, project_document
from privacy_shield.policy import current_capabilities


@frappe.whitelist()
def validate_link(doctype, docname, fields=None):
    from frappe.client import validate_link as original
    if doctype == "Contact Phone" and enabled("Contact"):
        raise frappe.PermissionError("Read phone rows through their parent Contact")
    if not enabled(doctype) or current_capabilities().view_full:
        return original(doctype, docname, fields)
    # Preserve native existence/select checks, but never let its direct internal
    # get_value call bypass the protected listing adapter.
    result = original(doctype, docname)
    if result.get("name") and fields:
        from privacy_shield.listing import get_value
        values = get_value(doctype, frappe.parse_json(fields), filters={"name": docname})
        result.update(values or {})
    return result


@frappe.whitelist()
def get_patient_detail(patient):
    from healthcare.healthcare.doctype.patient.patient import get_patient_detail as original
    if not enabled("Patient"):
        return original(patient)
    doc = frappe.get_doc("Patient", patient)
    doc.check_permission("read")
    result = original(patient)
    return project_document({**result, "doctype": "Patient"}, current_capabilities())


def encounter_context(patient=None):
    if not enabled("Patient Encounter"):
        return {"enabled": False}
    caps = current_capabilities()
    result = {"enabled": True, "view_full": caps.view_full, "edit_original": caps.edit_original, "mask_mobile": ""}
    if patient:
        doc = frappe.get_doc("Patient", patient)
        doc.check_permission("read")
        from privacy_shield.masking import mask_number
        result["mask_mobile"] = mask_number(doc.get("mobile"))
    return result


@frappe.whitelist()
def appointment_context(patient=None):
    """Return only the display projection needed by an unsaved appointment."""
    if not enabled("Patient Appointment"):
        return {"enabled": False}
    caps = current_capabilities()
    result = {
        "enabled": True,
        "view_full": caps.view_full,
        "edit_original": caps.edit_original,
        "mask_mobile": "",
    }
    if patient and not caps.view_full:
        doc = frappe.get_doc("Patient", patient)
        doc.check_permission("read")
        from privacy_shield.masking import mask_number
        result["mask_mobile"] = mask_number(doc.get("mobile"))
    return result
