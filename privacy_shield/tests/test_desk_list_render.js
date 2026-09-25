const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const code = fs.readFileSync(require('node:path').join(__dirname, '../public/js/desk_privacy.js'), 'utf8');
for (const lazy of [false, true]) {
    class ListView { get_column_html() { return 'native'; } }
    const frappe = {ui: {form: {on() {}}}, views: lazy ? {} : {ListView},
        utils: {escape_html: s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')},
        require(bundle, callback) { assert.equal(bundle, 'list.bundle.js'); this.views.ListView = ListView; callback(); }};
    vm.runInNewContext(code, {frappe});
    const view = new ListView(); view.doctype = 'Patient';
    const row = {mask_mobile: '******0181'};
    const column = {df: {fieldname: 'mobile'}};
    assert.match(view.get_column_html(column, row), /\*{6}0181/);
    assert.deepEqual(row, {mask_mobile: '******0181'});
    assert.equal(view.get_column_html(column, {mobile: '2025550181', mask_mobile: '******0181'}), 'native');
    assert.equal(view.get_column_html(column, {}), 'native');
    assert.match(view.get_column_html(column, {mask_mobile: '<script>'}), /&lt;script&gt;/);
    assert.equal(view.get_column_html({df: {fieldname: 'patient_name'}}, row), 'native');
    const wrapper = ListView.prototype.get_column_html;
    vm.runInNewContext(code, {frappe});
    assert.equal(ListView.prototype.get_column_html, wrapper);
}
console.log('Desk masked-column renderer checks passed (loaded/lazy list bundle).');
