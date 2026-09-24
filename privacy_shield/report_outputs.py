"""Scoped prepared-download restrictions; not report result masking."""
import frappe
from privacy_shield.import_access import restricted, TARGETS


def check_prepared(name):
    doc = frappe.get_doc("Prepared Report", name)
    doc.check_permission("read")
    check_report(doc.report_name)


def check_report(report_name):
    seen = set()
    for _ in range(10):
        if not report_name or report_name in seen:
            raise frappe.PermissionError("Cannot verify this prepared report's privacy scope")
        seen.add(report_name)
        report = frappe.get_doc("Report", report_name)
        if report.ref_doctype in TARGETS:
            raise frappe.PermissionError("Prepared downloads for this DocType are not reviewed for the privacy pilot")
        if report.report_type != "Custom Report":
            return
        report_name = report.reference_report
    raise frappe.PermissionError("Report reference chain exceeds the reviewed limit")


@frappe.whitelist()
def download_attachment(dn):
    from frappe.core.doctype.prepared_report.prepared_report import download_attachment as original
    if restricted():
        check_prepared(dn)
    return original(dn)


@frappe.whitelist()
def enqueue_json_to_csv_conversion(prepared_report_name):
    from frappe.core.doctype.prepared_report.prepared_report import enqueue_json_to_csv_conversion as original
    if frappe.conf.get("privacy_shield_desk_enabled", False):
        check_conversion_access(prepared_report_name)
    return original(prepared_report_name)


def check_attachment_urls(urls):
    """Batch report classification; no file contents or per-file metadata queries."""
    if not urls:
        return
    rows = frappe.db.sql(
        """SELECT DISTINCT pr.name, pr.report_name FROM `tabFile` f
        LEFT JOIN `tabPrepared Report` pr ON pr.name=f.attached_to_name
        WHERE f.file_url IN %s AND f.attached_to_doctype='Prepared Report'
        LIMIT 101""", (tuple(urls),), as_dict=True,
    )
    if len(rows) > 100 or any(not row.name or not row.report_name for row in rows):
        raise frappe.PermissionError("Cannot verify prepared attachment scope")
    pending = {row.report_name for row in rows}
    seen = set()
    for _ in range(10):
        if not pending:
            return
        if pending & seen:
            raise frappe.PermissionError("Cyclic prepared report reference")
        seen.update(pending)
        reports = frappe.get_all("Report", filters={"name": ["in", list(pending)]},
            fields=["name", "ref_doctype", "report_type", "reference_report"], limit_page_length=100)
        if {r.name for r in reports} != pending:
            raise frappe.PermissionError("Missing report metadata")
        pending = set()
        for report in reports:
            if report.ref_doctype in TARGETS:
                raise frappe.PermissionError("This prepared attachment is not reviewed for the privacy pilot")
            if report.report_type == "Custom Report":
                if not report.reference_report:
                    raise frappe.PermissionError("Missing custom report reference")
                pending.add(report.reference_report)
    if pending:
        raise frappe.PermissionError("Report reference chain exceeds the reviewed limit")


def guard_private_report_file():
    request = getattr(frappe.local, "request", None)
    if request and request.path.startswith("/private/files/") and restricted():
        check_attachment_urls([request.path])


def check_conversion_access(name):
    """Number visibility never grants access to an unreadable report."""
    doc = frappe.get_doc("Prepared Report", name)
    doc.check_permission("read")
    if restricted():
        check_report(doc.report_name)


def guard_conversion_job(method=None, kwargs=None, transaction_type=None):
    if not frappe.conf.get("privacy_shield_desk_enabled", False):
        return
    if method != "frappe.core.doctype.prepared_report.prepared_report.convert_json_to_csv":
        return
    job = getattr(frappe.local, "job", None)
    if not job or not job.get("user") or job.user != frappe.session.user:
        raise frappe.PermissionError("Prepared conversion requires a recorded job user")
    if not frappe.db.get_value("User", job.user, "enabled"):
        raise frappe.PermissionError("Prepared conversion requires an enabled job user")
    check_conversion_access((kwargs or {}).get("prepared_report_name"))
