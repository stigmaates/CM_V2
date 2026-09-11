(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num = (v) => v == null ? '—' : new Intl.NumberFormat('ru-RU',{maximumFractionDigits:1}).format(v);
  const date = (s) => {
    if (!s) return '—';
    const match = String(s).match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/);
    return match ? `${match[3]}.${match[2]}.${match[1]} ${match[4]}:${match[5]}` : String(s);
  };
  const score = (v) => `<span class="gp-score ${v!=null && v<40?'is-low':v>=75?'is-high':''}" title="${v==null?'Недостаточно данных':''}">${num(v)}</span>`;
  const filters = {health_min:0,health_max:100,value_min:0,value_max:100,engagement_min:0,engagement_max:100,deviation_min:.15,deviation_max:.5,metric:'all',audience_type:'',segment:''};
  let page=1, deviationPage=1, responseData=null, timer=null, controller=null, selectedGuest=null, detailController=null;
  let loading=false, selectedGuestConnected=false, chartFrame=null;
  const chartSectors=new Map(), circumference=2*Math.PI*91;
  const reducedMotion=window.matchMedia('(prefers-reduced-motion: reduce)');
  function setLoading(value){
    loading=value;
    document.querySelector('.gp-chart-block').classList.toggle('is-updating',value);
    $('gpChart').setAttribute('aria-busy',String(value));
    $('gpChartStatus').textContent=value?'Обновляем выборку…':'';
    updateButtons();
  }
  function updateButtons(){
    $('gpMail').disabled=loading||!responseData?.selected_telegram_count;
    $('gpInteract').disabled=loading||!responseData?.selected_telegram_count;
    $('gpDeviationInteract').disabled=loading||!responseData?.deviation_telegram_count;
    $('gpGuestInteract').disabled=!selectedGuestConnected;
  }
  function renderChart(data){
    cancelAnimationFrame(chartFrame);
    let offset=0;
    const transitions=data.audiences.map(a=>{
      let state=chartSectors.get(a.key);
      if(!state){
        const el=document.createElementNS('http://www.w3.org/2000/svg','circle');
        for(const [k,v] of Object.entries({cx:120,cy:120,r:91,fill:'none',stroke:a.color,'stroke-width':27,transform:'rotate(-90 120 120)',role:'button','stroke-dasharray':`0 ${circumference}`}))el.setAttribute(k,v);
        el.classList.add('gp-chart-sector');
        state={el,length:0,offset:0,tip:''};chartSectors.set(a.key,state);
        const showTip=()=>{$('gpChartTip').textContent=state.tip;};
        el.addEventListener('mouseenter',showTip);el.addEventListener('focus',showTip);
        el.addEventListener('click',()=>choose(a.key));
        el.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose(a.key);}});
        $('gpChart').append(el);
      }
      const length=data.total?circumference*a.count/data.total:0;
      state.tip=`${a.label}: ${num(a.count)} · с Telegram ${num(a.telegram_count)} · без Telegram ${num(a.without_telegram_count)}`;
      state.el.setAttribute('aria-label',state.tip);
      state.el.setAttribute('tabindex',a.count?'0':'-1');
      state.el.setAttribute('aria-hidden',String(!a.count));
      state.el.style.pointerEvents=a.count?'':'none';
      state.el.style.opacity=filters.audience_type&&filters.audience_type!==a.key?'.25':'1';
      const transition={state,fromLength:state.length,fromOffset:state.offset,length,offset};
      offset+=length;return transition;
    });
    const started=performance.now(),duration=reducedMotion.matches?0:520;
    function frame(now){
      const progress=duration?Math.min((now-started)/duration,1):1,ease=1-Math.pow(1-progress,3);
      transitions.forEach(t=>{
        t.state.length=t.fromLength+(t.length-t.fromLength)*ease;
        t.state.offset=t.fromOffset+(t.offset-t.fromOffset)*ease;
        t.state.el.setAttribute('stroke-dasharray',`${t.state.length} ${Math.max(0,circumference-t.state.length)}`);
        t.state.el.setAttribute('stroke-dashoffset',-t.state.offset);
      });
      if(progress<1)chartFrame=requestAnimationFrame(frame);
    }
    chartFrame=requestAnimationFrame(frame);
  }
  function error(message){$('gpError').textContent=message;$('gpError').hidden=!message;}
  async function api(url,options={}) {
    const response=await fetch(url,{headers:{Accept:'application/json','Content-Type':'application/json'},...options});
    if(!response.ok) {const data=await response.json().catch(()=>({}));throw new Error(data.error||'Не удалось загрузить данные. Обновите страницу.');}
    return response.json();
  }
  function pagination(container,current,total,fn){
    container.replaceChildren(); if(total<=responseData.page_size)return;
    const pages=Math.ceil(total/responseData.page_size);
    for(const [label,next] of [['←',current-1],[`${current} / ${pages}`,null],['→',current+1]]){
      const el=document.createElement(next===null?'span':'button');el.textContent=label;
      if(next!==null){el.type='button';el.disabled=next<1||next>pages;el.addEventListener('click',()=>fn(next));}
      container.append(el);
    }
  }
  const person = (r) => `<button class="gp-person" type="button" data-guest="${r.guest_id}">${esc(r.name)}<span>${esc(r.lifecycle_label)} · ${r.has_telegram?'С Telegram':'Без Telegram'}</span></button>`;
  const change = (d) => `<div class="${d.deviation_direction==='UP'?'gp-up':'gp-down'}">${esc(d.metric)}: ${num(d.baseline_30d)} → ${num(d.score)} <b>${d.deviation_direction==='UP'?'↑':'↓'}${num(d.deviation_ratio*100)}%</b>${d.baseline_estimated?' <small>≈ норма восстановлена</small>':''}</div>`;
  function render(data){
    responseData=data;
    $('gpUpdated').textContent=data.calculated_at?`${data.stale?'Данные устарели · ':''}${date(data.calculated_at)} · время клуба`:'Ожидается первый расчёт';
    $('gpTotal').textContent=num(data.selected_count);
    $('gpWithTelegram').textContent=num(data.selected_telegram_count);
    $('gpWithoutTelegram').textContent=num(data.selected_without_telegram_count);
    $('gpSelectionCount').textContent=`Для рассылки: ${num(data.selected_telegram_count)} · только с Telegram`;
    $('gpChartTip').textContent=data.audiences.find(a=>a.key===filters.audience_type)?.label || 'Выберите сектор или панель аудитории';
    $('gpAudienceList').innerHTML=data.audiences.map(a=>`<button type="button" class="gp-audience ${filters.audience_type===a.key?'is-active':''}" data-audience="${a.key}" aria-pressed="${filters.audience_type===a.key}" style="--audience-color:${a.color}"><span class="gp-audience-body"><span class="gp-label"><i class="gp-dot" style="background:${a.color}"></i>${esc(a.label)}</span><span class="gp-audience-telegram"><span>С Telegram <b>${num(a.telegram_count)}</b></span><span>Без Telegram <b>${num(a.without_telegram_count)}</b></span></span></span><span class="gp-audience-end"><strong>${num(a.count)} <small>/ ${num(a.total)}</small></strong><span class="gp-audience-open">Открыть <span aria-hidden="true">→</span></span></span></button>`).join('');
    renderChart(data);
    $('gpGuestsPanel').hidden=!filters.audience_type&&!filters.segment;
    document.querySelector('.gp-audiences').hidden=!$('gpGuestsPanel').hidden;
    $('gpGuestsTitle').textContent=data.audiences.find(a=>a.key===filters.audience_type)?.label || $('gpSegment').selectedOptions[0].textContent;
    $('gpGuestsCount').textContent=`${num(data.selected_count)} гостей · с Telegram ${num(data.selected_telegram_count)} · без Telegram ${num(data.selected_without_telegram_count)}`;
    $('gpGuests').innerHTML=data.guests.length?`<table class="gp-table"><thead><tr><th>Гость</th><th>H</th><th>V</th><th>E</th></tr></thead><tbody>${data.guests.map(r=>`<tr><td>${person(r)}</td><td>${score(r.health.score)}</td><td>${score(r.value.score)}</td><td>${score(r.engagement.score)}</td></tr>`).join('')}</tbody></table>`:'<div class="gp-empty">Нет гостей с такими показателями. Попробуйте расширить диапазоны.</div>';
    pagination($('gpGuestPages'),page,data.selected_count,p=>{page=p;load();});
    $('gpDeviationCount').textContent=`${num(data.deviation_count)} гостей с отклонениями · с Telegram ${num(data.deviation_telegram_count)} · без Telegram ${num(data.deviation_count-data.deviation_telegram_count)}`;
    $('gpDeviations').innerHTML=data.deviations.length?data.deviations.map(r=>`<article class="gp-deviation-row">${person(r)}<div class="gp-triple"><span>H <b>${num(r.health.score)}</b></span><span>V <b>${num(r.value.score)}</b></span><span>E <b>${num(r.engagement.score)}</b></span></div><div class="gp-deviation-change">${r.deviations.map(change).join('')}</div></article>`).join(''):'<div class="gp-empty">Нет подходящих отклонений или пока недостаточно истории оценок.</div>';
    pagination($('gpDeviationPages'),deviationPage,data.deviation_count,p=>{deviationPage=p;load();});
  }
  async function load(){
    clearTimeout(timer);controller?.abort();controller=new AbortController();const own=controller;
    error('');setLoading(true);
    try{const data=await api('/owner/api/guest-pulse?'+new URLSearchParams({...filters,page,deviation_page:deviationPage}),{signal:own.signal});if(own===controller){render(data);setLoading(false);}}
    catch(e){if(own===controller&&e.name!=='AbortError'){responseData=null;setLoading(false);error(e.message);$('gpChartStatus').textContent='Не удалось обновить выборку';}}
  }
  function choose(key){filters.audience_type=filters.audience_type===key?'':key;page=1;load();}
  document.querySelectorAll('[data-key]').forEach(input=>input.addEventListener('input',()=>{
    const key=input.dataset.key,percent=key.startsWith('deviation_'),value=Number(input.value);filters[key]=percent?value/100:value;
    document.querySelectorAll(`[data-key="${key}"]`).forEach(other=>{if(other!==input)other.value=value;});
    page=1;deviationPage=1;controller?.abort();setLoading(true);clearTimeout(timer);timer=setTimeout(load,250);
  }));
  $('gpAudienceList').addEventListener('click',e=>{const b=e.target.closest('[data-audience]');if(b)choose(b.dataset.audience);});
  document.querySelectorAll('[name=gpMetric]').forEach(input=>input.addEventListener('change',()=>{filters.metric=input.value;deviationPage=1;load();}));
  $('gpSegment').addEventListener('change',e=>{filters.segment=e.target.value;page=1;load();});
  $('gpReset').addEventListener('click',()=>{for(const k of ['health','value','engagement']){filters[k+'_min']=0;filters[k+'_max']=100;document.querySelectorAll(`[data-key="${k}_min"]`).forEach(e=>e.value=0);document.querySelectorAll(`[data-key="${k}_max"]`).forEach(e=>e.value=100);}filters.audience_type='';filters.segment='';$('gpSegment').value='';page=1;load();});
  $('gpAllTypes').addEventListener('click',()=>{filters.audience_type='';filters.segment='';$('gpSegment').value='';page=1;load();});
  $('gpRefresh').addEventListener('click',load);
  async function handoff(mode){
    if(mode==='guest'?!selectedGuestConnected:loading||!responseData)return;
    const buttons=[$('gpMail'),$('gpInteract'),$('gpDeviationInteract'),$('gpGuestInteract')];buttons.forEach(b=>b.disabled=true);
    try{const result=await api('/owner/api/guest-pulse/selection',{method:'POST',body:JSON.stringify({filters,mode,guest_id:selectedGuest})});window.location.assign(result.url);}
    catch(e){error(e.message);$('gpGuestDialog').close();updateButtons();}
  }
  $('gpMail').addEventListener('click',()=>handoff('audience'));$('gpInteract').addEventListener('click',()=>handoff('audience'));$('gpDeviationInteract').addEventListener('click',()=>handoff('deviations'));$('gpGuestInteract').addEventListener('click',()=>handoff('guest'));
  const dl = (items) => `<dl class="gp-detail-list">${items.map(([k,v])=>`<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl>`;
  const dialog=$('gpGuestDialog');
  async function openGuest(id){
    selectedGuestConnected=false;selectedGuest=Number(id);detailController?.abort();detailController=new AbortController();const own=detailController;
    $('gpGuestName').textContent='Карточка гостя';$('gpGuestDetail').textContent='Загрузка…';$('gpGuestInteract').disabled=true;dialog.showModal();
    try{
      const data=await api(`/owner/api/guest-pulse/guests/${id}`,{signal:own.signal});if(own!==detailController)return;
      const r=data.guest,h=r.health,v=r.value,e=r.engagement,f=r.visits; $('gpGuestName').textContent=r.name;
      const deviations=responseData?.deviations.find(x=>x.guest_id===Number(id))?.deviations||[];
      $('gpGuestDetail').innerHTML=`<div class="gp-detail-status">${esc(r.lifecycle_label)} · ${esc(r.phone||'Номер не указан')}</div>${deviations.length?`<div class="gp-detail-note">Причина попадания в отклонения:${deviations.map(change).join('')}</div>`:''}
        <div class="gp-detail-scores"><section class="gp-detail-card"><h3>Health</h3><strong>${num(h.score)} ${h.delta_14d==null?'':`<small>${h.delta_14d>=0?'↑':'↓'}${num(Math.abs(h.delta_14d))} за 14 дней</small>`}</strong><small>${h.score==null?'Недостаточно данных':h.preliminary?'Предварительная оценка':'Привычка посещений'}</small>${dl([['Давность',num(h.recency)+' / 100'],['Частота',num(h.frequency)+' / 100'],['Тренд',num(h.trend)+' / 100'],['Регулярность',num(h.consistency)+' / 100'],['7 дней назад',num(h.score_7d_ago)],['14 дней назад',num(h.score_14d_ago)],['30 дней назад',num(h.score_30d_ago)]])}</section>
        <section class="gp-detail-card"><h3>Value</h3><strong>${num(v.score)}</strong><small>Относительная ценность в этом клубе</small>${dl([['Пополнения · 90 дней',num(v.revenue_90d)+' ₽'],['Игровые часы · 90 дней',num(v.played_hours_90d)],['Визиты · 90 дней',num(v.visits_90d)],['Пополнения на визит',num(v.avg_check_90d)+' ₽'],['Выше гостей по пополнениям',num(v.percentiles.revenue_90d)+'%'],['Выше гостей по часам',num(v.percentiles.played_hours_90d)+'%'],['Выше гостей по визитам',num(v.percentiles.visits_90d)+'%'],['Выше гостей по среднему',num(v.percentiles.avg_check_90d)+'%'],['База сравнения',num(v.reference_count)]])}</section>
        <section class="gp-detail-card"><h3>Engagement</h3><strong>${num(e.score)}</strong><small>Активность в Кибер Бонус</small>${dl([['Telegram',r.has_telegram?'Подключён':'Не подключён'],['Задания · 30 дней',num(e.missions_completed_30d)],['Игровые действия · 30 дней',num(e.cb_actions_30d)],['Дней активности подряд',num(e.current_streak)],['Последняя активность',date(e.last_cb_activity_at)]])}</section></div>
        <p class="gp-detail-note">${esc(h.reason_text)}</p>
        ${dl([['Последний визит',date(f.last_visit_date)],['Обычный интервал',num(f.typical_gap_days)+' дн.'],['Всего визитов',num(f.visits_total)]])}
        <div class="gp-detail-note">Восстановленные оценки основаны на сохранённых событиях. Engagement за прошлые дни приблизительный: Telegram считается подключённым с первой сохранённой авторизации или активности. Игровые часы рассчитаны без перерывов; пополнения не равны бухгалтерской выручке.</div>
        <details class="gp-detail-history"><summary>Ежедневные оценки · ${data.history.length}</summary><table><thead><tr><th>Дата</th><th>H</th><th>V</th><th>E</th><th>Источник</th></tr></thead><tbody>${data.history.map(x=>`<tr><td>${esc(x.snapshot_date)}</td><td>${num(x.health_score)}</td><td>${num(x.value_score)}</td><td>${num(x.engagement_score)}</td><td>${x.reconstructed?'Восстановлено':'Снимок'}</td></tr>`).join('')}</tbody></table></details>
        <details class="gp-detail-history"><summary>Переходы статуса · ${data.events.length}</summary>${data.events.map(x=>`<p>${esc(date(x.changed_at))} · ${esc(x.from_status||'Начало')} → ${esc(x.to_status)}${x.reconstructed?' · восстановлено':''}</p>`).join('')}</details>`;
      selectedGuestConnected=r.has_telegram;updateButtons();
      $('gpGuestInteract').textContent=r.has_telegram?'Взаимодействовать ↗':'Telegram не подключён';
    }catch(e){if(e.name!=='AbortError')$('gpGuestDetail').textContent=e.message;}
  }
  $('guestPulse').addEventListener('click',e=>{const b=e.target.closest('[data-guest]');if(b)openGuest(b.dataset.guest);});
  $('gpClose').addEventListener('click',()=>dialog.close());dialog.addEventListener('close',()=>detailController?.abort());
  dialog.addEventListener('click',e=>{if(e.target===dialog){const rect=dialog.getBoundingClientRect();if(e.clientX<rect.left||e.clientX>rect.right||e.clientY<rect.top||e.clientY>rect.bottom)dialog.close();}});
  load();
})();
