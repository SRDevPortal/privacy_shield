"""Deny-only import record permissions and attached private-file barrier.

Source references and attachment aliases are checked; legacy public/static delivery
requires separate storage remediation.
"""
import frappe
from privacy_shield.desk import SCOPE
from privacy_shield.raw_access import RAW_DOCTYPES
from privacy_shield.policy import current_capabilities

TARGETS = tuple(sorted(set(SCOPE) | set(RAW_DOCTYPES) | {"Contact Phone"}))


def restricted(user=None):
    return bool(frappe.conf.get("privacy_shield_desk_enabled", False)) and not current_capabilities(user).view_full


def targets_sql():
    return ", ".join(frappe.db.escape(dt) for dt in TARGETS)


def import_condition(user=None):
    if not restricted(user):
        return ""
    return "COALESCE(`tabData Import`.`reference_doctype`, '') NOT IN (" + targets_sql() + ")"


def log_condition(user=None):
    if not restricted(user):
        return ""
    # Orphan logs have no trustworthy scope: hide them from restricted viewers.
    return ("EXISTS (SELECT 1 FROM `tabData Import` psi WHERE psi.name = "
            "`tabData Import Log`.`data_import` AND COALESCE(psi.reference_doctype, '') NOT IN ("
            + targets_sql() + "))")


def file_condition(user=None):
    if not restricted(user):
        return ""
    scope = targets_sql()
    return (
        "(NOT (`tabFile`.`attached_to_doctype` <=> 'Data Import') OR EXISTS "
        "(SELECT 1 FROM `tabData Import` psi WHERE psi.name = `tabFile`.`attached_to_name` "
        "AND COALESCE(psi.reference_doctype, '') NOT IN (" + scope + "))) "
        "AND NOT EXISTS (SELECT 1 FROM `tabData Import` src "
        "WHERE src.import_file = `tabFile`.file_url AND src.reference_doctype IN (" + scope + ")) "
        "AND NOT EXISTS (SELECT 1 FROM `tabFile` alias_file LEFT JOIN `tabData Import` imp "
        "ON imp.name=alias_file.attached_to_name WHERE alias_file.file_url=`tabFile`.file_url "
        "AND alias_file.attached_to_doctype='Data Import' "
        "AND (imp.name IS NULL OR imp.reference_doctype IN (" + scope + ")))"
    )


def protected_urls(urls):
    """Check source references and every attachment alias, without reading content."""
    urls = tuple(dict.fromkeys(url for url in urls if url))
    if not urls:
        return False
    if len(urls) > 100:
        raise frappe.ValidationError("Check at most 100 file URLs at a time")
    return bool(frappe.db.sql(
        """SELECT 1 FROM `tabData Import` src
        WHERE src.import_file IN %s AND src.reference_doctype IN %s
        UNION ALL
        SELECT 1 FROM `tabFile` f LEFT JOIN `tabData Import` di
        ON di.name=f.attached_to_name
        WHERE f.file_url IN %s AND f.attached_to_doctype='Data Import'
        AND (di.name IS NULL OR di.reference_doctype IN %s) LIMIT 1""",
        (urls, TARGETS, urls, TARGETS),
    ))


def check_import_urls(urls):
    if protected_urls(urls):
        raise frappe.PermissionError("This import source requires full-number visibility")


def has_permission(doc, ptype=None, user=None, debug=False):
    if not restricted(user):
        return None  # Never grant access; existing Frappe permissions still apply.
    if doc.doctype == "File" and protected_urls([doc.get("file_url")]):
        return False
    if doc.doctype == "Data Import":
        target = doc.get("reference_doctype")
    elif doc.doctype == "Data Import Log":
        target = frappe.db.get_value("Data Import", doc.get("data_import"), "reference_doctype") if doc.get("data_import") else None
        if target is None:
            return False
    elif doc.doctype == "File" and doc.get("attached_to_doctype") == "Data Import":
        target = frappe.db.get_value("Data Import", doc.get("attached_to_name"), "reference_doctype") if doc.get("attached_to_name") else None
        if target is None:
            return False
    else:
        return None
    return False if target in TARGETS else None


def guard_private_file():
    request = getattr(frappe.local, "request", None)
    if not request or not request.path.startswith("/private/files/") or not restricted():
        return
    check_import_urls([request.path])
