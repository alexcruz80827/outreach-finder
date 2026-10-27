'use strict';
const byId = id => document.getElementById(id);
const labels = {new:'New',shortlist:'Shortlist',maybe:'Maybe',reject:'Reject',do_not_contact:'Do not contact'};
let prospects = [];
let activeView = 'dashboard';
const views = {dashboard:{title:'Dashboard',status:''},campaigns:{title:'Campaigns',status:''},followups:{title:'Follow-ups',status:''},prospects:{title:'Prospects',status:''},shortlist:{title:'Shortlist',status:'shortlist'},suppressed:{title:'Suppressed',status:'do_not_contact'}};
let campaigns = [], events = [], due = [], analytics = null;
let workspaceRead = 0;
const outreachData = new Map(), outreachDrafts = new Map(), pending = new Set(), eventIntents = new Map();
const renderedButtons = new Map();
const committedEventIntents = new Set();
// Drafts stay in this tab only; no research or private notes enter browser storage.
const drafts = new Map();
const openRecords = new Set();
function draftNotice(message='') {
  const count=drafts.size+outreachDrafts.size;
  byId('notice').textContent = message + (count ? (message ? ' · ' : '') + count + ' unsaved draft' + (count===1 ? '' : 's') + ' kept in this tab. Save before closing.' : '');
}
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function link(title, url) {
  const node = element('a', title);
  try {
    if (typeof url !== 'string' || /[\s\\]/.test(url)) return element('span',title);
    const parsed = new URL(url);
    if (!['https:', 'http:'].includes(parsed.protocol) || parsed.username || parsed.password) return element('span', title);
    node.href = url;
    node.target = '_blank'; node.rel = 'noopener noreferrer';
  } catch (_) { return element('span', title); }
  return node;
}
function section(title, content, className='') {
  const node = element('section', undefined, className);
  node.append(element('h3', title), element('p', content));
  return node;
}
async function save(p, changes, card) {
  if(pending.has('review-'+p.id)) return;
  pending.add('review-'+p.id);
  byId('notice').textContent = 'Saving…';
  try {
    const response = await fetch('/api/prospects/' + encodeURIComponent(p.id), {method:'POST', headers:{'Content-Type':'application/json'},body:JSON.stringify(changes)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Save failed');
    Object.assign(p, result.prospect);
    if (drafts.get(p.id) === changes.notes) drafts.delete(p.id);
    if(p.status==='do_not_contact') {
      due=due.filter(d=>d.prospect_id!==p.id);
      if(analytics) analytics={...analytics,followups_due:null};
    }
    render();
    const success='Saved ' + p.name + ' · ' + labels[p.status];
    if(p.status==='do_not_contact') {
      try { await loadWorkspace();render();draftNotice(success); }
      catch(error) { draftNotice(success+' · Refresh failed: '+error.message+'. Refresh to reload due analytics.'); }
    } else draftNotice(success);
  } catch (error) { draftNotice(error.message + ' — your unsaved notes remain in this tab.'); }
  finally { pending.delete('review-'+p.id); }
}
function xProfile(p) {
  if (!['verified','unverified'].includes(p.x_status) || typeof p.x_url !== 'string' || typeof p.x_handle !== 'string') return false;
  const match = /^https:\/\/(?:x\.com|twitter\.com)\/([A-Za-z0-9_]{1,15})$/.exec(p.x_url);
  if (!match || match[0] !== p.x_url || !/^[A-Za-z0-9_]{1,15}$/.test(p.x_handle) || match[1].toLowerCase() !== p.x_handle.toLowerCase()) return false;
  if (['home','search','intent','messages','settings','i','explore','compose','login','signup'].includes(p.x_handle.toLowerCase())) return false;
  return p.x_status !== 'verified' || p.evidence.some(e=>e.category==='x_profile');
}
function recordDetail(p) {
  const node = element('div', undefined, 'record-detail');
  node.hidden = !openRecords.has(p.id);
  const header = element('div', undefined, 'card-header');
  const heading = element('div');
  heading.append(element('h2', p.name), element('p', p.company + ' / ' + p.niche, 'muted'));
  const hasX = xProfile(p);
  if (hasX) heading.append(link('@' + p.x_handle, p.x_url));
  heading.append(element('p', (hasX ? (p.x_status==='verified' ? 'Identity verified via primary source — not an X checkmark' : 'X identity unverified') : p.x_status==='not_found' ? 'X profile not found in research — not proof no account exists' : 'X profile unknown — no confirmed account supplied') + ' · DM eligibility unknown', 'muted'));
  header.append(heading, element('span', labels[p.status], 'badge ' + p.status));
  node.append(header);
  const sites = element('div', undefined, 'sites');
  sites.append(link('Website', p.website));
  if (hasX) sites.append(link('X profile', p.x_url));
  if (p.youtube_url) sites.append(link('YouTube', p.youtube_url));
  node.append(sites);
  node.append(section('Commercial offer', p.offer), section('Expertise · research summary', p.expertise_summary));
  const indicators = p.fit_indicators;
  node.append(element('p', 'Cited categories: ' + indicators.cited_categories.join(' · '), 'indicator'));
  node.append(section('Revenue evidence · ' + p.income_status.replaceAll('_',' '), p.income_summary));
  node.append(element('p', indicators.income_label + '. Business revenue ≠ personal income, profit or available budget.', 'warning'));
  node.append(element('p', 'YouTube: ' + p.youtube_status.replaceAll('_',' ') + ' · ' + indicators.intent_label, 'muted'));
  node.append(section('Opportunity hypothesis · not an established need', p.opportunity_hypothesis, 'hypothesis'));
  const evidence = element('details');
  evidence.open = false;
  evidence.append(element('summary', 'Source evidence (' + p.evidence.length + ') · verify context'));
  for (const e of p.evidence) {
    const entry = element('div', undefined, 'evidence');
    entry.append(element('span', e.category.toUpperCase(), 'eyebrow'), link(e.title, e.url), element('blockquote', e.excerpt), element('p', 'Observed: ' + e.observed_at + ' · Source date: ' + (e.source_date || 'not supplied'), 'muted'), element('p', e.url, 'source-url'));
    evidence.append(entry);
  }
  node.append(evidence);
  const caveats = element('section', undefined, 'caveats');
  caveats.append(element('h3', 'Caveats & uncertainty'));
  if (!p.caveats.length) caveats.append(element('p', 'No caveats supplied. Absence of caveats is not confidence.'));
  for (const c of p.caveats) caveats.append(element('p', '• ' + c));
  node.append(caveats);
  const noteLabel = element('label', 'Private review notes');
  const notes = element('textarea'); notes.value = drafts.has(p.id) ? drafts.get(p.id) : p.notes; notes.maxLength = 20000; notes.rows = 3;
  notes.addEventListener('input',()=>{
    if (notes.value === p.notes) drafts.delete(p.id); else drafts.set(p.id,notes.value);
    draftNotice();
  });
  notes.setAttribute('aria-label', 'Notes for ' + p.name); noteLabel.append(notes); node.append(noteLabel);
  const actions = element('div', undefined, 'actions');
  const saveNotes = element('button', 'Save notes'); saveNotes.type='button';
  saveNotes.addEventListener('click', () => save(p, {notes:notes.value}, node)); actions.append(saveNotes);
  for (const status of ['shortlist','maybe','reject','do_not_contact']) {
    const button = element('button', labels[status], status==='do_not_contact' ? 'danger' : ''); button.type='button';
    button.disabled = p.status === 'do_not_contact' || p.status === status;
    button.addEventListener('click', () => {
      if (status==='do_not_contact' && !confirm('Suppress this person? This cannot be cleared from the review UI or by reimport.')) return;
      return save(p, {status, notes:notes.value}, node);
    }); actions.append(button);
  }
  node.append(actions);
  node.append(outreachDetail(p));
  if (p.status==='do_not_contact') node.append(element('p', 'Suppressed. Review status cannot be reset; notes remain editable.', 'warning'));
  return node;
}
const incomeLabels = {unknown:'Unknown',commercial_signal_only:'Commercial signal',self_reported:'Self-reported',independently_verified:'Independent citation'};
function card(p) {
  const node = element('article', undefined, 'prospect-row');
  const row = element('div', undefined, 'row-overview');
  const person = element('div', undefined, 'person-cell');
  const avatar = element('span', p.name.split(/\s+/).map(s=>s[0]).slice(0,2).join(''), 'avatar');
  avatar.setAttribute('aria-hidden','true');
  const identity = element('div', undefined, 'person-copy');
  identity.append(element('h2', p.name), element('p', p.company, 'company'));
  person.append(avatar, identity);
  const profile = element('div', undefined, 'profile-cell');
  if (xProfile(p)) profile.append(link('@' + p.x_handle, p.x_url));
  else profile.append(element('span',p.x_status==='not_found' ? 'Not found' : 'Unknown','muted'));
  profile.append(element('small',xProfile(p) ? (p.x_status==='verified' ? 'Identity verified' : 'Unverified identity') : 'X identity','identity-label'));
  const offer = element('div',undefined,'offer-cell');
  offer.append(element('p',p.offer,'offer-preview'),element('small',p.niche,'muted'));
  const revenue = element('div',undefined,'revenue-cell');
  revenue.append(element('span',incomeLabels[p.income_status]),element('small',p.evidence.some(e=>e.category==='income') ? 'Income citation' : 'No income citation','muted'));
  const status = element('div',undefined,'status-cell');
  status.append(element('span',labels[p.status],'badge ' + p.status));
  const detail = recordDetail(p);
  detail.id = 'detail-' + p.id;
  const button = element('button','Details','detail-button'); button.type='button';
  button.textContent = detail.hidden ? 'Details' : 'Close';
  button.setAttribute('aria-expanded',String(!detail.hidden)); button.setAttribute('aria-controls',detail.id);
  button.setAttribute('aria-label','Details for ' + p.name);
  button.addEventListener('click',()=>{
    detail.hidden = !detail.hidden;
    if (detail.hidden) openRecords.delete(p.id); else openRecords.add(p.id);
    button.setAttribute('aria-expanded',String(!detail.hidden));
    button.textContent = detail.hidden ? 'Details' : 'Close';
  });
  row.append(person,profile,offer,revenue,status,button);
  node.append(row,detail);
  return node;
}
function render() {
  renderedButtons.clear();
  const query = byId('search').value.trim().toLowerCase();
  const status = byId('status').value;
  const income = byId('income').value;
  const hasRevenue = byId('revenue-evidence').checked;
  const verifiedX = byId('verified-x').checked;
  const campaign=campaigns.find(c=>c.id===byId('campaign-filter').value);
  const rows = prospects.filter(p => (activeView!=='followups' || (p.status!=='do_not_contact' && due.some(d=>d.prospect_id===p.id))) && (!campaign || campaign.members.includes(p.id)) && (!views[activeView].status || p.status===views[activeView].status) && (!query || JSON.stringify(p).toLowerCase().includes(query)) && (!status || p.status===status) && (!income || p.income_status===income) && (!hasRevenue || p.evidence.some(e=>e.category==='income')) && (!verifiedX || (p.x_status==='verified' && xProfile(p))));
  byId('cards').replaceChildren(...rows.map(card));
  byId('metric-total').textContent = String(prospects.length);
  byId('metric-verified').textContent = String(prospects.filter(p=>p.x_status==='verified' && xProfile(p)).length);
  byId('metric-revenue').textContent = String(prospects.filter(p=>p.evidence.some(e=>e.category==='income')).length);
  const shortlisted = String(prospects.filter(p=>p.status==='shortlist').length);
  byId('metric-shortlist').textContent = shortlisted;
  byId('count-shortlist').textContent = shortlisted;
  byId('count-suppressed').textContent = String(prospects.filter(p=>p.status==='do_not_contact').length);
  byId('result-count').textContent = String(rows.length);
  byId('view-title').textContent = views[activeView].title;
  byId('empty').hidden = rows.length > 0;
  for (const view of Object.keys(views)) byId('nav-' + view).setAttribute('aria-current',view===activeView ? 'page' : 'false');
  byId('summary').textContent = rows.length + ' shown / ' + prospects.length + ' imported · ' + prospects.filter(p=>p.status==='shortlist').length + ' shortlisted · ' + prospects.filter(p=>p.status==='do_not_contact').length + ' suppressed' + (!prospects.length ? '. No research imported yet. Use the CLI import command.' : !rows.length ? '. No matches — adjust filters.' : '');
  byId('dashboard').hidden=activeView!=='dashboard';
  byId('campaign-panel').hidden=activeView!=='campaigns';
  byId('research-panel').hidden=['dashboard','campaigns'].includes(activeView);
  byId('queue-note').hidden=activeView!=='followups';
  renderCampaigns();
  renderAnalytics();
}
async function load() {
  try {
    const response = await fetch('/api/prospects');
    if (!response.ok) throw new Error('Could not load local prospects');
    prospects = (await response.json()).prospects;
    await loadWorkspace();
    render();
    draftNotice();
  } catch (error) { draftNotice(error.message); }
}
byId('search').addEventListener('input', render);
for (const id of ['status','income','revenue-evidence','verified-x','campaign-filter']) byId(id).addEventListener('change', render);
byId('refresh').addEventListener('click', load);
for (const view of Object.keys(views)) byId('nav-' + view).addEventListener('click',()=>{
  activeView = view;
  byId('status').value = '';
  render();
});
byId('clear-filters').addEventListener('click',()=>{
  for (const id of ['search','status','income','campaign-filter']) byId(id).value = '';
  for (const id of ['revenue-evidence','verified-x']) byId(id).checked = false;
  render();
});
window.addEventListener('beforeunload',event=>{
  if (!drafts.size && !outreachDrafts.size) return;
  event.preventDefault();
  event.returnValue = '';
});
// Every write is local manual bookkeeping, never an external send.
async function api(path, payload) {
  const response=await fetch(path,payload===undefined?undefined:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const data=await response.json();
  if(!response.ok) throw new Error(data.error || 'Request failed');
  return data;
}
function uniqueId(prefix) {
  const bytes=new Uint32Array(4); crypto.getRandomValues(bytes);
  return prefix+'-'+Array.from(bytes,n=>n.toString(16)).join('-');
}
function button(text, key, fn, blocked=false) {
  const b=element('button',text); b.type='button'; b.disabled=blocked || pending.has(key);
  renderedButtons.set(key,{node:b,blocked});
  b.addEventListener('click',async()=>{
    if(pending.has(key) || blocked) return;
    pending.add(key); b.disabled=true;
    try { await fn(); } catch(error) { draftNotice(error.message+' — unsaved edits remain in this tab.'); }
    finally { pending.delete(key); b.disabled=blocked; const latest=renderedButtons.get(key); if(latest) latest.node.disabled=latest.blocked; }
  });
  return b;
}
async function loadWorkspace() {
  const read=++workspaceRead, rows=[...prospects];
  const [cs,es,fs,a,...metas]=await Promise.all([api('/api/campaigns'),api('/api/events'),api('/api/followups'),api('/api/analytics?days='+byId('analytics-range').value),...rows.map(p=>api('/api/prospects/'+encodeURIComponent(p.id)+'/outreach'))]);
  if(read!==workspaceRead) return;
  campaigns=cs.campaigns; events=es.events; due=fs.followups; analytics=a;
  rows.forEach((p,i)=>outreachData.set(p.id,metas[i].metadata));
  const selected=byId('campaign-filter').value;
  byId('campaign-filter').replaceChildren(option('All campaigns',''),...campaigns.map(c=>option(c.name,c.id)));
  byId('campaign-filter').value=selected;
  for(const key of committedEventIntents) eventIntents.delete(key);
  committedEventIntents.clear();
}
function option(title,value) { const o=element('option',title); o.value=value; return o; }
function editMetadata(p,field,value) {
  const draft={...(outreachDrafts.get(p.id)||{}),[field]:value};
  if(value===(outreachData.get(p.id)||{draft:'',follow_up_at:null})[field]) delete draft[field];
  if(Object.keys(draft).length) outreachDrafts.set(p.id,draft); else outreachDrafts.delete(p.id);
  draftNotice();
}
async function saveMetadata(p) {
  const changes={...(outreachDrafts.get(p.id)||{})};
  if(!Object.keys(changes).length) { draftNotice('No outreach edits to save.'); return; }
  const data=await api('/api/prospects/'+encodeURIComponent(p.id)+'/outreach',changes);
  outreachData.set(p.id,data.metadata);
  const current={...(outreachDrafts.get(p.id)||{})};
  for(const key of Object.keys(changes)) if(current[key]===changes[key]) delete current[key];
  if(Object.keys(current).length) outreachDrafts.set(p.id,current); else outreachDrafts.delete(p.id);
  await loadWorkspace(); render(); draftNotice('Outreach details saved.');
}
function localDate(value) {
  if(!value) return '';
  const d=new Date(value); return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);
}
async function copyDraft(value,area) {
  if(!value) throw new Error('Draft is empty');
  try {
    if(!navigator.clipboard?.writeText) throw new Error('Clipboard API unavailable');
    await navigator.clipboard.writeText(value);
  } catch(_) {
    area.focus(); area.select();
    if(!document.execCommand || !document.execCommand('copy')) throw new Error('Could not copy automatically. Draft selected: use your system Copy command');
  }
  draftNotice('Draft copied. Nothing sent. Review the contact route and content before manual outreach.');
}
function outreachDetail(p) {
  const box=element('section',undefined,'outreach-detail');
  const blocked=p.status==='do_not_contact';
  const data={draft:'',follow_up_at:null,...outreachData.get(p.id),...outreachDrafts.get(p.id)};
  box.append(element('h3','Manual outreach'),element('p','Editable DM draft · not AI generated. No X account or synced inbox. Verified personal X is optional; review the contact route before sending.','muted'));
  const label=element('label','DM draft'); const area=element('textarea'); area.value=data.draft; area.maxLength=20000; area.rows=4; area.setAttribute('aria-label','DM draft for '+p.name);
  area.addEventListener('input',()=>editMetadata(p,'draft',area.value)); label.append(area); box.append(label);
  const dateLabel=element('label','Follow-up date (your local time; stored in UTC)'); const input=element('input'); input.type='datetime-local'; input.value=localDate(data.follow_up_at); input.disabled=blocked; input.setAttribute('aria-label','Follow-up date for '+p.name);
  input.addEventListener('input',()=>{ if(!input.value) editMetadata(p,'follow_up_at',null); else if(!Number.isNaN(new Date(input.value).getTime())) editMetadata(p,'follow_up_at',new Date(input.value).toISOString()); });
  dateLabel.append(input); box.append(dateLabel);
  if(data.follow_up_at) box.append(element('p','Scheduled: '+data.follow_up_at,'muted'));
  const actions=element('div',undefined,'actions');
  actions.append(button('Save outreach details','meta-'+p.id,()=>saveMetadata(p)),button('Copy draft','copy-'+p.id,()=>copyDraft(area.value,area),blocked));
  box.append(actions);
  const memberships=element('div',undefined,'memberships'); memberships.append(element('h3','Campaign membership'));
  if(!campaigns.length) memberships.append(element('p','Create a campaign in Campaigns to assign this prospect.','muted'));
  for(const c of campaigns) {
    const assigned=c.members.includes(p.id);
    memberships.append(button((assigned?'Remove from ':'Add to ')+c.name,'member-'+p.id+'-'+c.id,async()=>{
      await api('/api/campaigns/'+c.id+'/members',{prospect_id:p.id,assigned:!assigned});
      await loadWorkspace();render();draftNotice('Campaign membership saved.');
    }));
  }
  box.append(memberships);
  const campaignLabel=element('label','Attribute event to campaign'); const select=element('select'); select.append(option('No campaign',''),...campaigns.filter(c=>c.members.includes(p.id)).map(c=>option(c.name,c.id))); campaignLabel.append(select); box.append(campaignLabel);
  const noteLabel=element('label','Event note (optional, immutable after logging)'); const note=element('input'); note.maxLength=2000; noteLabel.append(note); box.append(noteLabel);
  box.append(element('p','Log only actions/outcomes that actually happened. Events are immutable and timestamped now. A failed request can be retried with the same intent.','muted'));
  const logs=element('div',undefined,'actions');
  for(const kind of ['contacted','follow_up','replied','opportunity','won','lost']) {
    const key=p.id+'-'+kind;
    logs.append(button(committedEventIntents.has(key)?'Retry refresh ('+kind.replaceAll('_',' ')+')':'Log '+kind.replaceAll('_',' '),'event-'+key,async()=>{
      if(!committedEventIntents.has(key)) {
        if(!confirm('Manually log '+kind.replaceAll('_',' ')+' for '+p.name+'? This records history only, sends nothing, and cannot be undone.')) return;
        let payload=eventIntents.get(key);
        if(!payload) { payload={id:uniqueId('event'),prospect_id:p.id,campaign_id:select.value||null,kind,occurred_at:new Date().toISOString(),note:note.value}; eventIntents.set(key,payload); }
        await api('/api/events',payload);
        committedEventIntents.add(key);
      }
      const success='Manual '+kind.replaceAll('_',' ')+' event logged. Nothing sent.';
      try { await loadWorkspace();render();draftNotice(success+' Follow-up dates remain until you reschedule or clear them.'); }
      catch(error) { render();draftNotice(success+' Refresh failed: '+error.message+'. Use Retry refresh or Refresh; retry only reads workspace data.'); }
    },!committedEventIntents.has(key)&&blocked&&['contacted','follow_up'].includes(kind)));
  }
  box.append(logs);
  const history=element('details'); history.append(element('summary','Manual event history'));
  const rows=events.filter(e=>e.prospect_id===p.id);
  if(!rows.length) history.append(element('p','No events logged. Research status is not contact history.'));
  for(const e of rows) history.append(element('p',e.occurred_at+' · '+e.kind.replaceAll('_',' ')+' · '+(e.campaign_id||'No campaign')+(e.note?' · '+e.note:'')));
  box.append(history);
  return box;
}
function renderCampaigns() {
  const nodes=campaigns.map(c=>{
    const box=element('article',undefined,'campaign-card'); box.append(element('h3',c.name),element('p',c.members.length+' members · created '+c.created_at,'muted'));
    box.append(button('View members','view-'+c.id,async()=>{activeView='prospects';byId('campaign-filter').value=c.id;render();}));
    const select=element('select'); select.setAttribute('aria-label','Add prospect to '+c.name); select.append(option('Choose a prospect',''),...prospects.filter(p=>!c.members.includes(p.id)).map(p=>option(p.name+(p.status==='do_not_contact'?' (suppressed)':''),p.id)));
    box.append(select,button('Add member','add-'+c.id,async()=>{if(!select.value) throw new Error('Choose a prospect'); await api('/api/campaigns/'+c.id+'/members',{prospect_id:select.value,assigned:true});await loadWorkspace();render();draftNotice('Member added.');}));
    for(const id of c.members) {const p=prospects.find(p=>p.id===id); const row=element('div',undefined,'member-row');row.append(element('span',p?.name||id),button('Remove','remove-'+c.id+'-'+id,async()=>{await api('/api/campaigns/'+c.id+'/members',{prospect_id:id,assigned:false});await loadWorkspace();render();draftNotice('Member removed.');}));box.append(row);}
    return box;
  });
  byId('campaign-list').replaceChildren(...(nodes.length?nodes:[element('p','No campaigns yet. Create a research cohort above.','empty-state')]));
}
function svgNode(tag,attrs,text) {const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v] of Object.entries(attrs)) n.setAttribute(k,String(v));if(text!==undefined)n.textContent=text;return n;}
function renderAnalytics() {
  if(!analytics) return;
  for(const [id,key] of [['kpi-contacted','contacted'],['kpi-replied','replied'],['kpi-opportunity','opportunity'],['kpi-due','followups_due']]) byId(id).textContent=String(analytics[key]);
  if(analytics.followups_due===null) byId('kpi-due').textContent='Refresh needed';
  byId('reply-rate').textContent=analytics.reply_rate===null?'No contact cohort':analytics.reply_rate+'% of contacted cohort';
  byId('opportunity-rate').textContent=analytics.opportunity_rate===null?'No contact cohort':analytics.opportunity_rate+'% of contacted cohort';
  byId('daily-progress').textContent=analytics.today_contacted+' / '+analytics.daily_target+' unique people manually logged as contacted today (UTC). Not discoveries or qualified candidates.';
  if(document.activeElement!==byId('daily-target')) byId('daily-target').value=String(analytics.daily_target);
  byId('cohort-note').textContent=analytics.replies_without_contact+' replied and '+analytics.opportunities_without_contact+' opportunity people have no contact event in this range; excluded from rate numerators.';
  const rows=analytics.daily; const series=['contacted','follow_up','replied','opportunity'];
  const max=Math.max(1,...rows.flatMap(r=>series.map(k=>r[k])));
  const hasActivity=rows.some(r=>series.some(k=>r[k]>0)); byId('chart-empty').hidden=hasActivity;
  const svg=svgNode('svg',{viewBox:'0 0 900 260',role:'img','aria-labelledby':'chart-title chart-desc'});
  svg.append(svgNode('title',{id:'chart-title'},'Daily manually logged outreach events, UTC'),svgNode('desc',{id:'chart-desc'},rows.map(r=>r.date+': '+series.map(k=>k+' '+r[k]).join(', ')).join('; ')));
  for(let i=0;i<5;i++){const y=20+i*47;svg.append(svgNode('line',{x1:45,x2:880,y1:y,y2:y,class:'chart-grid'}),svgNode('text',{x:5,y:y+4,class:'chart-label'},String(Math.round(max*(1-i/4)*10)/10)));}
  if(hasActivity) for(const key of series) svg.append(svgNode('polyline',{points:rows.map((r,i)=>(45+i*835/(rows.length-1))+','+(208-r[key]*188/max)).join(' '),fill:'none','stroke-width':2,class:'line-'+key}));
  for(const i of [...new Set([0,Math.floor(rows.length/2),rows.length-1])]) svg.append(svgNode('text',{x:45+i*835/(rows.length-1),y:245,'text-anchor':i===0?'start':i===rows.length-1?'end':'middle',class:'chart-label'},rows[i].date));
  byId('activity-chart').replaceChildren(svg);
}
byId('analytics-range').addEventListener('change',async()=>{try{analytics=await api('/api/analytics?days='+byId('analytics-range').value);renderAnalytics();}catch(e){draftNotice(e.message);}});
byId('create-campaign').addEventListener('click',async()=>{
  const b=byId('create-campaign'); if(b.disabled)return; b.disabled=true;
  const name=byId('campaign-name').value;
  try{if(!name.trim())throw new Error('Enter a campaign name');await api('/api/campaigns',{id:uniqueId('campaign'),name});if(byId('campaign-name').value===name)byId('campaign-name').value='';await loadWorkspace();render();draftNotice('Campaign created.');}catch(e){draftNotice(e.message);}finally{b.disabled=false;}
});
byId('save-target').addEventListener('click',async()=>{
  const b=byId('save-target');if(b.disabled)return;b.disabled=true;
  try{await api('/api/settings',{daily_target:Number(byId('daily-target').value)});analytics=await api('/api/analytics?days='+byId('analytics-range').value);renderAnalytics();draftNotice('Daily planning target saved.');}catch(e){draftNotice(e.message);}finally{b.disabled=false;}
});
load();
