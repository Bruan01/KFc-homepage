const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

class Element {
  constructor(tag) { this.tagName=tag; this.nodes=[]; this.events={}; this.style={}; this.attrs={}; this.isConnected=true; }
  setAttribute(key,value) { this.attrs[key]=value; if(key==='id')this.id=value; }
  removeAttribute(key) { delete this.attrs[key]; }
  addEventListener(type,handler) { (this.events[type] ||= []).push(handler); }
  append(...nodes) { for(let node of nodes){if(node==null)continue;if(typeof node==='string')node=new Text(node);if(node.tagName==='#fragment'){this.append(...node.nodes);continue;}node.parentElement=this;this.nodes.push(node);} }
  replaceChildren(...nodes) { this.nodes=[];this.append(...nodes); }
  get children() { return this.nodes.filter(node=>node.tagName!=='#text'); }
  get textContent() { return this.nodes.map(node=>node.textContent).join(''); }
  set textContent(value) { this.replaceChildren(String(value)); }
  closest() { return ['pre','code','a'].includes(this.tagName)?this:this.parentElement?.closest() || null; }
  contains(node) { return this.nodes.includes(node); }
  after() {}
  focus() {}
  scrollIntoView() {}
}
class Text extends Element {
  constructor(value){super('#text');this.nodeValue=value;}
  get textContent(){return this.nodeValue;}
  set textContent(value){this.nodeValue=value;}
  replaceWith(fragment){const parent=this.parentElement;const i=parent.nodes.indexOf(this);parent.nodes.splice(i,1,...fragment.nodes);}
}
const document={createElement:tag=>new Element(tag),createTextNode:text=>new Text(text),createDocumentFragment:()=>new Element('#fragment'),addEventListener(){},removeEventListener(){},
  createTreeWalker(root,mask,filter){const nodes=[];function walk(node){if(node.tagName==='#text'&&filter.acceptNode(node)===1)nodes.push(node);for(const child of node.nodes)walk(child);}walk(root);let i=0;return {currentNode:null,nextNode(){this.currentNode=nodes[i++];return !!this.currentNode;}};}};
let fetchResolve,signal;
const revoked=[];
const context={window:{addEventListener(){}},document,NodeFilter:{SHOW_TEXT:4,FILTER_REJECT:2,FILTER_ACCEPT:1},URLSearchParams,Event,AbortController,
  URL:{createObjectURL:()=> 'blob:test-picture',revokeObjectURL:url=>revoked.push(url)},FormData:class{append(){}},alert:message=>{throw new Error(message);},
  fetch:async(url,options)=>{signal=options.signal;return new Promise(resolve=>fetchResolve=resolve);},setTimeout,clearTimeout};
vm.createContext(context);
vm.runInContext(fs.readFileSync('static/community-editor.js','utf8'),context);
const editor=context.window.KflowEditor;

(async()=>{
  const host=new Element('p');
  editor.plainMentions(host,'Hi @followed @missing @unfollowed',['followed']);
  assert.equal(host.children.length,1);
  assert.equal(host.children[0].attrs.href,'/forum/user/followed');
  assert.equal(host.textContent,'Hi @followed @missing @unfollowed');
  const special=new Element('p');editor.plainMentions(special,'@{name /?#}',['name /?#']);
  assert.equal(special.children[0].attrs.href,'/forum/user/'+encodeURIComponent('name /?#'));
  const markdown=new Element('div'),code=new Element('code');code.append('@followed');markdown.append('Hello @followed @missing',code);
  editor.linkify(markdown,['followed']);
  assert.equal(markdown.children.filter(node=>node.tagName==='a').length,1);
  assert.equal(code.textContent,'@followed');assert.equal(code.children.length,0);

  const input=new Element('textarea');input.value='abc';input.selectionStart=input.selectionEnd=1;
  input.setRangeText=function(value,start,end){this.value=this.value.slice(0,start)+value+this.value.slice(end);};
  let changes=0;
  const picker=editor.emojiPicker(input,20,()=>changes++,()=>false,message=>{throw new Error(message);});
  picker.children[1].children[0].events.click[0]();
  assert.equal([...input.value].length,4);assert.equal(input.value.startsWith('a'),true);assert.equal(input.value.endsWith('bc'),true);assert.equal(changes,1);
  context.window.innerWidth=320;context.window.innerHeight=600;
  picker.children[0].getBoundingClientRect=()=>({left:200,top:400,bottom:444});picker.children[1].offsetHeight=220;
  picker.open=true;picker.events.toggle[0]();
  assert.equal(picker.children[1].style.width,'286px');assert.equal(picker.children[1].style.left,'22px');assert.equal(picker.children[1].style.top,'174px');
  picker.open=false;picker.events.toggle[0]();

  input._communityEditor={tools:new Element('div')};
  const attachments=editor.attachments(input,{onError:message=>{throw new Error(message);}});
  const files=attachments.host.children[1],previews=attachments.host.children[2];
  files.files=[{type:'image/png',size:100}];files.events.change[0]();
  assert.equal(attachments.pending,true);assert.equal(previews.children.length,1);
  const remove=previews.children[0].children[2];let prevented=false;
  remove.events.pointerdown[0]({preventDefault(){prevented=true;}});assert.equal(prevented,true);
  remove.events.click[0]();
  assert.equal(signal.aborted,true);assert.equal(attachments.pending,false);assert.equal(previews.children.length,0);
  fetchResolve({ok:true,json:async()=>({image:{id:99}})});
  await new Promise(resolve=>setTimeout(resolve,0));
  assert.equal(previews.children.length,0);assert.equal(attachments.ids.length,0);assert.deepEqual(revoked,['blob:test-picture']);
  // The compact mention popover stays inside a narrow viewport and keeps
  // keyboard selection working when it must open above the editor.
  context.window.innerWidth=375;context.window.innerHeight=600;
  const mentionInput=new Element('textarea');mentionInput.id='mention-test';mentionInput.value='@al';mentionInput.selectionStart=mentionInput.selectionEnd=3;
  mentionInput.getBoundingClientRect=()=>({left:300,top:460,bottom:560});mentionInput.setRangeText=input.setRangeText;
  context.fetch=async()=>({ok:true,json:async()=>({items:[{username:'alice',display_name:'Alice'}],next_cursor:null})});
  const mentions=editor.mentionPicker(mentionInput,()=>{},()=>false,500,message=>{throw new Error(message);});
  mentions.panel.offsetHeight=120;mentions.panel.matches=()=>!!mentions.panel.open;
  mentions.panel.showPopover=()=>{mentions.panel.open=true;};mentions.panel.hidePopover=()=>{mentions.panel.open=false;};
  mentionInput.events.input[0]();await new Promise(resolve=>setTimeout(resolve,190));
  assert.equal(mentions.panel.style.width,'300px');assert.equal(mentions.panel.style.left,'63px');assert.equal(mentions.panel.style.top,'334px');
  assert.equal(mentions.panel.hidden,false);assert.equal(mentions.panel.open,true);
  mentionInput.events.keydown[0]({key:'ArrowDown',preventDefault(){}});
  mentionInput.events.keydown[0]({key:'Enter',preventDefault(){}});
  assert.equal(mentionInput.value,'@alice ');assert.equal(mentions.panel.hidden,true);assert.equal(mentions.panel.open,false);
  // Exercise the actual forum submit handler: image-only comments must pass
  // browser validation and send image IDs instead of requiring text.
  const replyInput={value:'',required:true},submit={disabled:false},replyForm={dataset:{},querySelector:selector=>selector==='textarea'?replyInput:submit};
  const replyAttachments={ids:[51],pending:false,host:{},clear(){this.ids=[];}};
  let sentBody,refreshed=0;
  const forumContext={window:{addEventListener(){},KflowEditor:{attach(){},attachments:()=>replyAttachments}},document:{addEventListener(){}},URLSearchParams,location:{search:''},
    fetch:async(url,options)=>{sentBody=JSON.parse(options.body);return {ok:true,json:async()=>({})};}};
  vm.createContext(forumContext);vm.runInContext(fs.readFileSync('static/forum-upgrade.js','utf8'),forumContext);
  forumContext.window.KflowForumExtras.render({querySelector:selector=>selector==='#replyForm'?replyForm:null},{id:1},{currentUser:{username:'alice'},onSent:()=>refreshed++,toast(){}});
  assert.equal(replyInput.required,false);
  await replyForm.onsubmit({preventDefault(){}});
  assert.equal(sentBody.content,'');assert.deepEqual(sentBody.images,[51]);assert.equal(refreshed,1);assert.equal(submit.disabled,false);
  console.log('PASS: followed-only mention links, escaped profile URLs, code exclusion, emoji insertion, removable pending attachments and late-upload cancellation');
})().catch(error=>{console.error(error);process.exitCode=1;});
