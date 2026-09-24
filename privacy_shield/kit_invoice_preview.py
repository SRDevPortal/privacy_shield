"""Development-only invoice projection. Not whitelisted or installed as a format.

Plain-text notes and terms are screened; rich HTML remains unsupported.
The renderer receives scalar dictionaries only, never Frappe documents or helpers.
"""
from decimal import Decimal, InvalidOperation
from datetime import date
from pathlib import Path
import re
from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment
import frappe
from privacy_shield.masking import mask_number


class UnsupportedInvoice(ValueError):
    pass


def text(value):
    value = str(value or "")
    # Conservative screen, not a claim to detect every number in arbitrary prose.
    if re.search(r"(?:\d[\s()+.-]*){7,}", value) or '<' in value or '>' in value:
        raise UnsupportedInvoice("Text needs content review before protected printing")
    return value


def date_value(value):
    if not value:
        return ''
    return date.fromisoformat(str(value)).isoformat()


def amount(value):
    try:
        value = Decimal(str(value if value is not None else 0))
        if not value.is_finite():
            raise InvalidOperation
        return format(value, 'f')
    except (InvalidOperation, ValueError):
        raise UnsupportedInvoice("Invalid numeric value")


def identifier(value, kind):
    value = str(value or '')
    patterns = {'invoice': r'(?:ACC-)?SINV-\d{4}-\d{5,6}(?:-\d+)?',
                'hsn': r'\d{4,8}', 'pincode': r'\d{6}',
                'gstin': r'\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]Z[A-Z0-9]'}
    return value if re.fullmatch(patterns[kind], value) else text(value)


def address_context(source):
    return dict(lines=[text(source.get(f)) for f in ('address_line1','address_line2','city','state','country') if source.get(f)],
                pincode=identifier(source.get('pincode'),'pincode'),
                phone=mask_number(source.get('phone')),
                gstin=identifier(source.get('gstin'),'gstin'))


def project(invoice, customer=None, item_groups=None, addresses=None):
    customer = customer or {}
    item_groups = item_groups or {}
    addresses = addresses or {}
    for field in ('customer_address','shipping_address_name','company_address'):
        if invoice.get(field) and field not in addresses:
            raise UnsupportedInvoice('Address must be explicitly resolved: ' + field)
    for field in ('contact_email',):
        if invoice.get(field):
            raise UnsupportedInvoice("Invoice contains unreviewed content: " + field)
    for display,link in [('address_display','customer_address'),('shipping_address','shipping_address_name')]:
        if invoice.get(display) and not invoice.get(link):
            raise UnsupportedInvoice('Unlinked formatted address needs review')
    items = []
    for row in invoice.get('items') or []:
        code = row.get('item_code')
        if code not in item_groups:
            raise UnsupportedInvoice("Item grouping must be explicitly resolved")
        items.append(dict(code=text(code), label=text(row.get('item_name') or code),
            group='Non Kit' if item_groups[code] == 'NON KIT ITEMS' else 'Kit',
            hsn=identifier(row.get('gst_hsn_code'),'hsn'), batch=text(row.get('sr_compliance_batch_no') or row.get('batch_no')),
            manufactured=date_value(row.get('sr_compliance_mfg_date')), expires=date_value(row.get('sr_compliance_expiry_date')), qty=amount(row.get('qty')),
            rate=amount(row.get('rate')), taxable=amount(row.get('net_amount')),
            total=amount(row.get('amount'))))
    if not items:
        raise UnsupportedInvoice("Invoice needs at least one item")
    taxes = [dict(label=text(row.get('description') or row.get('account_head')),
                  rate=amount(row.get('rate')), amount=amount(row.get('tax_amount')))
             for row in invoice.get('taxes') or []]
    totals = {field: amount(invoice.get(field)) for field in (
        'net_total','total_taxes_and_charges','grand_total','rounded_total',
        'rounding_adjustment','discount_amount','total_advance','write_off_amount',
        'outstanding_amount','sr_kit_total_price','sr_non_kit_total_price')}
    return dict(name=identifier(invoice.get('name'),'invoice'), company=text(invoice.get('company')),
        customer=text(invoice.get('customer_name') or invoice.get('customer')),
        date=date_value(invoice.get('posting_date')), due_date=date_value(invoice.get('due_date')),
        currency=text(invoice.get('currency')), kit_name=text(invoice.get('sr_kit_name') or 'Treatment Kit'),
        mobile=mask_number(invoice.get('contact_mobile') or customer.get('mobile_no')),
        addresses={key:address_context(value) for key,value in addresses.items()},
        company_gstin=identifier(invoice.get('company_gstin'),'gstin'),
        remarks=text(invoice.get('remarks')), terms=text(invoice.get('terms')),
        items=items,taxes=taxes,totals=totals)


def load_context(name):
    if not frappe.conf.get('privacy_shield_desk_enabled'):
        raise frappe.PermissionError('Invoice prototype requires the development privacy gate')
    doc=frappe.get_doc('Sales Invoice',name)
    doc.check_permission('read');doc.check_permission('print')
    def permitted(source, fields):
        allowed=set(source.permitted_fieldnames)
        levels=source.meta.get_permlevel_access(parenttype=source.get('parenttype'))
        allowed.update(f.fieldname for f in source.meta.get_table_fields() if (f.permlevel or 0) in levels)
        values={}
        for field in fields:
            if source.meta.has_field(field) or field=='name':
                if field not in allowed:
                    raise frappe.PermissionError('Print field access is required: '+field)
                values[field]=source.get(field)
        return values

    fields=['name','company','company_gstin','customer','customer_name','posting_date','due_date','currency',
            'contact_mobile','items','taxes','sr_kit_name','net_total','total_taxes_and_charges',
            'grand_total','rounded_total','rounding_adjustment','discount_amount','total_advance',
            'write_off_amount','outstanding_amount','sr_kit_total_price','sr_non_kit_total_price',
            'remarks','terms','customer_address','shipping_address_name','company_address',
            'address_display','shipping_address','contact_email']
    data=permitted(doc,fields)
    company=frappe.get_doc('Company',doc.company);company.check_permission('read')
    data['company']=permitted(company,['company_name']).get('company_name') or doc.company
    customer=None
    if not doc.contact_mobile and doc.customer:
        linked=frappe.get_doc('Customer',doc.customer);linked.check_permission('read')
        customer=permitted(linked,['mobile_no'])
    addresses={}
    for field in ('customer_address','shipping_address_name','company_address'):
        if doc.get(field):
            address=frappe.get_doc('Address',doc.get(field));address.check_permission('read')
            addresses[field]=permitted(address,['address_line1','address_line2','city','state','country','pincode','phone','gstin'])
    groups={}
    data['items']=[]
    for row in doc.items:
        if row.item_code not in groups:
            stored_group=permitted(row,['item_group']).get('item_group')
            if stored_group:
                groups[row.item_code]=stored_group
            else:
                item=frappe.get_doc('Item',row.item_code);item.check_permission('read')
                groups[row.item_code]=permitted(item,['item_group'])['item_group']
        data['items'].append(permitted(row,['item_code','item_name','gst_hsn_code','qty','rate','net_amount','amount',
            'batch_no','sr_compliance_batch_no','sr_compliance_mfg_date','sr_compliance_expiry_date']))
    data['taxes']=[permitted(row,['description','account_head','rate','tax_amount']) for row in doc.taxes]
    return project(data,customer,groups,addresses)


def render(context):
    template=Path(frappe.get_app_path('sriaas_clinic','print_formats','privacy_kit_invoice_preview.html')).read_text()
    env=SandboxedEnvironment(autoescape=True,undefined=StrictUndefined)
    env.globals.clear()
    return env.from_string(template).render(invoice=context)
