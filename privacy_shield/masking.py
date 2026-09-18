"""Conservative display-only formatting, independent of Frappe and storage."""
def mask_number(value):
    text = str(value or "").strip()
    if not text:
        return ""
    # Ambiguous multi-number/text values must not reveal a misleading suffix.
    if any(c not in "0123456789 +()-" for c in text):
        return "[masked]"
    digits = "".join(c for c in text if c in "0123456789")
    if not digits or len(digits) > 15:
        return "[masked]"
    return "*" * len(digits) if len(digits) <= 4 else "*" * (len(digits) - 4) + digits[-4:]


def virtual_expression(source):
    if not source or not source.replace("_", "").isalnum():
        raise ValueError("Invalid source field")
    # RestrictedPython expression: no imports, database queries or custom globals.
    return (
        "(lambda v: '' if not v else '[masked]' if "
        "any(c not in '0123456789 +()-' for c in v) else "
        "(lambda d: '[masked]' if not d or sum(1 for c in d) > 15 else '*' * sum(1 for c in d) if sum(1 for c in d) <= 4 "
        "else '*' * (sum(1 for c in d)-4) + d[-4:])(''.join(c for c in v if c in '0123456789')))"
        f"((doc.get({source!r}) or '').strip())"
    )
