"""Guard unreviewed bulk PDFs without changing upstream print generation."""
import json
import frappe
from privacy_shield.import_access import TARGETS
from privacy_shield.policy import current_capabilities


def check_bulk(doctype, name):
    if not frappe.conf.get("privacy_shield_desk_enabled", False):
        return
    targets = list(doctype) if isinstance(doctype, dict) else [doctype]
    if not any(dt in TARGETS for dt in targets):
        return
    if not current_capabilities().view_full:
        raise frappe.PermissionError("Bulk PDFs are not reviewed for restricted users; use the number summary")
    if isinstance(doctype, dict):
        documents = doctype
    else:
        try:
            names = json.loads(name) if isinstance(name, str) else name
        except (TypeError, ValueError) as exc:
            raise frappe.ValidationError("Expected a list of document names") from exc
        documents = {doctype: names}
    count = 0
    for dt, names in documents.items():
        if not isinstance(dt, str) or not isinstance(names, list) or not names:
            raise frappe.ValidationError("Expected DocTypes mapped to nonempty name lists")
        count += len(names)
        if count > 500:
            raise frappe.ValidationError("Limit bulk printing to 500 documents")
        for docname in names:
            if not isinstance(docname, str) or not docname:
                raise frappe.ValidationError("Expected document names")
            doc = frappe.get_doc(dt, docname)
            doc.check_permission("read")
            doc.check_permission("print")


@frappe.whitelist()
def download_multi_pdf(doctype, name, format=None, no_letterhead=False, letterhead=None, options=None):
    from frappe.utils.print_format import download_multi_pdf as original
    check_bulk(doctype, name)
    return original(doctype, name, format, no_letterhead, letterhead, options)


@frappe.whitelist()
def download_multi_pdf_async(doctype, name, format=None, no_letterhead=False, letterhead=None, options=None):
    from frappe.utils.print_format import download_multi_pdf_async as original
    check_bulk(doctype, name)
    return original(doctype, name, format, no_letterhead, letterhead, options)


def guard_job(method=None, kwargs=None, transaction_type=None):
    if not frappe.conf.get("privacy_shield_desk_enabled", False):
        return
    if method != "frappe.utils.print_format._download_multi_pdf":
        return
    args = kwargs or {}
    dt = args.get("doctype")
    targets = list(dt) if isinstance(dt, dict) else [dt]
    if not any(target in TARGETS for target in targets):
        return
    job = getattr(frappe.local, "job", None)
    if not job or not job.get("user") or job.user != frappe.session.user:
        raise frappe.PermissionError("Bulk printing requires the recorded job user")
    if not frappe.db.get_value("User", job.user, "enabled"):
        raise frappe.PermissionError("Bulk printing requires an enabled job user")
    check_bulk(dt, args.get("name"))
