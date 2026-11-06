/* Real display functions in isolation. No service, model, or data processing. */
const fs = require('fs'), path = require('path'), vm = require('vm'), assert = require('assert/strict');
const root = path.join(__dirname, '../../cecropis/web/static/js');
const elements = new Map();
const node = () => ({isConnected:true,children:[],dataset:{},textContent:'',innerHTML:'',value:'',disabled:false,nextElementSibling:null,attributes:{},
  setAttribute(name,value){this.attributes[name]=value;},append(...nodes){this.children.push(...nodes);},replaceChildren(...nodes){this.children=[...nodes];},addEventListener(){},after(){},remove(){}});
const element = id => {
  if (!elements.has(id)) elements.set(id,node());
  return elements.get(id);
};
const context = {console, Intl, Map, Set, Error, JSON, Event:class {}, CustomEvent:class {},
  navigator:{languages:['en']}, localStorage:{getItem:()=>null, setItem:()=>{}},
  matchMedia:()=>({matches:false, addEventListener:()=>{}}),
  document:{documentElement:{dataset:{}}, dispatchEvent:()=>{}, addEventListener:()=>{}, body:null,createElement:node,getElementById:id=>elements.get(id)},
  $:element, busy:false, protocolEdited:()=>{}, setTimeout:()=>{}, groupLock:()=>{}};
context.window = context;
vm.createContext(context);
for (const file of ['ui_messages.js','ui_preferences.js']) vm.runInContext(fs.readFileSync(path.join(root,file),'utf8'), context);
const UI = context.UI;
function source(file, start, end) {
  const text = fs.readFileSync(path.join(root,file),'utf8');
  assert(text.includes(start) && text.includes(end), file);
  return text.slice(text.indexOf(start), text.indexOf(end, text.indexOf(start)));
}
async function check(name, run) {
  try { await run(); console.log('PASS '+name); }
  catch(error) { console.error('FAIL '+name+': '+error.message); process.exitCode=1; }
}
(async () => {
  await check('observation names are strings and unique after deletion/custom edits', () => {
    let rows;
    context.rawProtocolRows=()=>rows;
    context.observationRow=o=>{assert.equal(typeof o.name,'string'); return o.name;};
    vm.runInContext(source('protocol_ui.js', "$('add_observation').onclick", "document.addEventListener('click'"), context);
    for (const names of [['Observation 2'], ['custom','Observation 3'], ['Observation 1','Observation 2']]) {
      rows=names.map(name=>({name,body_ids:[]}));
      element('add_observation').onclick();
      assert.equal(new Set(rows.map(o=>o.name)).size,rows.length);
    }
  });
  await check('removing an observation works when the translated button text is clicked', () => {
    const listeners=[];
    const add=context.document.addEventListener;
    context.document.addEventListener=(name,callback)=>listeners.push(callback);
    const rows=[{name:'first'},{name:'keep'}];
    context.rawProtocolRows=()=>rows;
    context.observationRow=o=>o.name;
    context.eventRow=o=>o;
    vm.runInContext(source('protocol_ui.js', "document.addEventListener('click', event => {", "$('replace_single_input').onclick"),context);
    listeners[0]({target:{dataset:{},closest:()=>({dataset:{deleteObservation:'0'}})}});
    assert.deepEqual(rows.map(o=>o.name),['keep']);
    context.document.addEventListener=add;
  });
  await check('renamed observation aria labels retain the new user text after language changes', () => {
    const listeners={};
    for(const id of ['input_events','observations']) element(id).addEventListener=(name,callback)=>{listeners[id]=callback;};
    const start=node(),stop=node();
    start.dataset.i18nLabel='protocol.observationRow.start_update_8092fd';
    stop.dataset.i18nLabel='protocol.observationRow.stop_4ff4d5';
    const row={querySelector:selector=>selector.includes('evaluation_start')?start:stop};
    vm.runInContext(source('protocol_ui.js', "for (const id of ['input_events', 'observations'])", "document.addEventListener('change'"),context);
    listeners.observations({target:{dataset:{field:'name'},value:'用户新名称 23',closest:()=>row}});
    for(const language of UI.languages){
      UI.language(language);UI.apply({querySelectorAll:()=>[]});
      assert(start.attributes['aria-label'].includes('用户新名称 23'));
      assert(stop.attributes['aria-label'].includes('用户新名称 23'));
      assert.equal(JSON.parse(start.attributes['data-i18n-label-params']).p0,'用户新名称 23');
    }
  });
  await check('explicit adoption preserves edited drafts on cancel and applies only after confirmation', () => {
    const applied=[];let routed=0;
    context.workButton=(key,action)=>({onclick:action});
    context.apply=config=>applied.push(config);
    context.changed=()=>{};context.workConfig=()=>{routed++;};
    context.replayClone=config=>JSON.parse(JSON.stringify(config));
    context.workflowDraftEdited=true;
    context.confirm=()=>false;
    const adopt=vm.runInContext('(()=>{const config={steps:32};'+source('workflow_ui.js', "const adopt = workButton('use.adopt'", 'adopt.disabled =')+'return adopt;})()',context);
    adopt.onclick();assert.equal(applied.length,0);assert.equal(routed,0);
    context.confirm=()=>true;
    adopt.onclick();assert.equal(applied.length,1);assert.equal(routed,1);
    context.workflowDraftEdited=false;
    context.confirm=()=>{throw Error('Unedited drafts need no confirmation');};
    adopt.onclick();assert.equal(applied.length,2);
  });
  await check('failed jobs without details remain failed in all languages', async () => {
    context.groupURL=x=>x; context.api=async()=>({status:'failed'});
    context.groupStatus=value=>UI.text(element('group_status'),value);
    vm.runInContext(source('group_ui.js','async function groupPoll()', 'function groupKnown'),context);
    for (const language of UI.languages) {
      UI.preferences.language=language; context.groupJob='test';
      await context.groupPoll();
      assert(element('group_status').textContent.includes(UI.t('group.groupPoll.failed_28384d')));
      assert(!element('group_status').textContent.includes(UI.t('group.groupPoll.cancelled_a37778')));
    }
  });
  await check('search mismatch retains a message binding across repeated updates', () => {
    context.searchResult={_signature:'old'}; context.searchSignature=()=> 'new';
    context.searchJob=null; context.searchRunning=false;
    UI.preferences.language='en';
    UI.text(element('search_status'),UI.msg('comparison.ready',{conditions:2,observations:2}));
    vm.runInContext(source('scope_ui.js','let searchStatusMessage', 'renderSearch = function'),context);
    vm.runInContext(source('scope_ui.js','function markSearchMismatch()', 'function scheduleCandidatePreview'),context);
    context.markSearchMismatch(); context.markSearchMismatch();
    UI.language('zh-CN'); UI.apply({querySelectorAll:()=>[]});
    assert(!element('search_status').textContent.includes('observation sets'));
    const message=UI.currentText(element('search_status'));
    assert.notEqual(typeof message,'string');
  });
  await check('known and unknown errors retain translated summary and raw detail', () => {
    for (const language of UI.languages) {
      UI.preferences.language=language;
      const known=UI.error('error.scope_required');
      assert.equal(String(UI.errorText(known)),UI.t('error.scope_required'));
      const unknown=UI.errorText(new Error('technical detail 10310'));
      assert.equal(String(unknown),UI.t('error.request'));
      assert.equal(unknown.technical,'technical detail 10310');
    }
  });
  await check('dynamic aria labels and numbers retain raw parameters in six languages', () => {
    const target=node();
    const amplitude=.123456789;
    UI.attr(target,'aria-label',UI.msg('editor.bodyIds',{role:UI.msg('protocol.collectionCell.input_events_409b10'),number:1}));
    for (const language of UI.languages) {
      UI.language(language); UI.apply({querySelectorAll:()=>[]});
      assert.equal(target.attributes['aria-label'],UI.t('editor.bodyIds',{role:UI.msg('protocol.collectionCell.input_events_409b10'),number:1}));
      assert.equal(JSON.stringify(UI.numeric(amplitude)),String(amplitude));
      assert(UI.htmlAttribute('aria-label','editor.bodyIds',{role:UI.msg('protocol.collectionCell.input_events_409b10'),number:1}).includes('data-i18n-label-params'));
    }
  });
  await check('saving failures can retry and delayed saves cannot claim a different result', async () => {
    context.comparisonSavingId=null;context.status=()=>{};context.renderComparisonUsability=()=>{};
    context.comparison={comparison_id:'first',rows:[{name:'用户原文'}],protocol:{outputs:['O']}};
    context.comparisonView={origin:'calculated',artifactId:null};
    vm.runInContext(source('protocol_ui.js','function canSaveComparison()', 'function renderComparison(r,'),context);
    vm.runInContext(source('workbench.js',"$('save_comparison').onclick",'const spatial = new SkeletonView'),context);
    context.api=async()=>{throw Error('Injected save failure');};
    await element('save_comparison').onclick();
    assert.equal(context.comparisonView.origin,'calculated');assert(context.canSaveComparison());
    context.api=async()=>({artifact_id:'saved-first'});
    await element('save_comparison').onclick();
    assert.equal(context.comparisonView.artifactId,'saved-first');assert(!context.canSaveComparison());
    context.comparisonView={origin:'calculated',artifactId:null};
    let finish;
    context.api=()=>new Promise(resolve=>finish=resolve);
    const pending=element('save_comparison').onclick();
    context.comparison={comparison_id:'second',rows:[],protocol:{outputs:[]}};
    context.comparisonView={origin:'calculated',artifactId:null};
    finish({artifact_id:'late-save-for-first'});await pending;
    assert.equal(context.comparisonView.artifactId,null);
    context.comparisonView={origin:'search-preview',artifactId:null};assert(!context.canSaveComparison());
  });
  await check('report previews reject stale languages; failed exports remain retryable', async () => {
    context.busy=false;context.comparison={comparison_id:'report-source'};
    context.curveSource={comparison_id:'report-source'};context.conditionSelected=new Set();
    element('report_condition_mode').value='all';
    const reportSource=fs.readFileSync(path.join(root,'workspace_ui.js'),'utf8');
    vm.runInContext(reportSource.slice(reportSource.indexOf('let reportPreviewHandle')),context);
    UI.language('en');let finish;
    context.api=()=>new Promise(resolve=>finish=resolve);
    const pending=element('report_preview').onclick();
    UI.language('ja');vm.runInContext('invalidateReportPreview()',context);
    finish({preview_id:'obsolete',language:'en',total_bytes:12,sizes:{},preview_html:'<html lang="en">'});await pending;
    assert.equal(vm.runInContext('reportPreviewHandle',context),null);
    context.api=async()=>({preview_id:'ja-preview',language:'ja',total_bytes:12,sizes:{},preview_html:'<html lang="ja">'});
    await element('report_preview').onclick();
    assert.equal(vm.runInContext('reportPreviewHandle.language',context),'ja');
    context.api=async()=>{throw Error('Injected export failure');};
    await element('report_export').onclick();assert(!element('report_export').disabled);
    context.api=async()=>({language:'ja',files:{'report.html':'/local-file'},sizes:{'report.html':12}});
    await element('report_export').onclick();assert(element('report_export').disabled);
    assert.equal(vm.runInContext('reportDisplay.phase',context),'exported');
  });
})();
