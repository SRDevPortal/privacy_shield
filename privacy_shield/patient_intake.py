"""Patient intake copies protected numbers only from an accessible CRM Lead."""
import frappe
from privacy_shield.desk import enabled, project_document
from privacy_shield.policy import current_capabilities

SOURCE_KEY = "__privacy_source_lead"


def source_lead(name):
    if not isinstance(name, str) or not name.strip():
        raise frappe.ValidationError("Select a source CRM Lead")
    lead = frappe.get_doc("CRM Lead", name)
    lead.check_permission("read")
    return lead


def context(source=None):
    if not enabled("Patient"):
        return {"enabled": False}
    frappe.has_permission("Patient", "create", throw=True)
    caps = current_capabilities()
    result = {"enabled": True, "view_full": caps.view_full,
              "edit_original": caps.edit_original,
              "enter_new_numbers": caps.enter_new_numbers}
    if source:
        lead = source_lead(source)
        visible = project_document(lead.as_dict(), caps)
        result["source"] = lead.name
        result["mask_mobile"] = visible.get("mask_mobile")
        result["mask_phone"] = visible.get("mask_phone")
        result["defaults"] = {k: visible.get(k) for k in ("first_name", "last_name", "email")}
        result["defaults"]["sex"] = visible.get("gender")
        if lead.get("sr_source_patient"):
            patient = frappe.get_doc("Patient", lead.sr_source_patient)
            patient.check_permission("read")
            result["existing_patient"] = patient.name
    return result


def copy_source_numbers(data, source):
    frappe.has_permission("Patient", "create", throw=True)
    lead = source_lead(source)
    if lead.get("sr_source_patient"):
        raise frappe.ValidationError("This lead already has a linked Patient. Select the existing Patient.")
    if not lead.get("mobile_no"):
        raise frappe.ValidationError("The source lead has no mobile number. Ask an authorized user to complete it.")
    # Client number input must not silently replace or be replaced by a source.
    if any(data.get(k) for k in ("mobile", "phone")):
        raise frappe.ValidationError("Do not enter numbers when using a source CRM Lead")
    data["mobile"] = lead.mobile_no
    data["phone"] = lead.get("phone") or ""
    return data


def resolve_encounter(data, stored, capabilities):
    if capabilities.edit_original:
        return data
    patient_name = data.get("patient", stored.get("patient"))
    if not patient_name:
        return data
    if patient_name == stored.get("patient") and stored.get("sr_pe_mobile"):
        return data
    patient = frappe.get_doc("Patient", patient_name)
    patient.check_permission("read")
    # Re-resolve when changing patient; never retain the previous patient's number.
    data["sr_pe_mobile"] = patient.get("mobile") or ""
    return data
