"""Keep comment creation native, then return a safe restricted-view acknowledgement."""
import frappe
from privacy_shield.import_access import TARGETS
from privacy_shield.raw_access import restricted, check


@frappe.whitelist(methods=["POST", "PUT"])
def add_comment(reference_doctype: str, reference_name: str, content: str, comment_email: str, comment_by: str):
    from frappe.desk.form.utils import add_comment as original
    check(reference_doctype)
    doc = original(reference_doctype, reference_name, content, comment_email, comment_by)
    if reference_doctype not in TARGETS or not restricted():
        return doc
    # The Desk footer needs a timeline item, but no unreviewed comment prose.
    return {
        "doctype": "Comment", "name": doc.name, "comment_type": "Comment",
        "reference_doctype": reference_doctype, "reference_name": reference_name,
        "creation": doc.creation, "modified": doc.modified,
        "comment_by": "Comment saved", "user_full_name": "Comment saved", "owner": "",
        "content": "This comment is hidden by your privacy permissions.",
    }
