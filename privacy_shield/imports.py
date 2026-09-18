"""Pilot restrictions for standard Data Import; not a masked import workflow."""
import frappe
from frappe.core.doctype.data_import.data_import import DataImport
from privacy_shield.desk import enabled
from privacy_shield.policy import current_capabilities

PREFIX = "frappe.core.doctype.data_import.data_import."


def scoped(doctype):
    return enabled(doctype) or (doctype == "Contact Phone" and enabled("Contact"))


def check_target(doctype, write=False):
    if not scoped(doctype):
        return
    caps = current_capabilities()
    if not caps.view_full or (write and not caps.edit_original):
        raise frappe.PermissionError(
            "This import operation is not supported for your number-privacy permissions."
        )


class PrivacyDataImport(DataImport):
    def validate(self):
        check_target(self.reference_doctype, write=True)
        validate_source(self)
        return super().validate()

    def get_importer(self):
        check_target(self.reference_doctype)
        return super().get_importer()

    def start_import(self):
        check_target(self.reference_doctype, write=True)
        validate_source(self)
        return super().start_import()


def guard_job(method=None, kwargs=None, transaction_type=None):
    if not frappe.conf.get("privacy_shield_desk_enabled", False):
        return
    if method != PREFIX + "start_import":
        return
    doc = frappe.get_doc("Data Import", (kwargs or {}).get("data_import"))
    if not scoped(doc.reference_doctype):
        return
    # execute_job restores the queued user before invoking this hook. A job with
    # no recorded actor must not inherit the worker's Administrator identity.
    job = getattr(frappe.local, "job", None)
    if not job or not job.get("user") or job.user != frappe.session.user:
        raise frappe.PermissionError("A scoped import requires a recorded job user")
    validate_source(doc)
    doc.check_permission("write")
    check_target(doc.reference_doctype, write=True)


def checked_import(name):
    doc = frappe.get_doc("Data Import", name)
    doc.check_permission("read")
    check_target(doc.reference_doctype)
    return doc


@frappe.whitelist()
def get_import_logs(data_import):
    from frappe.core.doctype.data_import.data_import import get_import_logs as original
    if frappe.conf.get("privacy_shield_desk_enabled", False):
        checked_import(data_import)
    return original(data_import)


@frappe.whitelist()
def download_template(doctype, export_fields=None, export_records=None, export_filters=None, file_type="CSV"):
    from frappe.core.doctype.data_import.data_import import download_template as original
    check_target(doctype)
    return original(doctype, export_fields, export_records, export_filters, file_type)


def validate_source(doc):
    if scoped(doc.reference_doctype):
        source = doc.get("import_file")
        if isinstance(source, str) and source and not source.startswith("/private/files/"):
            raise frappe.ValidationError("Protected imports require a private local source file.")
