for (const doctype of ['CRM Lead', 'Patient', 'Contact', 'Customer', 'Address', 'Patient Encounter', 'Sales Invoice', 'Clinic Appointment']) {
    frappe.ui.form.on(doctype, {
        refresh(frm) {
            const policy = frm.doc.__privacy_shield;
            if (!policy) return;
            const mapping = {
                'CRM Lead': {mobile_no: 'mask_mobile', phone: 'mask_phone'},
                'Patient': {mobile: 'mask_mobile', phone: 'mask_phone'},
                'Clinic Appointment': {mobile_number: 'mask_mobile', alternate_mobile: 'mask_alternate_mobile'},
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
            frm.__privacy_display_readonly ||= {};
            for (const field of policy.masked_display_fields || []) {
                if (frm.fields_dict[field] && !(field in frm.__privacy_display_readonly)) {
                    frm.__privacy_display_readonly[field] = frm.fields_dict[field].df.read_only;
                }
            }
            for (const [field, original] of Object.entries(frm.__privacy_display_readonly)) {
                frm.set_df_property(field, 'read_only',
                    (policy.masked_display_fields || []).includes(field) ? 1 : original);
            }
            if (doctype === 'Contact' && frm.fields_dict.phone_nos) {
                const grid = frm.fields_dict.phone_nos.grid;
                grid.update_docfield_property('phone', 'hidden', !policy.view_full);
                grid.update_docfield_property('mask_phone', 'hidden', policy.view_full);
                grid.__privacy_phone_reqd ??= grid.docfields.find(df => df.fieldname === 'phone')?.reqd;
                grid.update_docfield_property('phone', 'reqd', policy.view_full ? grid.__privacy_phone_reqd : 0);
                grid.update_docfield_property('mask_phone', 'in_list_view', 1);
                // Saved grid layouts still refer to phone. Substitute only the
                // display column; child row data keeps originals omitted.
                if (!grid.__privacy_columns_installed) {
                    const setup = grid.setup_user_defined_columns;
                    grid.setup_user_defined_columns = function () {
                        setup.call(this);
                        if (!frm.doc.__privacy_shield?.view_full) {
                            this.user_defined_columns = (this.user_defined_columns || []).map(df =>
                                df.fieldname === 'phone'
                                    ? {...this.fields_map.mask_phone, hidden: 0, in_list_view: 1, columns: df.columns}
                                    : df);
                        }
                    };
                    grid.__privacy_columns_installed = true;
                }
                if (grid.__privacy_full !== policy.view_full) {
                    grid.__privacy_full = policy.view_full;
                    grid.reset_grid();
                }
            }
        }
    });
}

// Desk's columns retain their source field names, while protected responses use
// mask_* keys. Render that separate display value without repopulating originals
// in the row object (which is also used by calling/message actions).
(() => {
    const mappings = {
        'CRM Lead': {mobile_no: 'mask_mobile', phone: 'mask_phone'},
        Patient: {mobile: 'mask_mobile', phone: 'mask_phone'},
        Contact: {mobile_no: 'mask_mobile', phone: 'mask_phone'},
        Customer: {mobile_no: 'mask_mobile'}, Address: {phone: 'mask_phone'},
        'Patient Encounter': {sr_pe_mobile: 'mask_mobile'},
        'Sales Invoice': {contact_mobile: 'mask_mobile'},
        'Clinic Appointment': {mobile_number: 'mask_mobile', alternate_mobile: 'mask_alternate_mobile'}
    };
    function install() {
        const prototype = frappe.views.ListView.prototype;
        if (prototype.__privacy_mask_columns) return;
        const original = prototype.get_column_html;
        prototype.get_column_html = function (column, doc) {
            const source = column.df?.fieldname;
            const display = mappings[this.doctype]?.[source];
            if (display && !Object.prototype.hasOwnProperty.call(doc, source)
                    && Object.prototype.hasOwnProperty.call(doc, display)) {
                return `<div class="list-row-col hidden-xs ellipsis"><span>${frappe.utils.escape_html(String(doc[display] || ''))}</span></div>`;
            }
            return original.call(this, column, doc);
        };
        prototype.__privacy_mask_columns = true;
    }
    if (frappe.views?.ListView) install();
    else frappe.require('list.bundle.js', install);
})();
