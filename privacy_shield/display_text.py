"""Restricted display names: protect phone-like text without rewriting storage.

Applies only to explicit human-readable name/title fields, never IDs, clinical
notes other than the explicit CRM lead-notes field, financial values or arbitrary strings. This is not universal free-text DLP.
"""
import re
from copy import deepcopy
from privacy_shield.masking import mask_number

FIELDS = frozenset({
    'first_name', 'middle_name', 'last_name', 'lead_name', 'patient_name',
    'customer_name', 'contact_name', 'full_name', 'address_title', 'title',
    'contact_display', 'sr_lead_notes',
})  # Link identities must remain intact.
# End on a digit; do not absorb separators at the edge of a display label.
PHONE_TEXT = re.compile(r'(?<![0-9*])\+?[0-9](?:[0-9 ()+.-]*[0-9])?(?![0-9*])')


def mask_display(value):
    if not isinstance(value, str):
        return value
    def replace(match):
        token = match.group(0)
        digits = ''.join(c for c in token if c.isdigit())
        return mask_number(digits) if len(digits) >= 7 else token
    return PHONE_TEXT.sub(replace, value)


def project_display(payload):
    result = deepcopy(payload)
    for field in FIELDS.intersection(result):
        result[field] = mask_display(result[field])
    return result


def preserve_display(payload, stored, full=False):
    result = deepcopy(payload)
    for field in FIELDS:
        original = stored.get(field)
        masked = mask_display(original)
        if not full and masked != original:
            if field in result and result[field] not in (masked, original):
                raise PermissionError('A masked display field cannot be edited without full-number visibility')
            result[field] = original
        elif field in result and isinstance(result[field], str):
            # Never persist a display mask when copying or creating documents.
            if re.search(r'\*{3,}\d*|\[masked\]', result[field]) and result[field] != original:
                raise ValueError('Masked display text cannot be stored in a display field')
    return result
