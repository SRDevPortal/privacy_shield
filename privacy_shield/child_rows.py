"""Pure save-boundary validation for existing Contact Phone children.

Caller must authorize the parent, preserve its timestamp and save through Frappe.
Never independently save a child using a caller-supplied parent identifier.
"""
from copy import deepcopy
from privacy_shield.guards import preserve_sources


def preserve_contact_rows(submitted, stored, can_edit=False):
    if not isinstance(submitted, list):
        raise ValueError("Contact phone rows must be a list")
    originals = {row["name"]: row for row in stored}
    seen = set()
    result = []
    for row in submitted:
        if not isinstance(row, dict):
            raise ValueError("Invalid contact phone row")
        name = row.get("name")
        if not name or name not in originals or name in seen:
            raise PermissionError("New, duplicate or foreign phone rows require a separate authorized action")
        seen.add(name)
        old = originals[name]
        for key in ("parent", "parenttype", "parentfield", "doctype"):
            if key in row and row[key] != old.get(key):
                raise PermissionError("Phone row ownership cannot be changed")
        guarded = preserve_sources(row, old, ["phone"], can_edit)
        # Primary selection is part of number editing, not an unrelated form edit.
        for key in ("is_primary_phone", "is_primary_mobile_no"):
            if key in row and row[key] != old.get(key) and not can_edit:
                raise PermissionError("Primary phone selection cannot be changed")
        merged = deepcopy(old)
        merged.update(guarded)
        result.append(merged)
    if seen != set(originals):
        raise PermissionError("Phone row deletion requires a separate authorized action")
    return result
