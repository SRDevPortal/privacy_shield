"""Authorized Patient-based appointment autofill at the client save boundary."""
import frappe


def prepare_reference(data, stored, capabilities):
    patient = data.get("patient", stored.get("patient"))
    if not patient or patient == stored.get("patient"):
        return data
    source = frappe.get_doc("Patient", patient)
    source.check_permission("read")
    if not stored and not capabilities.edit_original:
        # A full-view-only client may autofill these from the permitted Patient.
        # Accept only that exact source value, then let native validation resolve it.
        for target, source_field in (("mobile_number", "mobile"), ("alternate_mobile", "phone")):
            if data.get(target) not in (None, "", source.get(source_field)):
                raise frappe.PermissionError("Appointment numbers must come from the selected Patient")
            data.pop(target, None)
    # The normal appointment controller resolves blanks on creation. Changing
    # the Patient on an existing restricted form must not retain the old number.
    if stored and not capabilities.edit_original:
        data["mobile_number"] = source.get("mobile")
        data["alternate_mobile"] = source.get("phone")
        data["patient_name"] = source.get("patient_name")
    return data
