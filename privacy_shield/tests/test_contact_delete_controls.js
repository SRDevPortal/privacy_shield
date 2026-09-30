const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(require('path').join(__dirname, '../public/js/desk_privacy.js'), 'utf8');
let alerts = 0, deletes = 0;
const context = {__: s => s, setTimeout: () => {}, frappe: {show_alert: () => alerts++}};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('function privacy_contact_delete_notice')), context);
const control = {toggleClass(k,v) {this.hidden=v;}, addClass() {this.hidden=true;}, text() {return this;}, show() {return this;}};
let selected = [];
const saved = {name:'saved'}, fresh = {name:'new', __islocal:1};
const frm = {doc: {__privacy_shield:{}, phone_nos:[saved,fresh]}};
const grid = {wrapper:{find:()=>Object.create(control)}, remove_rows_button:Object.create(control), remove_all_rows_button:Object.create(control),
 refresh_remove_rows_button(){}, get_selected_children:()=>selected,
 delete_rows(){deletes++;}, delete_all_rows(){deletes++;}, remove_all(){deletes++;}};
context.privacy_contact_delete_controls(frm,grid);
for (const selection of [[saved], [saved,fresh]]) {
 selected=selection; grid.refresh_remove_rows_button(); assert(grid.remove_rows_button.hidden);
 grid.delete_rows(); assert.equal(deletes,0);
}
assert.equal(alerts,1);
grid.delete_all_rows(); grid.remove_all(); assert.equal(deletes,0);
selected=[fresh]; grid.refresh_remove_rows_button(); assert.equal(grid.remove_rows_button.hidden,false);
grid.delete_rows(); assert.equal(deletes,1);
assert(grid.remove_all_rows_button.hidden);
console.log('Saved/mixed deletion blocked; unsaved removal allowed; notice deduplicated.');
