"""Generic pilot mention previews; original comments remain in their source records."""
import frappe
from privacy_shield.import_access import TARGETS

NOTICE = "You were mentioned in a comment. Open the record to view permitted details."


def protect_notification_log(doc, method=None):
    if (frappe.conf.get("privacy_shield_desk_enabled", False)
            and doc.get("type") == "Mention" and doc.get("document_type") in TARGETS):
        # Safe for every recipient, including after a role change. Do not embed
        # author-entered prose or a record title in stored/email previews.
        doc.subject = "You were mentioned in a comment"
        doc.email_content = NOTICE
