const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map();
function node(id){if(!nodes.has(id))nodes.set(id,{id,events:{},hidden:false,disabled:false,textContent:'',children:[],addEventListener(type,fn){this.events[type]=fn;},append(...children){this.children.push(...children);},replaceChildren(...children){this.children=children;},focus(){this.focused=true;},reset(){this.resets=(this.resets||0)+1;},showModal(){this.open=true;},close(){this.open=false;this.events.close?.();},elements:{current_password:{focus(){this.focused=true;}}}});return nodes.get(id);}
let ready,resolveRequest,calls=0;
const context={window:{},document:{getElementById:node,createElement:tag=>node(Symbol(tag)),querySelector:()=>null,addEventListener(type,fn){if(type==='DOMContentLoaded')ready=fn;}},URLSearchParams,location:{pathname:'/account',search:''},history:{replaceState(){}},FormData:class{constructor(){return [['current_password','test-current'],['new_password','test-new-123'],['confirm_password','test-new-123']];}},fetch:async()=>{calls++;return new Promise(resolve=>resolveRequest=resolve);}};
vm.createContext(context);vm.runInContext(fs.readFileSync('static/account-settings.js','utf8'),context);ready();
(async()=>{
 node('openPasswordChange').events.click();assert.equal(node('passwordChangeDialog').open,true);assert.equal(node('passwordChangeForm').hidden,true);assert.equal(node('submitPasswordChange').hidden,true);assert.equal(calls,0);
 node('continuePasswordChange').events.click();assert.equal(node('passwordChangeForm').hidden,false);assert.equal(node('continuePasswordChange').hidden,true);assert.equal(node('submitPasswordChange').hidden,false);assert.equal(node('passwordChangeForm').elements.current_password.focused,true);
 const pending=node('passwordChangeForm').events.submit({preventDefault(){}});assert.equal(calls,1);assert.equal(node('submitPasswordChange').disabled,true);
 await node('passwordChangeForm').events.submit({preventDefault(){}});assert.equal(calls,1);
 node('closePasswordChange').events.click();assert.equal(node('passwordChangeDialog').open,true);
 let blocked=false;node('passwordChangeDialog').events.cancel({preventDefault(){blocked=true;}});assert.equal(blocked,true);
 resolveRequest({ok:false,json:async()=>({error:'当前密码不正确'})});await pending;
 assert.equal(node('passwordChangeError').textContent,'当前密码不正确');assert.equal(node('submitPasswordChange').disabled,false);assert.equal(node('closePasswordChange').disabled,false);
 node('closePasswordChange').events.click();assert.equal(node('passwordChangeDialog').open,false);
 node('openPasswordChange').events.click();assert.equal(node('passwordChangeWarning').hidden,false);assert.equal(node('passwordChangeForm').hidden,true);
 console.log('PASS: password warning/continue/cancel, external submit state, duplicate-submit guard, pending-dismiss guard, error recovery and reopen');
})().catch(error=>{console.error(error);process.exitCode=1;});
