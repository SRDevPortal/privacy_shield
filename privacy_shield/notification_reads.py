"""Owner-scoped notification feeds with reviewed pilot responses."""
import frappe
from frappe.utils import cint
from privacy_shield.raw_access import restricted
from privacy_shield.import_access import TARGETS

NOTICE = "Notification details are hidden by your privacy permissions."


def project_log(row):
    if row.get("document_type") not in TARGETS:
        return row
    safe = {key: row.get(key) for key in ("name", "creation", "modified", "for_user", "from_user", "type", "read", "document_type", "document_name")}
    safe.update(subject=NOTICE, email_content=NOTICE)
    return frappe._dict(safe)


@frappe.whitelist()
def get_notification_logs(limit=20):
    if not restricted():
        from frappe.desk.doctype.notification_log.notification_log import get_notification_logs as original
        return original(limit)
    if not frappe.has_permission("Notification Log", "read"):
        raise frappe.PermissionError("Not permitted to read notifications.")
    # This purpose-specific feed cannot accept arbitrary filters/users/fields.
    # Generic reads remain denied; fetch only this recipient's bounded page.
    rows = frappe.get_all("Notification Log", filters={"for_user": frappe.session.user},
                          fields=["*"], limit_page_length=max(1, min(cint(limit), 100)), order_by="modified desc")
    rows = [project_log(row) for row in rows]
    user_info = frappe._dict()
    for user in set(row.from_user for row in rows if row.from_user):
        frappe.utils.add_user_info(user, user_info)
    return {"notification_logs": rows, "user_info": user_info}


@frappe.whitelist()
def mark_as_read(docname: str):
    if not restricted():
        from frappe.desk.doctype.notification_log.notification_log import mark_as_read as original
        return original(docname)
    if frappe.flags.read_only or not docname:
        return
    # No private document or arbitrary field is returned or modified.
    frappe.db.set_value("Notification Log", {"name": str(docname), "for_user": frappe.session.user}, "read", 1, update_modified=False)
