"""Explicit contact mutations; never return stored original numbers."""
import re
import frappe
from privacy_shield.policy import current_capabilities
from privacy_shield.masking import mask_number


def normalize(value):
    if not isinstance(value, str) or not re.fullmatch(r"[+0-9 ()-]+", value.strip()):
        raise frappe.ValidationError("Enter a valid customer-provided number")
    digits = re.sub(r"[^0-9]", "", value)
    # Match the clinic's existing ten-digit Patient normalization.
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) != 10:
        raise frappe.ValidationError("Enter a ten-digit number, optionally prefixed with +91")
    return digits


def plan_rows(rows, additions, primary_mobile, primary_phone, caps):
    """Pure preflight. Existing rows and originals cannot be replaced/deleted."""
    # Form-encoded RPC converts JavaScript null to an empty string.
    primary_mobile = None if primary_mobile == "" else primary_mobile
    primary_phone = None if primary_phone == "" else primary_phone
    if not isinstance(additions, list) or len(additions) > 5:
        raise frappe.ValidationError("Add at most five numbers at a time")
    if additions and not caps.add_contact_numbers:
        raise frappe.PermissionError("Add Contact Numbers permission is required")
    if (primary_mobile is not None or primary_phone is not None) and not caps.change_primary_number:
        raise frappe.PermissionError("Change Primary Number permission is required")
    result = [dict(row) for row in rows]
    seen = {re.sub(r"[^0-9]", "", row["phone"])[-10:] for row in result if row.get("phone")}
    for i, value in enumerate(additions):
        value = normalize(value)
        if value in seen:
            raise frappe.ValidationError("This number is already listed; choose its masked row")
        seen.add(value)
        result.append({"name": "@new:" + str(i), "phone": value,
                       "is_primary_mobile_no": 0, "is_primary_phone": 0})
    for selected, field in [(primary_mobile, "is_primary_mobile_no"), (primary_phone, "is_primary_phone")]:
        if selected is None:
            continue
        if not selected or selected not in {row["name"] for row in result}:
            raise frappe.ValidationError("Select a number belonging to this Contact")
        for row in result:
            row[field] = int(row["name"] == selected)
    for row in result[len(rows):]:
        if not getattr(caps, "bypass_privacy", False) and row.get("is_primary_mobile_no") and row.get("is_primary_phone"):
            raise frappe.ValidationError("Choose Primary Mobile or Primary Phone for a new number, not both")
    return result


def _require_access(doc, permission):
    # Permission probes must not queue a Desk error when context catches denial.
    if not frappe.has_permission(doc.doctype, permission, doc=doc, throw=False):
        raise frappe.PermissionError("Contact number access is not permitted")


def load_contact(doctype, name, write=False):
    if doctype not in ("Patient", "Contact"):
        raise frappe.PermissionError("Use Patient or Contact")
    source = frappe.get_doc(doctype, name)
    _require_access(source, "read")
    if write:
        _require_access(source, "write")
    if doctype == "Patient":
        from frappe.contacts.doctype.contact.contact import get_default_contact
        contact = get_default_contact("Patient", name)
        if not contact:
            raise frappe.ValidationError("Create a linked Contact before managing numbers")
        source = frappe.get_doc("Contact", contact)
        _require_access(source, "read")
        if write:
            _require_access(source, "write")
    if write:
        # Native Contact hooks may synchronize each linked Patient.
        for link in source.links:
            if link.link_doctype == "Patient":
                patient = frappe.get_doc("Patient", link.link_name)
                _require_access(patient, "read")
                _require_access(patient, "write")
    return source


def describe(doc):
    caps = current_capabilities()
    return {"contact": doc.name, "modified": str(doc.modified),
            "can_add": caps.add_contact_numbers, "can_primary": caps.change_primary_number,
            "bypass_privacy": getattr(caps, "bypass_privacy", False),
            "rows": [{"id": row.name, "number": row.phone if getattr(caps, "bypass_privacy", False) else mask_number(row.phone),
                      "primary_mobile": bool(row.is_primary_mobile_no),
                      "primary_phone": bool(row.is_primary_phone)} for row in doc.phone_nos]}


def context(doctype, name):
    state = describe(load_contact(doctype, name))
    # UI capabilities intersect privacy grants with normal record permissions.
    # The mutation endpoint independently repeats these checks on every save.
    try:
        load_contact(doctype, name, write=True)
    except frappe.PermissionError:
        state["can_add"] = False
        state["can_primary"] = False
    return state


def update(doctype, name, modified, additions=None, primary_mobile=None, primary_phone=None):
    doc = load_contact(doctype, name, write=True)
    if str(doc.modified) != str(modified):
        raise frappe.TimestampMismatchError("Contact changed. Reopen Update Contact Numbers.")
    additions = frappe.parse_json(additions) if isinstance(additions, str) else (additions or [])
    caps = current_capabilities()
    rows = plan_rows([row.as_dict() for row in doc.phone_nos], additions, primary_mobile, primary_phone, caps)
    linked = [link.link_name for link in doc.links if link.link_doctype == "Patient"]
    for row in rows[len(doc.phone_nos):]:
        number = row["phone"]
        # Generic duplicate errors never identify another person's record.
        matches = frappe.db.sql("""SELECT parent FROM `tabContact Phone`
            WHERE RIGHT(REGEXP_REPLACE(phone, '[^0-9]', ''), 10) = %s
            AND parent != %s LIMIT 1""", (number, doc.name))
        if matches:
            raise frappe.ValidationError("Number is already in use. Ask an authorized user to review.")
        matches = frappe.db.sql("""SELECT name FROM `tabPatient`
            WHERE RIGHT(REGEXP_REPLACE(mobile, '[^0-9]', ''), 10) = %s
               OR RIGHT(REGEXP_REPLACE(phone, '[^0-9]', ''), 10) = %s""", (number, number))
        if any(value[0] not in linked for value in matches):
            raise frappe.ValidationError("Number is already in use. Ask an authorized user to review.")
    for i, row in enumerate(rows):
        if i < len(doc.phone_nos):
            target = doc.phone_nos[i]
        else:
            target = doc.append("phone_nos", {"phone": row["phone"]})
        target.is_primary_mobile_no = row.get("is_primary_mobile_no", 0)
        target.is_primary_phone = row.get("is_primary_phone", 0)
    doc.save()
    # Native hooks handle linked Patient updates. Explicitly check the outcome.
    for patient_name in linked:
        patient = frappe.get_doc("Patient", patient_name)
        if patient.mobile != doc.mobile_no or patient.phone != doc.phone:
            patient.mobile = doc.mobile_no
            patient.phone = doc.phone
            patient.save()
    doc.add_comment("Info", "Contact numbers updated: %s added; primary selection %s." %
                    (len(additions), "updated" if primary_mobile is not None or primary_phone is not None else "unchanged"))
    return describe(doc)


def validate_grid_update(prepared, stored):
    """Validate inline additions/primary changes before the ordinary Contact save."""
    old = {row["name"]: row for row in stored.get("phone_nos", [])}
    rows = prepared.get("phone_nos", [])
    changed = any(row.get("name") not in old or any(
        row.get(field) != old[row["name"]].get(field)
        for field in ("phone", "is_primary_phone", "is_primary_mobile_no")) for row in rows)
    if not changed:
        return
    doc = load_contact("Contact", stored["name"], write=True)
    linked = [link.link_name for link in doc.links if link.link_doctype == "Patient"]
    # Changing links and number primaries together could change an unauthorized Patient.
    incoming_links = prepared.get("links", stored.get("links", []))
    if {(x.get("link_doctype"), x.get("link_name")) for x in incoming_links} != {
            (x.get("link_doctype"), x.get("link_name")) for x in stored.get("links", [])}:
        raise frappe.ValidationError("Save link changes separately before editing contact numbers")
    for field in ("is_primary_phone", "is_primary_mobile_no"):
        if sum(bool(row.get(field)) for row in rows) > 1:
            raise frappe.ValidationError("Select only one primary number for each type")
    seen = set()
    for row in rows:
        number = re.sub(r"[^0-9]", "", row.get("phone") or "")[-10:]
        if number and number in seen:
            raise frappe.ValidationError("This number is already listed; choose its masked row")
        seen.add(number)
        if row.get("name") in old:
            continue
        if frappe.db.sql("""SELECT name FROM `tabContact Phone`
            WHERE RIGHT(REGEXP_REPLACE(phone, '[^0-9]', ''), 10)=%s
            AND parent != %s LIMIT 1""", (number, doc.name)):
            raise frappe.ValidationError("Number is already in use. Ask an authorized user to review.")
        matches = frappe.db.sql("""SELECT name FROM `tabPatient`
            WHERE RIGHT(REGEXP_REPLACE(mobile, '[^0-9]', ''), 10)=%s
            OR RIGHT(REGEXP_REPLACE(phone, '[^0-9]', ''), 10)=%s""", (number, number))
        if any(x[0] not in linked for x in matches):
            raise frappe.ValidationError("Number is already in use. Ask an authorized user to review.")

    return True


def sync_inline_contact(doc, method=None):
    if not doc.__dict__.pop("__privacy_inline_sync", False):
        return
    # The save boundary validates the primary change; authorize affected Patients
    # again here before synchronizing. This marker never grants permissions.
    for link in doc.links:
        if link.link_doctype != "Patient":
            continue
        patient = frappe.get_doc("Patient", link.link_name)
        patient.check_permission("read")
        patient.check_permission("write")
        if patient.mobile != doc.mobile_no or patient.phone != doc.phone:
            patient.mobile = doc.mobile_no
            patient.phone = doc.phone
            patient.save()
    doc.add_comment("Info", "Contact numbers or primary selections updated through the Contact table.")
