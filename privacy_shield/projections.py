"""Explicit output projections; callers retain record and field access checks."""
from copy import deepcopy
from privacy_shield.masking import mask_number


def project_numbers(payload, mapping, view_full=False, aliases=()):
    result = deepcopy(payload)
    for source, masked in mapping.items():
        if source in result:
            result[masked] = mask_number(result[source])
            if not view_full:
                result.pop(source)
    if not view_full:
        for alias in aliases:
            result.pop(alias, None)
    return result
