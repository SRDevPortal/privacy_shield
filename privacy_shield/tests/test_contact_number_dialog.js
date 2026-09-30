const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../../sriaas_clinic/sriaas_clinic/public/js/contact_numbers.js'), 'utf8');
async function check(isNew) {
  const handlers = {}, calls = [];
  let dialog, action, reloads=0, triggers=0;
  const state = {modified:'v1', can_add:true, can_primary:true,
    rows:[{id:'opaque-row', number:'******1234', primary_mobile:true}]};
  const frappe = {
    ui:{form:{on(dt, events){handlers[dt] = {...handlers[dt], ...events};}},
      Dialog:function(config){Object.assign(this,config);dialog=this;
        this.fields_dict={existing:{$wrapper:{text(){}}}};
        this.get_primary_btn=()=>({prop(){},hide(){}});
        this.show=()=>{}; this.hide=()=>{};this.set_value=()=>{};}},
    call:async options=>{calls.push(options);return {message:options.method.endsWith('get_context') ? state : state};},
    show_alert(){},msgprint(){}
  };
  const frm={doctype:'Patient Encounter',doc:{name:'local-encounter',patient:'patient-id'},
    is_new:()=>isNew,is_dirty:()=>isNew,add_custom_button:(label,fn)=>{action=fn;},
    reload_doc:async()=>{reloads++;},trigger:async()=>{triggers++;}};
  vm.runInNewContext(source,{frappe,__:x=>x});
  handlers['Patient Encounter'].refresh(frm);
  await action();
  await dialog.primary_action({number:'9876501235',primary_mobile:'@new:0',primary_phone:'opaque-row'});
  assert.equal(calls[1].args.primary_phone,'opaque-row');
  assert.equal(calls[1].args.primary_mobile,'@new:0');
  assert.equal(calls[1].args.doctype,'Patient');
  assert.equal(calls[1].args.name,'patient-id');
  assert.equal(calls[1].args.modified,'v1');
  assert(!JSON.stringify(calls).includes('9876501234'));
  assert.equal(reloads,isNew?0:1,'Do not discard unsaved Encounter changes');
  assert.equal(triggers,isNew?1:0);
}
(async()=>{await check(true);await check(false);console.log('2 contact-dialog regressions passed');})().catch(e=>{console.error(e);process.exit(1);});
