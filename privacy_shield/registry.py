"""Explicit customer-number sources; never infer sensitive fields by substring."""
DISPLAY_FIELDS = {
    "CRM Lead": {"mobile_no": "mask_mobile", "phone": "mask_phone"},
    "Patient": {"mobile": "mask_mobile", "phone": "mask_phone"},
    "Contact": {"mobile_no": "mask_mobile", "phone": "mask_phone"},
    "Contact Phone": {"phone": "mask_phone"},
    "Patient Encounter": {"sr_pe_mobile": "mask_mobile"},
    "Sales Invoice": {"contact_mobile": "mask_mobile"},
    "Customer": {"mobile_no": "mask_mobile"},
    "Address": {"phone": "mask_phone"},
    "Chat Contact": {"phone_number": "mask_mobile"},
    "Vobiz Call Log": {"customer_number": "mask_mobile"},
}
EXTRA_SENSITIVE_FIELDS = {
    "Patient Encounter": ("sr_pe_mobile_norm", "pe_latest_support_response", "pe_latest_support_stage", "pe_latest_support_issue_type"),
    "Sales Invoice": ("si_latest_support_response", "si_latest_support_stage", "si_latest_support_issue_type"),
    "CRM Lead": ("sr_mobile_norm", "vobiz_mobile_last10", "vobiz_phone_last10"),
    "Voice AI Encounter Queue": ("customer_phone",),
    "Vobiz Blocked Number": ("phone_number", "normalized_phone_number", "name"),
    "Chat Contact": ("name",),
}
