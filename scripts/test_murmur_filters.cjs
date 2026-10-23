const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/murmurs.js','utf8');
const initSource = source.slice(source.indexOf('  function initDateFilter()'), source.indexOf('  async function loadFeed('));
function setup(query='',today='2026-03-01',loggedIn=true) {
 const nodes = new Map();
 const $=id=>{if(!nodes.has(id)) nodes.set(id,{hidden:false,disabled:false,checked:false,attrs:{},events:{},_value:'',set value(value){this._value=String(value);},get value(){return this._value;},setAttribute(key,value){this.attrs[key]=value;},addEventListener(key,handler){this.events[key]=handler;},focus(){this.focused=true;}});return nodes.get(id);};
 $('mm-custom-dates').hidden=true;
 const state={profile:loggedIn?{username:'alice'}:null,page:5,post:null,view:'all'};
 const context={$,state,params:new URLSearchParams(query),chinaDay:()=>today,URL,Date,location:{href:'http://localhost/murmurs?'+query},history:{replaceState(a,b,url){context.location.href=String(url);}},loadFeed(){context.loads++;},toast(message){context.errors.push(message);},loads:0,errors:[]};
 vm.createContext(context);vm.runInContext(initSource+'\ninitDateFilter();',context);
 const change=(id,value)=>{const node=$(id);if(value!==undefined)node.value=value;node.events.change();};
 const click=id=>$(id).events.click();
 const apply=()=>$('mm-date-filter').events.submit({preventDefault(){}});
 return {context,$,state,change,click,apply};
}
for(const [days,start] of [[1,'2026-03-01'],[3,'2026-02-27'],[7,'2026-02-23'],[30,'2026-01-31']]) {
 const s=setup();assert.equal(s.$('mm-custom-dates').hidden,true);
 s.change('mm-range',days);assert.equal(s.state.dateRange.start,start);assert.equal(s.state.dateRange.end,'2026-03-01');
 assert.equal(s.state.page,1);assert.equal(s.context.loads,1);assert.equal(new URL(s.context.location.href).searchParams.get('start'),start);
}
const custom=setup();custom.change('mm-range','custom');assert.equal(custom.$('mm-custom-dates').hidden,false);assert.equal(custom.context.loads,0);
custom.$('mm-start').value='2026-02-01';custom.$('mm-end').value='2026-02-06';custom.apply();assert.equal(custom.state.dateRange.start,'2026-02-01');assert.equal(custom.$('mm-custom-dates').hidden,true);
custom.click('mm-custom-toggle');custom.$('mm-start').value='2026-01-01';custom.click('mm-custom-cancel');assert.equal(custom.state.dateRange.start,'2026-02-01');assert.equal(custom.context.loads,1);
custom.click('mm-custom-toggle');custom.$('mm-start').value='2026-03-02';custom.apply();assert.equal(custom.context.loads,1);assert.equal(custom.context.errors.length,1);
custom.$('mm-unread').checked=true;custom.change('mm-unread');assert.equal(custom.$('mm-range').disabled,true);assert.equal(custom.$('mm-custom-dates').hidden,true);assert.equal(new URL(custom.context.location.href).searchParams.get('unread'),'1');
custom.$('mm-unread').checked=false;custom.change('mm-unread');assert.equal(custom.state.dateRange.start,'2026-02-01');assert.equal(custom.$('mm-range').disabled,false);
assert.equal(setup('', '2026-03-01',false).$('mm-unread').disabled,true);
const restored=setup('start=2026-02-23&end=2026-03-01&page=3');assert.equal(restored.$('mm-range').value,'7');assert.equal(restored.$('mm-custom-dates').hidden,true);
assert.equal(setup('start=2026-01-11&end=2026-02-11').$('mm-range').value,'custom');
const leap=setup('','2024-03-01');leap.change('mm-range','3');assert.equal(leap.state.dateRange.start,'2024-02-28');
console.log('PASS: 1/3/7/30-day ranges, month/leap boundaries, custom disclosure/apply/cancel, invalid dates, unread and guest state, URL restoration');
