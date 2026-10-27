'use strict';
// Tiny DOM contract harness; no packages, network or listening server.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(tag) { this.tagName=tag; this.children=[]; this.textContent=''; this.value=''; this.checked=false; this.listeners={}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children=nodes; }
  addEventListener(event, fn) { this.listeners[event]=fn; }
  setAttribute(key, value) { this[key]=value; }
  focus() { document.activeElement=this; }
  select() { this.selected=true; }
}
const elements = Object.fromEntries(['search','status','income','revenue-evidence','verified-x','cards','summary','notice','refresh','nav-prospects','nav-shortlist','nav-suppressed','metric-total','metric-verified','metric-revenue','metric-shortlist','count-shortlist','count-suppressed','view-title','result-count','empty','clear-filters'].map(id=>[id,new Element('div')]));
for(const [,id] of fs.readFileSync('static/index.html','utf8').matchAll(/id="([^"]+)"/g)) if(!elements[id]) elements[id]=new Element('div');
elements['analytics-range'].value='7';
const document = {getElementById:id=>elements[id],createElement:tag=>new Element(tag),createElementNS:(ns,tag)=>new Element(tag)};
const base = {id:'test',name:'<img src=x onerror=alert(1)>',company:'Example',website:'https://example.test',niche:'AI',offer:'Consulting',expertise_summary:'Case study',opportunity_hypothesis:'Possible benefit',intent:'inferred',income_status:'unknown',income_summary:'Unknown',youtube_status:'unknown',evidence:[{category:'offer',url:'https://example.test/offer',title:'Source',excerpt:'Exact quote',observed_at:'2026-10-26',source_date:'2026-01-01'}],caveats:['Unverified'],status:'new',notes:'',fit_indicators:{cited_categories:['offer'],income_label:'Revenue unverified',intent_label:'Inferred'}};
let calls=[];
const window = {listeners:{},addEventListener(event,fn){this.listeners[event]=fn;}};
const emptyAnalytics={contacted:0,replied:0,opportunity:0,followups_due:0,reply_rate:null,opportunity_rate:null,today_contacted:0,daily_target:30,replies_without_contact:0,opportunities_without_contact:0,daily:Array.from({length:7},(_,i)=>({date:'2026-10-'+(20+i),contacted:0,follow_up:0,replied:0,opportunity:0}))};
const context=vm.createContext({window,document,URL,crypto:require('node:crypto').webcrypto,navigator:{},location:{origin:'http://127.0.0.1:3016'},confirm:()=>true,fetch:async(url,options)=>{calls.push([url,options]);return {ok:true,json:async()=>url==='/api/campaigns'?{campaigns:[]}:url==='/api/events'?{events:[]}:url==='/api/followups'?{followups:[]}:url.startsWith('/api/analytics')?emptyAnalytics:url.endsWith('/outreach')?{metadata:{draft:'',follow_up_at:null}}:options?{prospect:{...base,...JSON.parse(options.body)}}:{prospects:[base]}}},console});
assert.ok(fs.existsSync('static/app.js'),'dashboard JavaScript must exist');
vm.runInContext(fs.readFileSync('static/app.js','utf8'),context);
const flatten = node => [node,...node.children.flatMap(flatten)];
const tick = () => new Promise(resolve=>setImmediate(resolve));
(async()=>{
  await tick();
  assert.equal(typeof elements['nav-dashboard']?.listeners.click,'function','Dashboard navigation must work');
  assert.equal(typeof elements['nav-campaigns']?.listeners.click,'function','Campaign navigation must work');
  assert.equal(typeof elements['nav-followups']?.listeners.click,'function','Followup navigation must work');
  assert.ok(flatten(elements.cards).some(n=>n.tagName==='textarea'&&n['aria-label']==='DM draft for '+base.name),'editable DM draft must be available');
  assert.equal(elements.cards.children.length,1);
  const nodes=flatten(elements.cards);
  assert.ok(nodes.some(n=>n.className==='prospect-row'),'compact prospect rows must replace large cards');
  const sourceDisclosure=nodes.find(n=>n.tagName==='details');
  assert.ok(sourceDisclosure && !sourceDisclosure.open,'source evidence must start collapsed');
  const detailButton=nodes.find(n=>n.tagName==='button'&&n.textContent==='Details');
  assert.ok(detailButton,'full research must be available on demand');
  const research=nodes.find(n=>n.className==='record-detail');
  assert.equal(research.hidden,true,'full research starts hidden');
  detailButton.listeners.click();
  assert.equal(research.hidden,false,'details button reveals full record');
  assert.equal(detailButton['aria-expanded'],'true');
  assert.ok(nodes.some(n=>n.textContent===base.name),'untrusted name must be literal text');
  assert.ok(nodes.some(n=>String(n.textContent).includes('2026-10-26')),'observed date visible');
  assert.ok(nodes.some(n=>String(n.textContent).includes('2026-01-01')),'source date visible');
  for (const url of ['javascript:alert(1)','data:text/html,<svg onload=alert(1)>','https://user:secret@example.test','https://example.test/ white','https://example.test\\\\evil','https://example.test\n']) {
    context.unsafeURL=url;
    const unsafe=vm.runInContext('link("Unsafe source",unsafeURL)',context);
    assert.equal(unsafe.tagName,'span','unsafe source URL must not become a link: ' + JSON.stringify(url));
  }
  const link=nodes.find(n=>n.tagName==='a' && n.textContent==='Source');
  assert.equal(link.href,'https://example.test/offer');
  elements.search.value='no match'; elements.search.listeners.input();
  assert.equal(elements.cards.children.length,0);
  elements.search.value='';elements.search.listeners.input();
  elements['revenue-evidence'].checked=true;elements['revenue-evidence'].listeners.change();
  assert.equal(elements.cards.children.length,0);
  elements['revenue-evidence'].checked=false;elements['revenue-evidence'].listeners.change();
  const shortlist=flatten(elements.cards).find(n=>n.tagName==='button'&&n.textContent==='Shortlist');
  assert.ok(shortlist); await shortlist.listeners.click(); await tick();
  assert.equal(calls.at(-1)[1].method,'POST');
  assert.equal(JSON.parse(calls.at(-1)[1].body).status,'shortlist');
  assert.equal(calls.at(-1)[1].headers['Content-Type'],'application/json');
  assert.ok(flatten(elements.cards).some(n=>n.textContent.includes('X profile unknown')));
  const verified={...base,id:'verified',name:'Verified Owner',x_url:'https://x.com/Owner_1',x_handle:'owner_1',x_status:'verified',evidence:[...base.evidence,{category:'x_profile',url:'https://example.test/about',title:'Identity source',excerpt:'Owner links to https://x.com/Owner_1',observed_at:'2026-10-26T12:00:00Z'}]};
  context.testRows=[verified,{...base,id:'unverified',x_url:'https://twitter.com/Other',x_handle:'Other',x_status:'unverified'},{...base,id:'missing',x_status:'not_found'},base];
  vm.runInContext('prospects = testRows; render();',context);
  const xnodes=flatten(elements.cards.children[0]);
  for (const title of ['X profile','@owner_1']) {
    const xlink=xnodes.find(n=>n.tagName==='a'&&n.textContent===title);
    assert.equal(xlink.href,verified.x_url); assert.equal(xlink.rel,'noopener noreferrer'); assert.equal(xlink.target,'_blank');
  }
  assert.ok(xnodes.some(n=>n.textContent.includes('Identity verified via primary source')));
  assert.ok(xnodes.some(n=>n.textContent.includes('DM eligibility unknown')));
  assert.ok(xnodes.some(n=>n.textContent==='Identity source'));
  assert.ok(flatten(elements.cards).some(n=>n.textContent.includes('not proof no account exists')));
  elements['verified-x'].checked=true; elements['verified-x'].listeners.change();
  assert.equal(elements.cards.children.length,1);
  elements.search.value='owner_1'; elements.search.listeners.input(); assert.equal(elements.cards.children.length,1);
  elements['revenue-evidence'].checked=true; elements['revenue-evidence'].listeners.change(); assert.equal(elements.cards.children.length,0);
  elements['revenue-evidence'].checked=false; elements.search.value='';
  context.testRows=[{...verified,x_url:'https://x.com/Owner_1?bad=1'},{...verified,evidence:base.evidence},{...verified,x_handle:'wrong'}];
  vm.runInContext('prospects = testRows; render();',context); assert.equal(elements.cards.children.length,0,'malformed/unsupported profiles cannot pass verified filter');
  elements['verified-x'].checked=false; elements['verified-x'].listeners.change();
  assert.ok(!flatten(elements.cards).some(n=>n.tagName==='a'&&n.textContent==='X profile'),'invalid profiles never linked');
  assert.ok(fs.readFileSync('static/index.html','utf8').includes('id="verified-x"'));
  context.testRows=[{...base,id:'new-one',status:'new'}, {...verified,status:'shortlist'}, {...base,id:'suppressed',status:'do_not_contact',evidence:[...base.evidence,{category:'income'}]}];
  vm.runInContext('prospects = testRows; render();',context);
  assert.equal(elements['metric-total'].textContent,'3');
  assert.equal(elements['metric-verified'].textContent,'1');
  assert.equal(elements['metric-revenue'].textContent,'1');
  assert.equal(elements['metric-shortlist'].textContent,'1');
  elements['nav-shortlist'].listeners.click();
  assert.equal(elements.cards.children.length,1);
  assert.ok(flatten(elements.cards).some(n=>n.textContent==='Verified Owner'));
  assert.equal(elements['nav-shortlist']['aria-current'],'page');
  elements['nav-suppressed'].listeners.click();
  assert.equal(elements.cards.children.length,1);
  assert.ok(flatten(elements.cards).filter(n=>n.tagName==='button'&&['Shortlist','Maybe','Reject','Do not contact'].includes(n.textContent)).every(n=>n.disabled));
  elements.search.value='nobody';elements.search.listeners.input();
  assert.equal(elements.empty.hidden,false);
  elements['clear-filters'].listeners.click();
  assert.equal(elements.cards.children.length,1,'clear filters keeps selected navigation view');
  elements['nav-prospects'].listeners.click();
  assert.equal(elements.cards.children.length,3,'Prospects includes all records with suppression labels');
  elements.status.value='new';elements.status.listeners.change();
  assert.equal(elements.cards.children.length,1,'review-state filter excludes shortlist and suppression');
  elements.income.value='self_reported';elements.income.listeners.change();
  assert.equal(elements.cards.children.length,0,'income classification combines with review-state filter');
  elements['clear-filters'].listeners.click();
  assert.equal(elements.cards.children.length,3);
  context.testRows=[base];
  vm.runInContext('prospects = testRows; render();',context);
  let note=flatten(elements.cards).find(n=>n.tagName==='textarea');
  note.value='Keep this private draft'; note.listeners.input();
  let prevented=false;
  const unload={preventDefault(){prevented=true;}};
  assert.equal(typeof window.listeners.beforeunload,'function','tab exit must warn about draft loss');
  window.listeners.beforeunload(unload);
  assert.equal(prevented,true);
  assert.equal(unload.returnValue,'');
  elements['nav-suppressed'].listeners.click();elements['nav-prospects'].listeners.click();
  assert.ok(flatten(elements.cards).some(n=>n.tagName==='textarea'&&n.value==='Keep this private draft'),'navigation retains drafts');
  elements.search.value='hide all';elements.search.listeners.input();
  elements.search.value='';elements.search.listeners.input();
  note=flatten(elements.cards).find(n=>n.tagName==='textarea');
  assert.equal(note.value,'Keep this private draft','filter changes retain unsaved notes');
  await elements.refresh.listeners.click(); await tick();
  assert.ok(flatten(elements.cards).some(n=>n.tagName==='textarea'&&n.value==='Keep this private draft'),'refresh retains drafts');
  assert.ok(elements.notice.textContent.includes('unsaved'),'drafts are clearly signposted');
  const saveButton=flatten(elements.cards).find(n=>n.tagName==='button'&&n.textContent==='Save notes');
  await saveButton.listeners.click(); await tick();
  assert.equal(JSON.parse(calls.at(-1)[1].body).notes,'Keep this private draft');
  let cleanPrevented=false;
  window.listeners.beforeunload({preventDefault(){cleanPrevented=true;}});
  assert.equal(cleanPrevented,false,'saved notes do not trigger tab-exit warning');
  const realFetch=context.fetch;
  context.fetch=async()=>{throw new Error('Offline test');};
  note=flatten(elements.cards).find(n=>n.tagName==='textarea');
  note.value='Retain draft after failed save';note.listeners.input();
  await flatten(elements.cards).find(n=>n.tagName==='button'&&n.textContent==='Save notes').listeners.click();
  assert.ok(elements.notice.textContent.includes('Offline test'));
  elements.search.value='hide';elements.search.listeners.input();
  elements['clear-filters'].listeners.click();
  assert.equal(flatten(elements.cards).find(n=>n.tagName==='textarea').value,'Retain draft after failed save');
  context.fetch=realFetch;
  // A late response must not erase edits made while that save was in flight.
  let finishSave;
  context.fetch=()=>new Promise(resolve=>{finishSave=resolve;});
  const saving=flatten(elements.cards).find(n=>n.tagName==='button'&&n.textContent==='Save notes').listeners.click();
  note=flatten(elements.cards).find(n=>n.tagName==='textarea');
  note.value='Newer draft typed during save';note.listeners.input();
  finishSave({ok:true,json:async()=>({prospect:{...base,notes:'Retain draft after failed save'}})});
  await saving;
  assert.equal(flatten(elements.cards).find(n=>n.tagName==='textarea').value,'Newer draft typed during save');
  assert.ok(elements.notice.textContent.includes('unsaved'));
  context.testRows=[base,{...base,id:'other',name:'Other Person',notes:''}];
  vm.runInContext('prospects = testRows; render();',context);
  context.fetch=async(url,options)=>({ok:true,json:async()=>({prospect:{...base,id:'other',name:'Other Person',...JSON.parse(options.body)}})});
  await flatten(elements.cards.children[1]).find(n=>n.tagName==='button'&&n.textContent==='Save notes').listeners.click();
  assert.equal(flatten(elements.cards.children[0]).find(n=>n.tagName==='textarea').value,'Newer draft typed during save','saving a different record keeps the first draft');
  context.fetch=realFetch;
  // Outreach drafts survive navigation, failures and late responses independently of notes.
  context.testRows=[base];vm.runInContext('prospects=testRows; drafts.clear(); render();',context);
  const dm=()=>flatten(elements.cards).find(n=>n.tagName==='textarea'&&n['aria-label']==='DM draft for '+base.name);
  dm().value='Private manual DM';dm().listeners.input();
  elements['nav-campaigns'].listeners.click();elements['nav-prospects'].listeners.click();
  assert.equal(dm().value,'Private manual DM');
  context.fetch=async()=>{throw new Error('Offline DM');};
  await flatten(elements.cards).find(n=>n.textContent==='Save outreach details').listeners.click();
  assert.equal(dm().value,'Private manual DM');
  assert.ok(elements.notice.textContent.includes('Offline DM'));
  let completeDM;
  context.fetch=(url,options)=>url.endsWith('/outreach')&&options?new Promise(resolve=>{completeDM=resolve;}):realFetch(url,options);
  const savingDM=flatten(elements.cards).find(n=>n.textContent==='Save outreach details').listeners.click();
  dm().value='Newer manual DM';dm().listeners.input();
  completeDM({ok:true,json:async()=>({metadata:{draft:'Private manual DM',follow_up_at:null}})});
  await savingDM;
  assert.equal(dm().value,'Newer manual DM','late saved response cannot erase newer DM draft');
  assert.equal(flatten(elements.cards).find(n=>n.textContent==='Save outreach details').disabled,false,'save button must re-enable after rerender');
  context.fetch=realFetch;
  // A clipboard API failure falls back honestly on HTTP.
  vm.runInContext('outreachDrafts.clear();',context);
  let oldRead,reads=0;
  context.fetch=(url,options)=>url.endsWith('/outreach')&&!options?(++reads===1?new Promise(resolve=>{oldRead=resolve;}):Promise.resolve({ok:true,json:async()=>({metadata:{draft:'Newest saved draft',follow_up_at:null}})})):realFetch(url,options);
  const staleLoad=vm.runInContext('loadWorkspace()',context);
  await vm.runInContext('loadWorkspace()',context);
  oldRead({ok:true,json:async()=>({metadata:{draft:'Older read',follow_up_at:null}})});await staleLoad;
  vm.runInContext('render()',context);
  assert.equal(dm().value,'Newest saved draft','out-of-order workspace reads must not overwrite newer state');
  context.fetch=realFetch;
  document.execCommand=()=>true;
  await flatten(elements.cards).find(n=>n.textContent==='Copy draft').listeners.click();
  assert.ok(elements.notice.textContent.includes('Draft copied'));
  document.execCommand=()=>false;
  await flatten(elements.cards).find(n=>n.textContent==='Copy draft').listeners.click();
  assert.ok(elements.notice.textContent.includes('Could not copy automatically'));
  // Network uncertainty retains the original event intent; double clicks make one request.
  let failEvent; const eventBodies=[];
  context.fetch=(url,options)=>url==='/api/events'&&options?(eventBodies.push(options.body),new Promise((resolve,reject)=>{failEvent=reject;})):realFetch(url,options);
  let log=flatten(elements.cards).find(n=>n.textContent==='Log contacted');
  const firstLog=log.listeners.click();await log.listeners.click();
  assert.equal(eventBodies.length,1,'in-flight double-click must not submit again');
  failEvent(new Error('Unknown result'));await firstLog;
  context.fetch=(url,options)=>{if(url==='/api/events'&&options){eventBodies.push(options.body);return Promise.resolve({ok:true,json:async()=>({event:JSON.parse(options.body)})});}return realFetch(url,options);};
  await log.listeners.click();
  assert.equal(eventBodies.length,2);assert.equal(eventBodies[0],eventBodies[1],'retry must use identical id and payload');
  assert.equal(elements['kpi-contacted'].textContent,'0','only server analytics, never client invented counts');
  // A committed event with failed refresh must never be posted again by retry.
  const committedBodies=[]; let failRefresh=true;
  context.fetch=(url,options)=>{
    if(url==='/api/events'&&options) { committedBodies.push(options.body); return Promise.resolve({ok:true,json:async()=>({event:JSON.parse(options.body)})}); }
    if(url==='/api/campaigns'&&failRefresh) return Promise.reject(new Error('Refresh unavailable'));
    return realFetch(url,options);
  };
  log=flatten(elements.cards).find(n=>n.textContent==='Log contacted');
  await log.listeners.click();
  assert.equal(committedBodies.length,1);
  assert.ok(elements.notice.textContent.includes('event logged'),'committed write must be reported as logged despite refresh failure');
  assert.ok(elements.notice.textContent.includes('Refresh'),'notice must distinguish refresh failure');
  assert.equal(vm.runInContext('eventIntents.get("test-contacted").id',context),JSON.parse(committedBodies[0]).id,'retain committed intent until refresh succeeds');
  elements['nav-dashboard'].listeners.click();elements['nav-prospects'].listeners.click();
  let retry=flatten(elements.cards).find(n=>n.textContent==='Retry refresh (contacted)');
  assert.ok(retry,'offer read-only refresh retry, not another logging action');
  await retry.listeners.click();
  assert.equal(committedBodies.length,1,'failed refresh retry must not write');
  failRefresh=false;
  retry=flatten(elements.cards).find(n=>n.textContent==='Retry refresh (contacted)');
  await retry.listeners.click();
  assert.equal(committedBodies.length,1,'successful refresh retry must not write');
  assert.ok(flatten(elements.cards).some(n=>n.textContent==='Log contacted'),'a new action is available only after recovery');
  context.fetch=realFetch;
  // Suppression removes stale actionable rows and invalidates the due KPI even offline.
  for(const offline of [true,false]) {
    context.testRows=[{...base,status:'new'}];
    context.dueAnalytics={...emptyAnalytics,followups_due:1};
    vm.runInContext('prospects=testRows;due=[{prospect_id:"test"}];analytics=dueAnalytics;activeView="followups";render();',context);
    assert.equal(elements.cards.children.length,1);
    assert.equal(elements['kpi-due'].textContent,'1');
    context.fetch=(url,options)=>{
      if(options&&url==='/api/prospects/test') return Promise.resolve({ok:true,json:async()=>({prospect:{...base,status:'do_not_contact'}})});
      if(offline) return Promise.reject(new Error('Suppression refresh offline'));
      return realFetch(url,options);
    };
    await flatten(elements.cards).find(n=>n.textContent==='Do not contact').listeners.click();
    assert.equal(elements.cards.children.length,0,'suppressed person must leave Follow-ups immediately');
    assert.equal(elements['kpi-due'].textContent,offline?'Refresh needed':'0','due KPI must be invalidated or refreshed, never stale');
    assert.ok(elements.notice.textContent.includes('Saved'),'refresh failure cannot imply suppression failed');
    // Even a stale followups response must not restore a suppressed row.
    vm.runInContext('due=[{prospect_id:"test"}];render();',context);
    assert.equal(elements.cards.children.length,0);
  }
  context.fetch=realFetch;
  elements['nav-prospects'].listeners.click();
  context.testRows=[{...base,status:'do_not_contact'}];vm.runInContext('prospects=testRows;render();',context);
  for(const text of ['Copy draft','Log contacted','Log follow up']) assert.equal(flatten(elements.cards).find(n=>n.textContent===text).disabled,true);
  assert.equal(flatten(elements.cards).find(n=>n.textContent==='Save outreach details').disabled,false,'suppressed drafts remain editable');
  context.testRows=[];vm.runInContext('prospects = testRows; render();',context);
  assert.equal(elements.empty.hidden,false);
  for (const id of ['metric-total','metric-verified','metric-revenue','metric-shortlist']) assert.equal(elements[id].textContent,'0');
  console.log('UI contract PASS: dashboard/campaign/followup navigation; manual drafts + late/failed saves; HTTP clipboard fallback; immutable event retry/double-click; suppression; compact research/citations/dates; filters; safe links/XSS; real server analytics');
})().catch(error=>{console.error(error);process.exitCode=1;});
