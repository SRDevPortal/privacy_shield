"""Save-boundary primitive; callers must pass the original submitted mapping.

Not a document hook: Frappe fills omitted fields with None during construction,
so absence must be captured before constructing the document. No service bypass
is inferred from client flags or ignore_permissions.
"""
from copy import deepcopy


def preserve_sources(submitted, stored, fields, can_edit=False):
    result = deepcopy(submitted)
    for field in fields:
        if field not in submitted:
            if field in stored:
                result[field] = stored[field]
            continue
        value = submitted[field]
        if isinstance(value, str) and ("*" in value or value == "[masked]"):
            raise ValueError("Masked text cannot be saved as an original number")
        if not can_edit and value != stored.get(field):
            raise PermissionError("Original number changes are not permitted")
    return result
