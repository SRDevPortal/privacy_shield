for (const doctype of ['CRM Lead', 'Patient', 'Contact', 'Customer', 'Address', 'Patient Encounter', 'Sales Invoice']) {
    frappe.ui.form.on(doctype, {
        refresh(frm) {
            const policy = frm.doc.__privacy_shield;
            if (!policy) return;
            const mapping = {
                'CRM Lead': {mobile_no: 'mask_mobile', phone: 'mask_phone'},
                'Patient': {mobile: 'mask_mobile', phone: 'mask_phone'},
                'Contact': {mobile_no: 'mask_mobile', phone: 'mask_phone'},
                'Customer': {mobile_no: 'mask_mobile'}, 'Address': {phone: 'mask_phone'},
                'Patient Encounter': {sr_pe_mobile: 'mask_mobile'},
                'Sales Invoice': {contact_mobile: 'mask_mobile'}
            }[doctype];
            frm.__privacy_original_properties ||= {};
            for (const [source, display] of Object.entries(mapping)) {
                const df = frm.fields_dict[source]?.df;
                if (!df) continue;
                const original = frm.__privacy_original_properties[source] ||= {
                    hidden: df.hidden, reqd: df.reqd, read_only: df.read_only
                };
                frm.toggle_display(source, policy.view_full && !original.hidden);
                frm.toggle_display(display, !policy.view_full);
                frm.set_df_property(source, 'reqd', policy.view_full ? original.reqd : 0);
                frm.set_df_property(source, 'read_only', policy.edit_original ? original.read_only : 1);
            }
            if (doctype === 'Contact' && frm.fields_dict.phone_nos) {
                const grid = frm.fields_dict.phone_nos.grid;
                grid.update_docfield_property('phone', 'hidden', !policy.view_full);
                grid.update_docfield_property('mask_phone', 'hidden', policy.view_full);
                if (!policy.view_full) grid.update_docfield_property('phone', 'reqd', 0);
            }
        }
    });
}
