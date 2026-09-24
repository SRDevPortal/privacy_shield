"""Display-only duplicate summaries; never use these values for writes/dialing."""
from privacy_shield.projections import project_numbers
from privacy_shield.registry import DISPLAY_FIELDS, EXTRA_SENSITIVE_FIELDS


def project_duplicate_rows(rows):
    mapping = DISPLAY_FIELDS["CRM Lead"]
    result = []
    for row in rows:
        projected = project_numbers(row, mapping, aliases=EXTRA_SENSITIVE_FIELDS["CRM Lead"])
        # The existing popup renders these keys as escaped text. Keep its column
        # contract while also exposing the explicit masked-display fields.
        for source, display in mapping.items():
            if source in row:
                projected[source] = projected[display]
        result.append(projected)
    return result
