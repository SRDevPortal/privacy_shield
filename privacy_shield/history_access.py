"""Pilot-only barriers for unreviewed history of protected source documents."""
import frappe
from privacy_shield.import_access import TARGETS, targets_sql
from privacy_shield.raw_access import restricted, check

HISTORY_FIELDS = {"MCP Audit Log": "ref_doctype", "Comment": "reference_doctype", "Version": "ref_doctype", "Communication": "reference_doctype", "Notification Log": "document_type", "CRM Notification": "reference_doctype"}
TIMELINE_FIELDS = ("versions", "comments", "communications", "automated_messages", "additional_timeline_content")


def has_permission(doc, ptype=None, user=None, debug=False):
    field = HISTORY_FIELDS.get(doc.doctype)
    protected = bool(field and doc.get(field) in TARGETS)
    if doc.doctype == "MCP Audit Log":
        # Source labels cannot prove arbitrary payloads/error traces are safe.
        # Keep this wrapper for previously resolved hook paths as well.
        check(doc.doctype, user)
        return None
    if doc.doctype == "Communication":
        protected = protected or any(row.get("link_doctype") in TARGETS for row in (doc.get("timeline_links") or []))
    if protected and restricted(user):
        # A False result can be restored by DocShare; this is an explicit denial.
        raise frappe.PermissionError("This record history requires full-number visibility during the pilot.")
    return None


def _condition(doctype, user=None):
    if not restricted(user):
        return ""
    field = HISTORY_FIELDS[doctype]
    return f"COALESCE(`tab{doctype}`.`{field}`, '') NOT IN ({targets_sql()})"


def comment_condition(user=None):
    return _condition("Comment", user)


def version_condition(user=None):
    return _condition("Version", user)


def communication_condition(user=None):
    if not restricted(user):
        return ""
    return ("(" + _condition("Communication", user) + ") AND NOT EXISTS ("
            "SELECT 1 FROM `tabCommunication Link` ps_link "
            "WHERE ps_link.parent = `tabCommunication`.name "
            "AND ps_link.parenttype = 'Communication' "
            "AND ps_link.parentfield = 'timeline_links' "
            "AND ps_link.link_doctype IN (" + targets_sql() + "))")


def notification_condition(user=None):
    return _condition("Notification Log", user)


def mcp_audit_condition(user=None):
    from privacy_shield.raw_access import query_condition
    return query_condition(user)


def crm_notification_condition(user=None):
    return _condition("CRM Notification", user)


def scrub_docinfo(docinfo):
    for field in TIMELINE_FIELDS:
        docinfo[field] = []


def _source(doctype, name):
    check(doctype)
    frappe.get_doc(doctype, name).check_permission("read")


@frappe.whitelist()
def get_comments(doctype, name, comment_type="Comment"):
    if doctype in TARGETS and restricted():
        _source(doctype, name)
        return []
    from frappe.desk.form.load import get_comments as original
    return original(doctype, name, comment_type)


@frappe.whitelist()
def get_communications(doctype, name, start=0, limit=20):
    if doctype in TARGETS and restricted():
        _source(doctype, name)
        return []
    from frappe.desk.form.load import get_communications as original
    return original(doctype, name, start, limit)


@frappe.whitelist()
def get_docinfo(doc=None, doctype=None, name=None):
    from frappe.desk.form.load import get_docinfo as original
    if restricted():
        if doc is not None:
            raise frappe.PermissionError("Client-supplied documents are not supported for history reads during the pilot.")
        if doctype in TARGETS:
            _source(doctype, name)
            result = original(doctype=doctype, name=name)
            if frappe.response.get("docinfo"):
                scrub_docinfo(frappe.response["docinfo"])
            return result
    return original(doc=doc, doctype=doctype, name=name)
