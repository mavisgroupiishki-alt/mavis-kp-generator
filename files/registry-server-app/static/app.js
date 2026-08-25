(() => {
  const SOURCE_ORDER=['spk2','att','attoff','iso','metal','osp','lic'];
  const SOURCE_LABELS={spk2:'СПК',att:'Действующие аттестаты',attoff:'Отменённые / прекращённые аттестаты',iso:'ISO / СУОТ',metal:'Сертификаты / декларации продукции',osp:'ОСП / сварочное производство',lic:'Лицензии'};
  const boot=window.MAVIS_BOOTSTRAP||{};
  const $=id=>document.getElementById(id); const q=$('query'),btn=$('searchBtn'),state=$('state'),candidates=$('candidates'),result=$('result'),freshness=$('freshness'),dealContext=$('dealContext'),setupState=$('setupState'),heroText=$('heroText');
  function esc(v){return String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));}
  function normalizeName(v){return String(v||'').toLowerCase().replaceAll('ё','е').replace(/[«»“”„"'`]/g,' ').replace(/[^a-zа-я0-9\s-]/g,' ').replace(/\s+/g,' ').trim().replace(/^(общество с ограниченной ответственностью|открытое акционерное общество|закрытое акционерное общество|частное унитарное предприятие|совместное общество с ограниченной ответственностью|ооо|оао|зао|чуп|уп|сооо|ип)\s+/,'').trim();}
  function setState(msg,err=false){state.classList.remove('hidden','error'); if(err)state.classList.add('error'); state.textContent=msg;}
  function clearState(){state.classList.add('hidden');state.classList.remove('error');}
  function dateRu(v){if(!v)return ''; const d=new Date(v); return Number.isNaN(d.getTime())?String(v):d.toLocaleDateString('ru-RU');}
  function expiryInfo(v){if(!v)return{text:'срок не указан',cls:''};const d=new Date(v);if(Number.isNaN(d.getTime()))return{text:String(v),cls:''};const days=Math.ceil((d-Date.now())/86400000);if(days<0)return{text:`истёк ${dateRu(v)}`,cls:'expiry-bad'};if(days<=60)return{text:`до ${dateRu(v)} (${days} дн.)`,cls:'expiry-warn'};return{text:`до ${dateRu(v)}`,cls:'expiry-ok'};}
  async function api(path){const r=await fetch(path,{cache:'no-store'});const d=await r.json().catch(()=>({}));if(!r.ok){const e=new Error(d.message||`HTTP ${r.status}`);e.status=r.status;throw e;}return d;}
  function safeUrl(v){try{const u=new URL(String(v||''),window.location.origin);return (u.protocol==='http:'||u.protocol==='https:')?u.href:'';}catch{return '';} }
  function validSpkEndpoint(v){return /^\/RegisterDocument\/Get[A-Za-z0-9_]+DocumentContent$/.test(String(v||''));}
  function spkPreviewSrcdoc(content){return `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0;padding:14px;font-family:Inter,Arial,sans-serif;color:#182230;background:#fff;font-size:13px;line-height:1.35}.certificate-document-scroll{overflow:auto;max-width:100%}table{border-collapse:collapse;min-width:100%;width:max-content}th,td{vertical-align:top}img{max-width:100%}</style></head><body>${String(content||'')}</body></html>`;}
  function spkAttachmentsHtml(d){const cur=Array.isArray(d.attachments_current)?d.attachments_current:[],arc=Array.isArray(d.attachments_archive)?d.attachments_archive:[];if(!cur.length&&!arc.length)return '';const uid='spk'+Math.random().toString(36).slice(2,10);const list=(arr,section)=>arr.length?arr.map((a,i)=>{const docId=String(a.document_id||'');const endpoint=String(a.content_endpoint||'');const canPreview=/^\d+$/.test(docId)&&validSpkEndpoint(endpoint);const detail=safeUrl(a.detail_url||d.url);const pid=`${uid}-${section}-${i}`;return `<div class="spk-file"><div class="spk-file-main"><span class="spk-file-icon">▤</span><span class="spk-file-name">${esc(a.name||'Документ')}</span>${a.type?`<span class="spk-file-type">${esc(a.type)}</span>`:''}</div><div class="spk-file-actions">${canPreview?`<button type="button" class="spk-eye" data-target="${pid}" data-doc-id="${esc(docId)}" data-endpoint="${esc(endpoint)}" title="Показать / скрыть область">👁</button>`:(detail?`<a class="spk-eye-link" href="${esc(detail)}" target="_blank" rel="noopener" title="Открыть карточку в реестре">👁</a>`:'')}</div></div>${canPreview?`<div id="${pid}" class="spk-preview hidden"><div class="spk-preview-head"><div><div class="spk-preview-kicker">Область просмотра документа</div><strong>${esc(a.name||'Документ')}</strong></div><span class="spk-file-type">${esc(a.type||'FILE')}</span></div><div class="spk-preview-state">Нажмите на глазик, чтобы загрузить область.</div><iframe title="${esc(a.name||'Документ')}" sandbox></iframe></div>`:''}`;}).join(''):`<div class="spk-files-empty">Документы не найдены</div>`;return `<div class="spk-attachments" data-tabs="${uid}"><div class="spk-tabs"><button type="button" class="spk-tab-btn active" data-pane="${uid}-current">Актуальные документы <span>${cur.length}</span></button><button type="button" class="spk-tab-btn" data-pane="${uid}-archive">Архив документов <span>${arc.length}</span></button></div><div id="${uid}-current" class="spk-tab-pane">${list(cur,'current')}</div><div id="${uid}-archive" class="spk-tab-pane hidden">${list(arc,'archive')}</div></div>`;}
  function wireSpkDocuments(){result.querySelectorAll('.spk-eye').forEach(btn=>btn.addEventListener('click',async()=>{const pane=document.getElementById(btn.dataset.target);if(!pane)return;const opening=pane.classList.contains('hidden');if(!opening){pane.classList.add('hidden');btn.classList.remove('active');return;}pane.classList.remove('hidden');btn.classList.add('active');const frame=pane.querySelector('iframe');const st=pane.querySelector('.spk-preview-state');if(frame?.dataset.loaded==='1')return;if(st){st.classList.remove('error');st.textContent='Загружаю область из официального реестра СПК…';}btn.disabled=true;try{const data=await api(`/api/spk-document?id=${encodeURIComponent(btn.dataset.docId||'')}&endpoint=${encodeURIComponent(btn.dataset.endpoint||'')}`);if(!frame)throw new Error('Не найден блок предпросмотра');frame.srcdoc=spkPreviewSrcdoc(data.content||'');frame.dataset.loaded='1';if(st)st.classList.add('hidden');}catch(err){if(st){st.classList.remove('hidden');st.classList.add('error');st.textContent='Не удалось загрузить область: '+err.message;}}finally{btn.disabled=false;}}));result.querySelectorAll('.spk-tab-btn').forEach(btn=>btn.addEventListener('click',()=>{const box=btn.closest('.spk-attachments');if(!box)return;box.querySelectorAll('.spk-tab-btn').forEach(x=>x.classList.remove('active'));box.querySelectorAll('.spk-tab-pane').forEach(x=>x.classList.add('hidden'));btn.classList.add('active');document.getElementById(btn.dataset.pane)?.classList.remove('hidden');}));}
  function docHtml(d){const ex=expiryInfo(d.expiry_date),meta=[];if(d.issue_date)meta.push(`<div><span class="meta-label">Выдан:</span>${esc(dateRu(d.issue_date))}</div>`);if(d.expiry_date)meta.push(`<div><span class="meta-label">Срок:</span><span class="${ex.cls}">${esc(ex.text)}</span></div>`);if(d.status)meta.push(`<div><span class="meta-label">Статус:</span>${esc(d.status)}</div>`);if(d.category)meta.push(`<div><span class="meta-label">Категория:</span>${esc(d.category)}</div>`);if(d.source==='spk2'&&d.issuer)meta.push(`<div><span class="meta-label">Кем выдано:</span>${esc(d.issuer)}</div>`);const url=safeUrl(d.url);const link=url?`<a class="registry-link" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${d.url_kind==='direct'?'Открыть карточку в реестре ↗':'Открыть реестр ↗'}</a>`:'';const attachments=d.source==='spk2'?spkAttachmentsHtml(d):'';const activity=(d.activity&&!attachments)?`<div class="activity">${esc(d.activity)}</div>`:'';return `<div class="doc"><div class="doc-number">${esc(d.number||'Документ без номера')}</div>${d.organization?`<div class="doc-org">${esc(d.organization)}</div>`:''}${meta.length?`<div class="doc-meta">${meta.join('')}</div>`:''}${activity}${attachments}${link}</div>`;}
  function renderEntity(e){const docs=e.documents||{},total=Object.values(docs).reduce((n,a)=>n+(a?.length||0),0),recs=[];if((docs.attoff||[]).length)recs.push({t:'Найдены отменённые / прекращённые аттестаты — проверить актуальность перед предложением.',alert:true});for(const [s,label] of [['spk2','СПК'],['att','аттестацию организации'],['iso','ISO / СУОТ'],['osp','ОСП'],['lic','лицензию'],['metal','сертификацию продукции']])if(!(docs[s]||[]).length)recs.push({t:`В реестре не найдено: ${label}. Можно проверить потребность клиента.`});let cards='';for(const s of SOURCE_ORDER){const arr=docs[s]||[];cards+=`<section class="registry-card"><div class="registry-head"><div class="registry-title">${SOURCE_LABELS[s]}</div><span class="badge ${arr.length?(s==='attoff'?'bad':'ok'):'none'}">${arr.length?`Найдено: ${arr.length}`:'Не найдено'}</span></div>${arr.length?`<div class="docs">${arr.map(docHtml).join('')}</div>`:`<div class="empty">По этой компании записей в актуальном снимке реестра нет.</div>`}</section>`;}result.innerHTML=`<div class="company-card"><div><h2>${esc(e.name)}</h2><div class="company-meta">${e.unp?`УНП ${esc(e.unp)}`:'УНП в найденных записях не указан'}</div></div><div class="company-count">Документов в реестрах: ${total}</div></div><section class="recommendations"><h3>Подсказки</h3><div class="rec-list">${recs.length?recs.map(r=>`<div class="rec ${r.alert?'alert':''}">${esc(r.t)}</div>`).join(''):'<div class="rec">По основным реестрам документы найдены.</div>'}</div></section><div class="registry-grid">${cards}</div><div class="footer-note">Результат основан на последнем опубликованном снимке реестров. История запросов не сохраняется.</div>`;result.classList.remove('hidden');wireSpkDocuments();}
  let staleRetry=false;async function openEntity(id){candidates.classList.add('hidden');setState('Загружаю документы компании…');try{const e=await api(`/api/entity/${encodeURIComponent(id)}`);renderEntity(e);clearState();staleRetry=false;}catch(err){if(err.status===404&&!staleRetry){staleRetry=true;setState('Индекс только что обновился — повторяю поиск по свежей версии…');await doSearch(false);return;}staleRetry=false;setState('Не удалось загрузить карточку: '+err.message,true);}}
  function renderCandidates(items){candidates.innerHTML=`<div class="candidates-title">Найдено несколько компаний — выберите нужную</div>`+items.map(x=>`<div class="candidate" data-id="${esc(x.id)}"><div><div class="candidate-name">${esc(x.name)}</div><div class="candidate-unp">${x.unp?`УНП ${esc(x.unp)}`:'УНП в реестрах не найден'}</div></div><div class="candidate-open">Открыть →</div></div>`).join('');candidates.classList.remove('hidden');candidates.querySelectorAll('.candidate').forEach(n=>n.addEventListener('click',()=>openEntity(n.dataset.id)));}
  async function doSearch(auto=false){const raw=q.value.trim();result.classList.add('hidden');candidates.classList.add('hidden');if(!raw){setState('Введите УНП или название компании.');return;}btn.disabled=true;setState(auto?'Автоматически проверяю компанию из сделки…':'Ищу компанию по реестрам…');try{const d=await api(`/api/search?q=${encodeURIComponent(raw)}`),items=d.items||[];if(!items.length){setState(auto?'Компания из сделки не найдена в опубликованном снимке реестров. Можно изменить запрос вручную.':'Компания не найдена в опубликованном снимке реестров. Проверьте написание или попробуйте УНП.');return;}clearState();const digits=raw.replace(/\D/g,'');let exact=items.find(x=>digits.length===9&&x.unp===digits);if(!exact&&auto&&boot.deal?.company_name){const n=normalizeName(boot.deal.company_name); exact=items.find(x=>normalizeName(x.name)===n);}if(exact||items.length===1)await openEntity((exact||items[0]).id);else renderCandidates(items);}catch(err){setState('Ошибка проверки: '+err.message,true);}finally{btn.disabled=false;}}
  function bxCall(method, params={}){
    return new Promise((resolve,reject)=>{
      BX24.callMethod(method,params,(res)=>{
        if(res.error()) reject(new Error(`${res.error()}: ${res.error_description()||''}`));
        else resolve(res.data());
      });
    });
  }
  async function setupBitrixPlacement(){
    if(typeof BX24==='undefined') return;
    BX24.init(async function(){
      try{
        const info=await bxCall('app.info',{});
        let placements=await bxCall('placement.get',{});
        if(!Array.isArray(placements)) placements=[];
        let found=placements.find(x=>String(x.placement||x.PLACEMENT||'')==='CRM_DEAL_DETAIL_TAB');
        if(!found){
          await bxCall('placement.bind',{
            PLACEMENT:'CRM_DEAL_DETAIL_TAB',
            HANDLER:window.location.origin+'/deal-tab',
            TITLE:'Проверка реестров',
            LANG_ALL:{ru:{TITLE:'Проверка реестров'},en:{TITLE:'Registry check'}}
          });
          placements=await bxCall('placement.get',{});
          if(!Array.isArray(placements)) placements=[];
          found=placements.find(x=>String(x.placement||x.PLACEMENT||'')==='CRM_DEAL_DETAIL_TAB');
        }
        if(!found) throw new Error('placement.bind выполнен, но CRM_DEAL_DETAIL_TAB не найден в placement.get');
        setupState.classList.remove('hidden','ok','error');
        setupState.classList.add('ok');
        if(info && info.INSTALLED===false){
          setupState.textContent='Вкладка зарегистрирована. Завершаю установку приложения…';
          BX24.installFinish();
        }else{
          setupState.textContent='Вкладка «Проверка реестров» зарегистрирована. Перезагрузите карточку сделки.';
        }
      }catch(err){
        setupState.classList.remove('hidden','ok','error');
        setupState.classList.add('error');
        setupState.textContent='Настройка вкладки Bitrix24: '+err.message;
      }
    });
  }
  function renderBootstrap(){
    if(boot.setup&&Object.keys(boot.setup).length){setupState.classList.remove('hidden','ok','error'); setupState.classList.add(boot.setup.ok?'ok':'error'); setupState.textContent=boot.setup.message||'';}
    if(boot.error){setState(boot.error,true);}
    if(boot.mode==='deal'&&boot.deal){const d=boot.deal;dealContext.innerHTML=`<div class="deal-context-main"><div class="deal-kicker">Текущая сделка Bitrix24</div><div class="deal-company">${esc(d.company_name||d.deal_title||'Компания не определена')}</div><div class="deal-meta">${d.unp?`УНП ${esc(d.unp)} · `:''}Сделка #${esc(d.deal_id)}${d.category_name?` · ${esc(d.category_name)}`:''}</div></div>${d.warning?`<div class="deal-warning">${esc(d.warning)}</div>`:''}`;dealContext.classList.remove('hidden');heroText.textContent='Данные компании подставлены из текущей сделки. Проверка запускается автоматически.';q.value=d.query||'';setTimeout(()=>doSearch(true),120);}
  }
  btn.addEventListener('click',()=>doSearch(false));q.addEventListener('keydown',e=>{if(e.key==='Enter')doSearch(false);});
  api('/api/manifest').then(m=>{const d=m.updated_at?new Date(m.updated_at):null;freshness.textContent=d&&!Number.isNaN(d)?`Данные обновлены: ${d.toLocaleString('ru-RU')}`:'Данные загружены';}).catch(e=>{freshness.textContent='Не удалось загрузить базу';setState('Приложение не видит опубликованный индекс: '+e.message,true);});
  renderBootstrap();
  if(boot.mode!=='deal') setupBitrixPlacement();
})();
