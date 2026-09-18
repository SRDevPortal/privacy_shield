"""Reject public protected-import files before Frappe writes or moves bytes."""
import frappe
from frappe.core.doctype.file.file import File
from privacy_shield.import_access import TARGETS, protected_urls


def validate_private_source(doc):
    if not frappe.conf.get("privacy_shield_desk_enabled", False) or doc.get("is_folder"):
        return
    if doc.get("is_private"):
        return
    protected = False
    if doc.get("attached_to_doctype") == "Data Import":
        target = frappe.db.get_value("Data Import", doc.get("attached_to_name"), "reference_doctype")
        protected = target is None or target in TARGETS
    urls = [doc.get("file_url")]
    if not doc.is_new():
        urls.append(frappe.db.get_value("File", doc.name, "file_url"))
    if protected or protected_urls(urls):
        raise frappe.ValidationError("Protected import files must remain private.")


class PrivacyFile(File):
    def before_insert(self):
        validate_private_source(self)
        return super().before_insert()

    def validate(self):
        validate_private_source(self)
        return super().validate()
