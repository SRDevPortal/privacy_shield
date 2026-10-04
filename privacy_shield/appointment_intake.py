"""Server-owned number resolution for standard Healthcare appointments."""
from copy import deepcopy

import frappe


def resolve_new(data):
    """Ignore client autofill and copy the current Patient mobile after access checks."""
    result = deepcopy(data)
    patient = result.get("patient")
    if not patient:
        result.pop("apt_mobile_number", None)
        return result

    doc = frappe.get_doc("Patient", patient)
    doc.check_permission("read")
    mobile = doc.get("mobile")
    if mobile:
        result["apt_mobile_number"] = mobile
    else:
        result.pop("apt_mobile_number", None)
    return result
