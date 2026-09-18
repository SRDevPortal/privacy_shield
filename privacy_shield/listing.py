"""Bounded list/value adapters for the development pilot.

Only explicit column names are accepted under the gate. SQL expressions, joins and
aggregates need dedicated reviewed adapters; aliases must not evade projection.
"""
import json
import re
from copy import deepcopy
import frappe
from frappe.utils import cint
from privacy_shield.desk import enabled
from privacy_shield.policy import current_capabilities
from privacy_shield.registry import DISPLAY_FIELDS, EXTRA_SENSITIVE_FIELDS
from privacy_shield.masking import mask_number


def columns(doctype, fields):
    if isinstance(fields, str):
        try: fields = json.loads(fields)
        except ValueError: fields = [fields]
    fields = fields or ["name"]
    if not isinstance(fields, (list, tuple)) or not fields or len(fields) > 100:
        raise frappe.ValidationError("Use an explicit list of up to 100 columns")
    reverse = {target: source for source, target in DISPLAY_FIELDS[doctype].items()}
    requested, physical = [], []
    for field in fields:
        if not isinstance(field, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", field):
            raise frappe.ValidationError("Privacy pilot requires plain field names; aliases and SQL expressions are unsupported")
        requested.append(field)
        physical.append(reverse.get(field, field))
    return requested, physical


def project_rows(doctype, rows, requested, physical, full=False, as_dict=True):
    mapping = DISPLAY_FIELDS[doctype]
    aliases = EXTRA_SENSITIVE_FIELDS.get(doctype, ())
    output = []
    for row in rows:
        result = {} if as_dict else []
        for request, source in zip(requested, physical):
            if source not in row:
                if not as_dict: result.append(None)
                continue  # retain positional shape after field permission removal
            value = row[source]
            key = request
            if request in mapping.values() or (not full and source in mapping):
                value = mask_number(value)
                key = mapping.get(source, request)
            elif not full and source in aliases:
                if as_dict: continue
                value = None
            if as_dict: result[key] = value
            else: result.append(value)
        output.append(result)
    return output


def validate_query(doctype, filters, or_filters, group_by, order_by, full):
    sensitive = set(DISPLAY_FIELDS[doctype]) | set(DISPLAY_FIELDS[doctype].values()) | set(EXTRA_SENSITIVE_FIELDS.get(doctype, ()))
    if group_by:
        raise frappe.ValidationError("Grouped queries require a reviewed privacy adapter")
    # Reject expressions in ordering as well as selection.
    for term in (order_by or "").split(","):
        if term.strip() and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?: (?:asc|desc))?", term.strip(), re.I):
            raise frappe.ValidationError("Unsupported list ordering")
        if term.strip().split(" ")[0] in set(DISPLAY_FIELDS[doctype].values()):
            raise frappe.ValidationError("Masked fields cannot be sorted as stored columns")
    for conditions in (filters, or_filters):
        if isinstance(conditions, str): conditions = json.loads(conditions)
        if isinstance(conditions, dict): names = list(conditions)
        elif isinstance(conditions, list):
            names = []
            for item in conditions:
                if not isinstance(item, (list, tuple)) or len(item) not in (3,4):
                    raise frappe.ValidationError("Unsupported filter shape")
                if len(item) == 4 and item[0] != doctype:
                    raise frappe.ValidationError("Joined filters require a reviewed privacy adapter")
                names.append(item[-3])
        elif conditions is None: names = []
        else: raise frappe.ValidationError("Unsupported filter shape")
        for name in names:
            if not isinstance(name,str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",name):
                raise frappe.ValidationError("Unsupported filter field")
            if name in set(DISPLAY_FIELDS[doctype].values()) or (not full and name in sensitive):
                raise frappe.PermissionError("Filtering by protected numbers is unavailable in this pilot")


@frappe.whitelist()
def get_list(doctype, fields=None, filters=None, group_by=None, order_by=None,
             limit_start=None, limit_page_length=20, parent=None, debug=False,
             as_dict=True, or_filters=None):
    from frappe.client import get_list as original
    if not enabled(doctype):
        return original(doctype,fields,filters,group_by,order_by,limit_start,limit_page_length,parent,debug,as_dict,or_filters)
    capabilities = current_capabilities()
    requested, physical = columns(doctype,fields)
    validate_query(doctype,filters,or_filters,group_by,order_by,capabilities.view_full)
    limit = cint(limit_page_length)
    if not 1 <= limit <= 200:
        raise frappe.ValidationError("Privacy pilot page size must be between 1 and 200")
    rows = original(doctype,physical,filters,None,order_by,max(0,cint(limit_start)),limit,parent,False,True,or_filters)
    return project_rows(doctype,rows,requested,physical,capabilities.view_full,bool(cint(as_dict)))


@frappe.whitelist()
def get_value(doctype, fieldname, filters=None, as_dict=True, debug=False, parent=None):
    from frappe.client import get_value as original
    if not enabled(doctype):
        return original(doctype,fieldname,filters,as_dict,debug,parent)
    if isinstance(filters,str):
        try: filters = json.loads(filters)
        except ValueError: filters = {"name": filters}
        if isinstance(filters,str): filters = {"name": filters}
    rows = get_list(doctype,fieldname,filters,limit_page_length=1,parent=parent,as_dict=as_dict)
    if cint(as_dict): return rows[0] if rows else {}
    if not rows: return None
    return rows[0][0] if len(rows[0]) == 1 else rows[0]


@frappe.whitelist()
def search_widget(doctype, txt, query=None, searchfield=None, start=0, page_length=10,
                  filters=None, filter_fields=None, as_dict=False,
                  reference_doctype=None, ignore_user_permissions=False):
    from frappe.desk.search import search_widget as original
    if not enabled(doctype):
        return original(doctype,txt,query,searchfield,start,page_length,filters,filter_fields,as_dict,reference_doctype,ignore_user_permissions)
    full = current_capabilities().view_full
    if full:
        return original(doctype,txt,query,searchfield,start,page_length,filters,filter_fields,as_dict,reference_doctype,ignore_user_permissions)
    if query or (frappe.get_hooks("standard_queries") or {}).get(doctype):
        raise frappe.PermissionError("Custom link queries require a reviewed privacy adapter")
    if searchfield not in (None,"name") or filter_fields:
        raise frappe.PermissionError("Custom search fields require a reviewed privacy adapter")
    validate_query(doctype,filters,None,None,None,False)
    if not 1 <= cint(page_length) <= 200:
        raise frappe.ValidationError("Privacy pilot page size must be between 1 and 200")
    rows = original(doctype,txt,None,"name",max(0,cint(start)),cint(page_length),filters,None,False,reference_doctype,False)
    # Supplemental titles/descriptions may contain phone numbers. IDs stay intact.
    return [{"name": row[0]} for row in rows] if cint(as_dict) else [[row[0]] for row in rows]


@frappe.whitelist()
def search_link(doctype, txt, query=None, filters=None, page_length=10, searchfield=None,
                reference_doctype=None, ignore_user_permissions=False):
    from frappe.desk.search import search_link as original
    if not enabled(doctype) or current_capabilities().view_full:
        return original(doctype,txt,query,filters,page_length,searchfield,reference_doctype,ignore_user_permissions)
    rows = search_widget(doctype,txt,query,searchfield,0,page_length,filters,
                         reference_doctype=reference_doctype,ignore_user_permissions=False)
    return [{"value": row[0], "description": ""} for row in rows]


def _reportview(compressed):
    from frappe.desk import reportview
    original = reportview.get if compressed else reportview.get_list
    doctype = frappe.form_dict.get("doctype")
    if not enabled(doctype): return original()
    args = deepcopy(dict(frappe.form_dict))
    fields = args.get("fields")
    if isinstance(fields,str): fields = json.loads(fields)
    # Desk qualifies columns with its own table. Do not accept cross-table fields.
    prefix = "`tab" + doctype + "`."
    def plain(field):
        return field[len(prefix):].strip("`") if isinstance(field,str) and field.startswith(prefix) else field
    fields = [plain(field) for field in (fields or ["name"])]
    requested, physical = columns(doctype,fields)
    full = current_capabilities().view_full
    order = args.get("order_by")
    if order: order = order.replace(prefix, "").replace("`", "")
    validate_query(doctype,args.get("filters"),args.get("or_filters"),args.get("group_by"),order,full)
    limit = cint(args.get("page_length",20))
    if not 1 <= limit <= 200: raise frappe.ValidationError("Privacy pilot page size must be between 1 and 200")
    args.update(fields=physical,order_by=order,page_length=limit,debug=False)
    previous = frappe.local.form_dict
    try:
        frappe.local.form_dict = frappe._dict(args)
        result = original()
    finally:
        frappe.local.form_dict = previous
    if not compressed:
        return project_rows(doctype,result,requested,physical,full)
    if not result: return result
    result = deepcopy(result)
    keys = result["keys"]
    rows = [dict(zip(keys,row)) for row in result["values"]]
    projected = project_rows(doctype,rows,requested,physical,full)
    out_keys = list(projected[0]) if projected else []
    result["keys"] = out_keys
    result["values"] = [[row.get(key) for key in out_keys] for row in projected]
    return result


@frappe.whitelist()
def reportview_get():
    return _reportview(True)


@frappe.whitelist()
def reportview_get_list():
    return _reportview(False)
