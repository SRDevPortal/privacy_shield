"""Limited reviewed outputs. Arbitrary templates/child exports are not sanitized.

Restricted export: explicit record ID and mapped number columns, bounded pages.
Restricted print: explicitly selected Number Summary, no Jinja or linked lookups.
"""
import csv
import io
import json
from html import escape
import frappe
from frappe.utils import cint
from privacy_shield.desk import enabled
from privacy_shield.raw_access import check as check_raw
from privacy_shield.policy import current_capabilities
from privacy_shield.registry import DISPLAY_FIELDS
from privacy_shield.listing import columns, validate_query, project_rows
from privacy_shield.masking import mask_number

FORMAT = "Privacy Shield Number Summary"
MAX_EXPORT = 500


def safe_cell(value):
    text = "" if value is None else str(value)
    # Defend downloaded spreadsheets against formula interpretation.
    return "'"+text if text.lstrip().startswith(("=","+","-","@")) or text.startswith(("\t","\r")) else text


def export_table(doctype, fields, filters=None):
    requested,physical=columns(doctype,fields)
    allowed={"name"} | set(DISPLAY_FIELDS[doctype]) | set(DISPLAY_FIELDS[doctype].values())
    if any(field not in allowed for field in requested):
        raise frappe.PermissionError("This privacy export supports record ID and phone/mobile columns only")
    validate_query(doctype,filters,None,None,"name asc",False)
    # Keep export permission independent of number visibility; support owner-only grants.
    all_records=frappe.permissions.can_export(doctype)
    if not all_records and not frappe.permissions.can_export(doctype,is_owner=True):
        raise frappe.PermissionError("Export permission is required")
    queried=list(dict.fromkeys(physical+["owner"]))
    rows=frappe.get_list(doctype,fields=queried,filters=filters,order_by="name asc",limit_page_length=MAX_EXPORT+1)
    if len(rows)>MAX_EXPORT:
        raise frappe.ValidationError("Filter the export to 500 records or fewer")
    if not all_records and any(row.get("owner")!=frappe.session.user for row in rows):
        raise frappe.PermissionError("Only your own records can be exported")
    projected=project_rows(doctype,rows,requested,physical,False)
    headers=list(dict.fromkeys(DISPLAY_FIELDS[doctype].get(field,field) for field in requested))
    return [headers]+[[safe_cell(row.get(field)) for field in headers] for row in projected]


def write_export(doctype, fields, filters, file_type):
    if file_type not in ("CSV","Excel"):
        raise frappe.ValidationError("Use CSV or Excel")
    table=export_table(doctype,fields,filters)
    if file_type=="CSV":
        buffer=io.StringIO(newline="")
        csv.writer(buffer).writerows(table)
        content=buffer.getvalue().encode("utf-8-sig");extension="csv"
    else:
        from openpyxl import Workbook
        workbook=Workbook(write_only=True)
        sheet=workbook.create_sheet("Masked Numbers")
        for row in table: sheet.append(row)
        buffer=io.BytesIO();workbook.save(buffer);workbook.close()
        content=buffer.getvalue();extension="xlsx"
    frappe.response.update(filename="masked_numbers."+extension,filecontent=content,type="download")


@frappe.whitelist()
def export_numbers(doctype,fields=None,filters=None,file_type="CSV"):
    if not enabled(doctype):
        raise frappe.ValidationError("The privacy output pilot is not enabled for this DocType")
    if frappe.session.user=="Guest": raise frappe.PermissionError("Authentication required")
    fields=fields or ["name",*DISPLAY_FIELDS[doctype].values()]
    return write_export(doctype,fields,frappe.parse_json(filters) if isinstance(filters,str) else filters,file_type)


@frappe.whitelist()
def export_data(doctype=None,parent_doctype=None,all_doctypes=True,with_data=False,
                select_columns=None,file_type="CSV",template=False,filters=None,export_without_column_meta=False):
    from frappe.core.doctype.data_export.exporter import export_data as original
    target=doctype[0] if isinstance(doctype,list) and doctype else doctype
    target=target or parent_doctype
    for raw_target in (doctype if isinstance(doctype, list) else [target]):
        check_raw(raw_target)
    if not enabled(target) or current_capabilities().view_full:
        return original(doctype,parent_doctype,all_doctypes,with_data,select_columns,file_type,template,filters,export_without_column_meta)
    # Import templates require their own treatment; masked values must not be imported.
    if isinstance(doctype,list) or parent_doctype not in (None,"",target) or template not in (False,0,"0","false",None):
        raise frappe.PermissionError("Use the reviewed number export; import templates and child exports are not supported")
    if not cint(with_data):
        raise frappe.PermissionError("Use the reviewed number export with data; template-only output is not supported")
    selection=frappe.parse_json(select_columns) if isinstance(select_columns,str) else select_columns
    if not isinstance(selection,dict) or set(selection)!={target}:
        raise frappe.PermissionError("Select only this document's ID and number columns")
    return write_export(target,selection[target],frappe.parse_json(filters) if isinstance(filters,str) else filters,file_type)


@frappe.whitelist()
def export_query():
    from frappe.desk.reportview import export_query as original
    dt=frappe.form_dict.get("doctype")
    check_raw(dt)
    if not enabled(dt) or current_capabilities().view_full: return original()
    # Avoid dropping selected-item, join, grouping or report-specific semantics.
    supported={"cmd","doctype","fields","filters","file_format_type","title","csrf_token"}
    if any(value not in (None,"",False) and key not in supported for key,value in frappe.form_dict.items()):
        raise frappe.PermissionError("Use the reviewed number export for restricted downloads")
    return write_export(dt,frappe.parse_json(frappe.form_dict.get("fields")),
        frappe.parse_json(frappe.form_dict.get("filters")),frappe.form_dict.get("file_format_type","CSV"))


def summary_html(doctype,name):
    doc=frappe.get_doc(doctype,name)
    doc.check_permission("read");doc.check_permission("print")
    rows=[]
    for source,target in DISPLAY_FIELDS[doctype].items():
        if source not in doc.permitted_fieldnames: continue
        label="Mobile" if target=="mask_mobile" else "Phone"
        rows.append("<tr><th>"+label+"</th><td>"+escape(mask_number(doc.get(source)))+"</td></tr>")
    # No display names, addresses, letterheads, free text, child rows or linked lookups.
    return '<!doctype html><html><head><meta charset="utf-8"></head><body><h1>Masked number summary</h1><p>'+escape(doctype)+" / "+escape(str(doc.name))+"</p><table>"+"".join(rows)+"</table></body></html>"


@frappe.whitelist()
def download_pdf(doctype,name,format=None,doc=None,no_letterhead=0,language=None,letterhead=None,pdf_generator=None):
    from frappe.utils.print_format import download_pdf as original
    check_raw(doctype)
    if not enabled(doctype) or current_capabilities().view_full:
        return original(doctype,name,format,doc,no_letterhead,language,letterhead,pdf_generator)
    if format!=FORMAT or doc or letterhead:
        raise frappe.PermissionError("Choose Privacy Shield Number Summary; other print formats are not reviewed")
    from frappe.utils.pdf import get_pdf
    html=summary_html(doctype,name)
    frappe.response.update(filename="masked_number_summary.pdf",filecontent=get_pdf(html),type="pdf")


@frappe.whitelist()
def get_html_and_style(doc,name=None,print_format=None,no_letterhead=None,letterhead=None,trigger_print=False,style=None,settings=None):
    from frappe.www.printview import get_html_and_style as original
    dt=doc if name is not None else (frappe.parse_json(doc) or {}).get("doctype")
    check_raw(dt)
    if not enabled(dt) or current_capabilities().view_full:
        return original(doc,name,print_format,no_letterhead,letterhead,trigger_print,style,settings)
    if not name or print_format!=FORMAT or letterhead:
        raise frappe.PermissionError("Choose Privacy Shield Number Summary for an existing document")
    return {"html":summary_html(dt,name),"style":"table{border-collapse:collapse}th,td{padding:8px;text-align:left}"}


def guard_printview():
    # /printview bypasses RPC overrides and can render templates with linked lookups.
    request=getattr(frappe.local,"request",None)
    if not request or request.path.rstrip("/")!="/printview": return
    dt=frappe.form_dict.get("doctype")
    check_raw(dt)
    if enabled(dt) and not current_capabilities().view_full:
        raise frappe.PermissionError("Use the reviewed Privacy Shield Number Summary API for this pilot")
