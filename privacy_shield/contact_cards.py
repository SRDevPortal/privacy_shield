"""Protected native Patient/Customer cards from permission-filtered onload lists."""
from copy import deepcopy
from privacy_shield.masking import mask_number
from privacy_shield.display_text import PHONE_TEXT

ADDRESS_FIELDS = ("name", "address_title", "address_type", "is_primary_address", "is_shipping_address", "disabled", "address_line1", "address_line2", "city", "county", "state", "pincode", "country", "email_id", "fax", "gstin", "gst_state", "gst_state_number", "tax_category")
CONTACT_FIELDS = ("name", "first_name", "last_name", "is_primary_contact", "is_billing_contact", "designation", "email_id", "address")


def scrub_known(value, numbers):
    if not isinstance(value, str):
        return value
    digits = {"".join(c for c in str(n) if c.isdigit()) for n in numbers if n}
    return PHONE_TEXT.sub(lambda m: mask_number(m.group()) if "".join(c for c in m.group() if c.isdigit()) in digits else m.group(), value)


def project_cards(onload):
    # Never pass through other unreviewed onload content or provider aliases.
    if not isinstance(onload, dict):
        return {}
    result = {}
    if "addr_list" in onload:
        from frappe.contacts.doctype.address.address import render_address
        result["addr_list"] = []
        for row in onload.get("addr_list") or []:
            numbers = [row.get("phone")]
            card = {k: scrub_known(deepcopy(row[k]), numbers) if k != "name" else row[k]
                    for k in ADDRESS_FIELDS if k in row}
            card["phone"] = mask_number(row.get("phone"))
            # Re-render from protected structured data, never forward raw HTML.
            card["display"] = render_address(card)
            result["addr_list"].append(card)
    if "contact_list" in onload:
        result["contact_list"] = []
        for row in onload.get("contact_list") or []:
            numbers = [row.get("phone"), row.get("mobile_no")] + [r.get("phone") for r in row.get("phone_nos") or []]
            card = {k: scrub_known(deepcopy(row[k]), numbers) if k != "name" else row[k]
                    for k in CONTACT_FIELDS if k in row}
            card.update(phone=mask_number(row.get("phone")), mobile_no=mask_number(row.get("mobile_no")),
                        phone_nos=[{"phone": mask_number(r.get("phone"))} for r in row.get("phone_nos") or []],
                        email_ids=[{"email_id": r.get("email_id")} for r in row.get("email_ids") or []])
            result["contact_list"].append(card)
    return result
