app_name = "privacy_shield"
app_title = "Privacy Shield"
app_publisher = "SRIAAS"
app_description = "Role-aware customer phone privacy"
app_email = "webdevelopersriaas@gmail.com"
app_license = "MIT"
required_apps = ["SRDevPortal/sriaas_role_permissions"]
before_install = "privacy_shield.install.before_install"
after_install = "privacy_shield.install.sync_fields"
after_migrate = "privacy_shield.install.sync_fields"
# No global ORM, response or save hooks until integration acceptance passes.

# Installed after dedupe: route into the clinic-owned adapter, which explicitly
# delegates through dedupe's active-lead guard before calling CRM.
override_whitelisted_methods = {
    "crm.api.doc.get_data": "sriaas_clinic.api.crm_lead.privacy_views.get_data",
}

# Direct website printing bypasses whitelisted method overrides.
before_request = [
    "privacy_shield.outputs.guard_printview",
    "privacy_shield.request_guards.guard_rest",
]

# Scoped Data Import checks also cover controller-method preview/download calls.
override_doctype_class = {"Data Import": "privacy_shield.imports.PrivacyDataImport"}
before_job = ["privacy_shield.imports.guard_job"]
override_whitelisted_methods.update({
    "frappe.core.doctype.data_import.data_import.get_import_logs": "privacy_shield.imports.get_import_logs",
    "frappe.core.doctype.data_import.data_import.download_template": "privacy_shield.imports.download_template",
})

# Deny-only hooks supplement framework authorization; no original values change.
has_permission = {
    dt: "privacy_shield.import_access.has_permission"
    for dt in ("Data Import", "Data Import Log", "File")
}
permission_query_conditions = {
    "Data Import": "privacy_shield.import_access.import_condition",
    "Data Import Log": "privacy_shield.import_access.log_condition",
    "File": "privacy_shield.import_access.file_condition",
}
before_request.append("privacy_shield.import_access.guard_private_file")

# File APIs are also re-exported under the legacy DocType module path.
override_whitelisted_methods.update({
    "frappe.core.api.file.zip_files": "privacy_shield.file_outputs.zip_files",
    "frappe.core.doctype.file.file.zip_files": "privacy_shield.file_outputs.zip_files",
})

override_whitelisted_methods.update({
    "frappe.core.api.file.unzip_file": "privacy_shield.file_outputs.unzip_file",
    "frappe.core.doctype.file.file.unzip_file": "privacy_shield.file_outputs.unzip_file",
    "frappe.utils.file_manager.add_attachments": "privacy_shield.file_outputs.add_attachments",
})

override_whitelisted_methods.update({
    "download_file": "privacy_shield.file_outputs.download_file",
    "frappe.handler.download_file": "privacy_shield.file_outputs.download_file",
    "frappe.core.doctype.prepared_report.prepared_report.download_attachment": "privacy_shield.report_outputs.download_attachment",
    "frappe.core.doctype.prepared_report.prepared_report.enqueue_json_to_csv_conversion": "privacy_shield.report_outputs.enqueue_json_to_csv_conversion",
})

before_request.append("privacy_shield.report_outputs.guard_private_report_file")
before_job.append("privacy_shield.report_outputs.guard_conversion_job")

override_whitelisted_methods.update({
    "frappe.desk.query_report.run": "privacy_shield.query_outputs.run",
    "frappe.desk.query_report.export_query": "privacy_shield.query_outputs.export_query",
    "frappe.desk.query_report.get_data_for_custom_field": "privacy_shield.query_outputs.get_data_for_custom_field",
})

override_doctype_class["File"] = "privacy_shield.private_files.PrivacyFile"

# Raw provider text requires a reviewed summary instead of document access.
from privacy_shield.raw_access import RAW_DOCTYPES
has_permission.update({dt: "privacy_shield.raw_access.has_permission" for dt in RAW_DOCTYPES})
permission_query_conditions.update({dt: "privacy_shield.raw_access.query_condition" for dt in RAW_DOCTYPES})
before_request.append("privacy_shield.raw_access.guard_request")

# Linked history can contain original phone values and provider prose.
has_permission.update({dt: "privacy_shield.history_access.has_permission" for dt in ("Comment", "Version", "Communication", "Notification Log", "CRM Notification")})
permission_query_conditions.update({
    "Comment": "privacy_shield.history_access.comment_condition",
    "Version": "privacy_shield.history_access.version_condition",
    "Communication": "privacy_shield.history_access.communication_condition",
    "Notification Log": "privacy_shield.history_access.notification_condition",
    "CRM Notification": "privacy_shield.history_access.crm_notification_condition",
})
override_whitelisted_methods.update({
    "frappe.desk.form.load.get_comments": "privacy_shield.history_access.get_comments",
    "frappe.desk.form.load.get_communications": "privacy_shield.history_access.get_communications",
    "frappe.desk.form.load.get_docinfo": "privacy_shield.history_access.get_docinfo",
})

# Preserve core comment lifecycle; replace only protected room payload delivery.
override_doctype_class["Comment"] = "privacy_shield.private_comments.PrivacyComment"
app_include_js = ["/assets/privacy_shield/js/history_refresh.js"]

# Sanitize mention previews before persistence and email side effects.
doc_events = {
    "Notification Log": {"before_insert": "privacy_shield.notification_privacy.protect_notification_log"},
}
override_whitelisted_methods["frappe.desk.form.utils.add_comment"] = "privacy_shield.comment_actions.add_comment"

override_whitelisted_methods.update({
    "frappe.desk.doctype.notification_log.notification_log.get_notification_logs": "privacy_shield.notification_reads.get_notification_logs",
    "frappe.desk.doctype.notification_log.notification_log.mark_as_read": "privacy_shield.notification_reads.mark_as_read",
    "crm.api.notifications.get_notifications": "sriaas_clinic.api.crm_lead.privacy_notifications.get_notifications",
    "crm.api.notifications.mark_as_read": "sriaas_clinic.api.crm_lead.privacy_notifications.mark_as_read",
})

# Raven queries the ORM directly for label-keyed document previews.
override_whitelisted_methods["raven.api.document_link.get_preview_data"] = "privacy_shield.raven_views.get_preview_data"

# MCP Audit Log uses the RAW_DOCTYPES hooks above, regardless of source.

# This tax download endpoint accepts arbitrary source/field arguments.
override_whitelisted_methods["india_compliance.gst_india.doctype.gst_return_log.gst_return_log.download_file"] = "privacy_shield.file_outputs.gst_download_file"

# Native bulk printing bypasses the single-document PDF override.
override_whitelisted_methods.update({
    "frappe.utils.print_format.download_multi_pdf": "privacy_shield.bulk_print.download_multi_pdf",
    "frappe.utils.print_format.download_multi_pdf_async": "privacy_shield.bulk_print.download_multi_pdf_async",
})
before_job.append("privacy_shield.bulk_print.guard_job")
