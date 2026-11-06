"use strict";

/* The same readiness report in the small setup page and workspace details. */
window.DataPreparation = (() => {
  const message = issue => UI.htmlText('prep.' + issue.code, issue.params || {});
  // Canonicalize structured diagnostics, including nested details. Translation
  // and object insertion order must not decide whether two issues are equal.
  function diagnosticKey(value) {
    if (Array.isArray(value)) return value.map(diagnosticKey);
    if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(key => [key, diagnosticKey(value[key])]));
    return value;
  }
  function render(host, report) {
    const seen = new Set();
    const issues = [...report.issues, ...(report.index.issues || []),
      ...(!report.ready ? report.raw.issues || [] : [])].filter(issue => {
        const key = JSON.stringify(diagnosticKey(issue));
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });
    const rows = [
      ['prep.index',UI.htmlText('prep.status.'+report.index.status)],
      ['prep.optionalGeometry',UI.htmlText(report.optional.skeletons_available?'prep.boundGeometry':'prep.noGeometry')]
    ];
    const diagnostics=issues.map(issue=>'<li>'+message(issue)+(issue.params?.detail?'<details><summary>'+UI.htmlText('prep.technical')+'</summary><pre>'+UI.escape(issue.params.detail)+'</pre></details>':'')+'</li>').join('');
    const dependencyDetails=report.dependencies.filter(d=>!d.available&&d.detail).map(d=>'<pre>'+UI.escape(d.name+': '+d.detail)+'</pre>').join('');
    host.innerHTML='<h3>'+UI.htmlText('prep.'+(report.ready?'ready':report.next_action))+'</h3><div class="tablewrap"><table class="prep-status-table"><tbody>'+rows.map(([key,value])=>'<tr><th>'+UI.htmlText(key)+'</th><td>'+value+'</td></tr>').join('')+'</tbody></table></div><ul class="preparation-issues">'+diagnostics+'</ul>';
    if(dependencyDetails)host.innerHTML+='<details><summary>'+UI.htmlText('prep.technical')+'</summary>'+dependencyDetails+'</details>';
  }
  return {render};
})();

document.addEventListener('DOMContentLoaded', () => {
  if (!window.preparationInitial) return;
  const $ = id => document.getElementById(id), initial = window.preparationInitial;
  let result = null, sequence = 0, requestFeedback = null;
  function feedback(value) { requestFeedback=value; UI.text($('preparation_status'),value); }
  const languages = [['zh-CN','简体中文'],['en','English'],['ja','日本語'],['fr','Français'],['de','Deutsch'],['es','Español']];
  for (const [id,key,values,current] of [['prep_language','preference.language',languages,UI.preferences.language],['prep_theme','preference.theme',[['light','theme.menuLight'],['dark','theme.menuDark'],['system','theme.menuSystem']],UI.preferences.theme]]) {
    const select=document.createElement('select');select.id=id;UI.attr(select,'aria-label',UI.msg(key));
    for (const [value,label] of values) {
      const option=document.createElement('option');option.value=value;
      if(id==='prep_language'){option.lang=value;option.textContent=label;}else{option.dataset.i18n=label;UI.text(option,UI.msg(label));}
      select.append(option);
    }
    select.value=current;select.onchange=()=>id==='prep_language'?UI.language(select.value):UI.setTheme(select.value);
    $('preparation_preferences').append(select);
  }
  for(const field of ['raw','index','cases','runs','skeletons','skeleton_cache']){
    const label=document.createElement('label'),caption=document.createElement('span'),input=document.createElement('input');
    caption.dataset.i18n='prep.path.'+field;input.type='text';input.dataset.path=field;input.value=initial.paths[field]||'';
    label.append(caption,input);$(field.startsWith('skeleton')?'preparation_geometry':field==='index'?'preparation_paths':'preparation_storage').append(label);
  }
  $('binding_back').hidden=!initial.back;
  function payload(){return {paths:{...Object.fromEntries(Object.entries(initial.paths).filter(([key])=>['geometry'].includes(key))),...Object.fromEntries([...document.querySelectorAll('[data-path]')].map(input=>[input.dataset.path,input.value.trim()]).filter(([,value])=>value))},output:initial.output,remember:$('preparation_remember').checked};}
  function display(){
    document.title='Cecropis · '+UI.t('prep.title');
    if(requestFeedback){UI.text($('preparation_status'),requestFeedback);return;}
    if(!result)return;
    DataPreparation.render($('preparation_status'),result.preparation);
    $('preparation_open').disabled=!result.preparation.ready;
    $('binding_forget').hidden=result.memory?.status==='missing';
    UI.text($('binding_status'),UI.msg((result.memory?.status==='invalid'||(result.memory?.matches&&!result.preparation.ready))?'binding.invalid':result.memory?.matches?'binding.saved':'binding.notRemembered'));
    UI.apply();
  }
  async function request(action){
    const epoch=++sequence;requestFeedback=null;$('preparation_open').disabled=true;
    if(action==='open')$('preparation_form').inert=true;
    try{
      const response=await fetch('/api/preparation/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-Local-Token':initial.token},body:JSON.stringify(payload())});
      const data=await response.json();if(epoch!==sequence)return;
      if(!response.ok){$('preparation_form').inert=false;feedback(UI.errorText(UI.error(data.code==='memorySaveFailed'?'binding.saveFailed':data.code==='workspaceBusy'?'binding.busy':'prep.operationFailed',{},data.detail||data.code)));if(result?.preparation)$('preparation_open').disabled=!result.preparation.ready;return;}
      if(action==='forget'){$('preparation_remember').checked=false;await request('check');return;}
      if(action==='open'){
        $('preparation_form').inert=true;
        feedback(UI.msg('prep.opening'));
        // The same foreground service releases its setup listener, then opens the workbench.
        for(let attempt=0;attempt<40;attempt++){
          if(epoch!==sequence)return;
          try{const ready=await fetch('/api/workspace',{cache:'no-store'});if(ready.ok){location.reload();return;}}catch{}
          await new Promise(resolve=>setTimeout(resolve,250));
        }
        feedback(UI.msg('prep.openFailed'));
        return;
      }
      result=data;display();
    }catch(error){if(epoch===sequence){$('preparation_form').inert=false;feedback(UI.errorText(UI.error('error.request',{},error.message)));}}
  }
  $('preparation_form').onsubmit=event=>{event.preventDefault();request('check');};
  $('preparation_open').onclick=()=>request('open');
  $('binding_forget').onclick=()=>request('forget');
  $('preparation_form').addEventListener('input',event=>{if(!event.target.dataset.path)return;sequence++;result=null;$('preparation_open').disabled=true;feedback(UI.msg('prep.edited'));});
  document.addEventListener('ui-language',()=>{ $('prep_language').value=UI.preferences.language;display(); });
  document.addEventListener('ui-theme',()=>{ $('prep_theme').value=UI.preferences.theme; });
  UI.apply();request('check');
});

