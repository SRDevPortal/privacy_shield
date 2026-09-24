"""File output guards include import source references; static delivery remains separate."""
import frappe
from privacy_shield.import_access import restricted, check_import_urls


def checked_files(files):
    names = frappe.parse_json(files) if isinstance(files, str) else files
    if not isinstance(names, list) or not 1 <= len(names) <= 100 or any(not isinstance(n, str) or not n for n in names):
        raise frappe.ValidationError("Select between 1 and 100 File record IDs")
    names = list(dict.fromkeys(names))
    # One permission-aware metadata query, rather than adding checks per file.
    rows = frappe.get_list("File", filters={"name": ["in", names]},
                           fields=["name", "file_url"], limit_page_length=100)
    if {row.name for row in rows} != set(names):
        raise frappe.PermissionError("One or more selected files are not accessible")
    urls = tuple({row.file_url for row in rows if row.file_url})
    check_import_urls(urls)
    from privacy_shield.report_outputs import check_attachment_urls
    check_attachment_urls(urls)
    # Normal File authorization still runs; no content is read during preflight.
    return names


@frappe.whitelist()
def zip_files(files):
    from frappe.core.api.file import zip_files as original
    if restricted():
        files = frappe.as_json(checked_files(files))
    return original(files)


@frappe.whitelist()
def unzip_file(name):
    from frappe.core.api.file import unzip_file as original
    if restricted():
        checked_files([name])
        # Extraction deletes its source and creates new files: check the source
        # action permissions before Frappe reads the archive.
        doc = frappe.get_doc("File", name)
        doc.check_permission("write")
        doc.check_permission("delete")
    return original(name)


@frappe.whitelist()
def add_attachments(doctype, name, attachments):
    from frappe.utils.file_manager import add_attachments as original
    if restricted():
        attachments = checked_files(attachments)
        frappe.get_doc(doctype, name).check_permission("write")
    return original(doctype, name, attachments)


@frappe.whitelist(allow_guest=True)
def download_file(file_url):
    from frappe.handler import download_file as original
    if restricted():
        if not isinstance(file_url, str) or not file_url.startswith(("/files/", "/private/files/")):
            raise frappe.PermissionError("Use a local file URL for this privacy pilot")
        check_import_urls([file_url])
        from privacy_shield.report_outputs import check_attachment_urls
        check_attachment_urls([file_url])
    return original(file_url)


@frappe.whitelist()
def gst_download_file():
    """Frappe v15-compatible tax attachment download with scoped preflight."""
    from india_compliance.gst_india.doctype.gst_return_log.gst_return_log import get_file_doc

    frappe.has_permission("GST Return Log", "read", throw=True)
    args = frappe.form_dict
    file = get_file_doc(args.get("doctype"), args.get("name"), args.get("file_field"))
    if not file:
        raise frappe.DoesNotExistError("Attachment not found")
    file.check_permission("read")
    if restricted():
        checked_files([file.name])
    # v15 readers (including the existing S3 wrapper) do not accept encodings.
    # Core decodes UTF-8 text; re-encode it for the native download byte contract.
    content = file.get_content()
    frappe.response["filename"] = args.get("file_name") or file.file_name
    frappe.response["filecontent"] = content.encode("utf-8") if isinstance(content, str) else content
    frappe.response["type"] = "download"
