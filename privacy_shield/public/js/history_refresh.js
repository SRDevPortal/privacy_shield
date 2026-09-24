// No comment content is carried by this room event. Reload using viewer permissions.
(() => {
    let pending = false;
    let dirty = false;
    let latest;
    async function refresh() {
        if (pending) return;
        pending = true;
        try {
            while (dirty) {
                dirty = false;
                const event = latest;
                const frm = window.cur_frm;
                if (!frm || frm.doctype !== event.doctype || frm.docname !== event.name) continue;
                try {
                    const response = await frappe.call({
                        method: "frappe.desk.form.load.get_docinfo",
                        args: {doctype: event.doctype, name: event.name},
                    });
                    if (window.cur_frm !== frm || frm.doctype !== event.doctype || frm.docname !== event.name) continue;
                    if (response.docinfo) {
                        frappe.model.docinfo[event.doctype] ||= {};
                        frappe.model.docinfo[event.doctype][event.name] = response.docinfo;
                        if (frm.timeline) frm.timeline.refresh();
                    }
                } catch (_) {
                    // Framework handles the error; never restore stale history on denial.
                    if (window.cur_frm === frm && frm.doctype === event.doctype && frm.docname === event.name) {
                        const info = frappe.model.docinfo[event.doctype]?.[event.name];
                        if (info) {
                            for (const key of ["comments", "versions", "communications", "automated_messages", "additional_timeline_content"]) info[key] = [];
                            if (frm.timeline) frm.timeline.refresh();
                        }
                    }
                }
            }
        } finally {
            pending = false;
        }
    }
    const onHistoryChanged = (event) => {
        if (!event || typeof event.doctype !== "string" || typeof event.name !== "string") return;
        const frm = window.cur_frm;
        if (!frm || frm.doctype !== event.doctype || frm.docname !== event.name) return;
        latest = event;
        dirty = true;
        void refresh();
    };
    const register = () => frappe.realtime.on("privacy_shield_history_changed", onHistoryChanged);
    // app_include_js loads before Desk creates the socket. Register afterwards.
    if (frappe.realtime.socket) register();
    else $(document).one("app_ready", register);
})();
