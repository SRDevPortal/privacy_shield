"""Site-scoped clinic adapter resolution. No clinic business app is imported by name."""
import frappe


def adapter():
    entries = frappe.get_hooks("privacy_shield_clinic_adapter") or []
    if isinstance(entries, str):
        entries = [entries]
    entries = list(dict.fromkeys(entries))
    if len(entries) != 1:
        raise frappe.ValidationError("Register exactly one clinic privacy adapter for this site.")
    path = entries[0]
    if not isinstance(path, str) or path.split(".", 1)[0] not in frappe.get_installed_apps():
        raise frappe.ValidationError("The clinic privacy adapter must belong to an installed app.")
    import importlib
    return importlib.import_module(path)


def endpoint(name):
    module = adapter()
    path = module.ENDPOINTS.get(name)
    if not path or path.split(".", 1)[0] != module.__name__.split(".", 1)[0]:
        raise frappe.ValidationError("The clinic privacy adapter does not provide this action.")
    return frappe.get_attr(path)


def template_path(name):
    module = adapter()
    relative = getattr(module, "TEMPLATES", {}).get(name)
    if not relative or not isinstance(relative, str) or relative.startswith("/") or ".." in relative.split("/"):
        raise frappe.ValidationError("This preview template is not available for the installed clinic.")
    return frappe.get_app_path(module.__name__.split(".", 1)[0], *relative.split("/"))


@frappe.whitelist()
def crm_get_data(doctype, filters, order_by, page_length=20, page_length_count=20,
                 column_field=None, title_field=None, columns=None, rows=None,
                 kanban_columns=None, kanban_fields=None, view=None, default_filters=None):
    return endpoint("crm_get_data")(**locals())


@frappe.whitelist()
def crm_get_notifications():
    return endpoint("crm_get_notifications")()


@frappe.whitelist()
def crm_mark_as_read(user=None, doc=None):
    return endpoint("crm_mark_as_read")(user=user, doc=doc)


@frappe.whitelist()
def get_encounter_context(patient=None):
    return endpoint("get_encounter_context")(patient=patient)
