"""Replace protected comment room payloads with permission-checked refreshes."""
import frappe
from frappe.core.doctype.comment.comment import Comment
from privacy_shield.import_access import TARGETS


class PrivacyComment(Comment):
    def notify_change(self, action):
        if (not frappe.conf.get("privacy_shield_desk_enabled", False)
                or self.reference_doctype not in TARGETS):
            return super().notify_change(action)
        if not self.reference_name:
            return  # Never fall back to a site-wide notification.
        if self.comment_type not in ("Like", "Assigned", "Assignment Completed", "Comment", "Attachment", "Attachment Removed"):
            return
        # A document room contains viewers with different privacy capabilities.
        # Never send the actor's projection or original comment into that room.
        frappe.publish_realtime(
            "privacy_shield_history_changed",
            {"doctype": self.reference_doctype, "name": self.reference_name},
            doctype=self.reference_doctype,
            docname=self.reference_name,
            after_commit=True,
        )
