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
  const filters = {health_min:0,health_max:100,value_min:0,value_max:100,engagement_min:0,engagement_max:100,deviation_min:.15,deviation_max:.5,deviation_direction:'all',deviation_telegram_only:false,metric:'all',audience_type:'',segment:''};
  let page=1, deviationPage=1, sort='health', sortDirection='asc', responseData=null, timer=null, controller=null, selectedGuest=null, detailController=null;
  let loading=false, selectedGuestConnected=false, ringAnimation=null, ringPending=false, rangeDrag=null;
  const chartSectors=new Map(), circumference=2*Math.PI*44;
  const audienceIcons={new:'+',churned:'↘',valuable_risk:'◆',low_engagement:'◇',loyal:'★',risk:'!',other:'•••'};
  const reducedMotion=window.matchMedia('(prefers-reduced-motion: reduce)');
  function animateRing(){
    ringAnimation?.cancel();
    const sectors=$('gpChartSectors');
    ringAnimation=sectors.animate(
      [{opacity:.18,transform:'scale(.9)'},{opacity:1,transform:'scale(1)'}],
      {duration:reducedMotion.matches?180:650,easing:'cubic-bezier(.25,.46,.45,.94)',iterations:1}
    );
  }
  function setLoading(value,animate=true){
    loading=value;
    $('gpChart').setAttribute('aria-busy',String(value));
    if(value&&animate)ringPending=true;
    if(!value)ringPending=false;
    updateButtons();
  }
  function updateButtons(){
    $('gpMail').disabled=loading||!responseData?.selected_telegram_count;
    $('gpInteract').disabled=loading||!responseData?.selected_telegram_count;
    $('gpDeviationInteract').disabled=loading||!responseData?.deviation_telegram_count;
    $('gpGuestInteract').disabled=!selectedGuestConnected;
  }
  function renderChart(data,refill=false){
    let offset=0;
    data.audiences.forEach(a=>{
      let state=chartSectors.get(a.key);
      if(!state){
        const el=document.createElementNS('http://www.w3.org/2000/svg','circle');
        for(const [k,v] of Object.entries({cx:120,cy:120,r:44,fill:'none',stroke:a.color,'stroke-width':88,'stroke-linecap':'butt',transform:'rotate(-90 120 120)',role:'button','stroke-dasharray':`0 ${circumference}`}))el.setAttribute(k,v);
        el.classList.add('gp-chart-sector');
        state={el,length:0,offset:0,tip:''};chartSectors.set(a.key,state);
        const showTip=()=>{$('gpChartTip').textContent=state.tip;};
        el.addEventListener('mouseenter',showTip);el.addEventListener('focus',showTip);
        el.addEventListener('click',()=>choose(a.key));
        el.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose(a.key);}});
        $('gpChartSectors').append(el);
      }
      const length=data.total?circumference*a.count/data.total:0;
      state.tip=`${a.label}: ${num(a.count)} · с Telegram ${num(a.telegram_count)} · без Telegram ${num(a.without_telegram_count)}`;
      state.el.setAttribute('aria-label',state.tip);
      state.el.setAttribute('tabindex',a.count?'0':'-1');
      state.el.setAttribute('aria-hidden',String(!a.count));
      state.el.style.pointerEvents=a.count?'':'none';
      state.el.style.opacity=filters.audience_type&&filters.audience_type!==a.key?'.25':'1';
      state.length=length;state.offset=offset;
      state.el.setAttribute('stroke-dasharray',`${length} ${Math.max(0,circumference-length)}`);
      state.el.setAttribute('stroke-dashoffset',-offset);
      offset+=length;
    });
    if(refill)animateRing();
  }

  function error(message){$('gpError').textContent=message;$('gpError').hidden=!message;if(message)$('gpError').scrollIntoView({block:'center',behavior:'smooth'});}
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
  const sortHeader = (key,label,title='') => {
    const active=sort===key, direction=active?sortDirection:'none';
    const arrow=active?(sortDirection==='asc'?'↑':'↓'):'↕';
    return `<th aria-sort="${direction==='asc'?'ascending':direction==='desc'?'descending':'none'}"${title?` title="${esc(title)}"`:''}><button type="button" class="gp-sort ${active?'is-active':''}" data-sort="${key}">${esc(label)}<span aria-hidden="true">${arrow}</span></button></th>`;
  };
  const metricLabel = {health:'П',value:'Ц',engagement:'В'};
  const signed = (value,suffix='') => `${value>0?'+':''}${num(value)}${suffix}`;
  const change = (d) => {
    const points=d.deviation_points??(d.score-d.baseline_30d);
    const percent=d.deviation_percent??((d.deviation_direction==='UP'?1:-1)*d.deviation_ratio*100);
    return `<div class="${d.deviation_direction==='UP'?'gp-up':'gp-down'}"><b>${metricLabel[d.metric]||esc(d.metric)}</b>: норма ${num(d.baseline_30d)} → сейчас ${num(d.score)} <strong>${signed(points,' п.')} (${signed(percent,'%')})</strong>${d.baseline_estimated?' <small>≈ норма восстановлена</small>':''}</div>`;
  };
  function renderDeviationRule(){
    const direction={all:'рост и снижение',up:'только рост',down:'только снижение'}[filters.deviation_direction];
    const contact=filters.deviation_telegram_only?' Только гости с Telegram.':'';
    $('gpDeviationRule').textContent=`Показаны ${direction} от ${num(filters.deviation_min*100)}% до ${num(filters.deviation_max*100)}% от личной нормы.${contact}`;
  }
  function render(data,refill=false){
    responseData=data;
    $('gpUpdated').textContent=data.calculated_at?`${data.stale?'Данные устарели · ':''}${date(data.calculated_at)} · время клуба`:'Ожидается первый расчёт';
    $('gpDistributionTotal').textContent=num(data.total);
    $('gpSelectionCount').textContent=`Для рассылки: ${num(data.selected_telegram_count)} · только с Telegram`;
    $('gpChartTip').textContent=data.audiences.find(a=>a.key===filters.audience_type)?.label || 'Выберите сектор или карточку группы';
    $('gpAudienceList').innerHTML=data.audiences.map(a=>{
      const percent=data.total?Math.round(a.count/data.total*100):0;
      return `<button type="button" class="gp-audience ${filters.audience_type===a.key?'is-active':''}" data-audience="${a.key}" aria-pressed="${filters.audience_type===a.key}" style="--audience-color:${a.color}"><span class="gp-audience-icon" aria-hidden="true">${audienceIcons[a.key]||'•'}</span><span class="gp-audience-body"><span class="gp-label">${esc(a.label)}</span><span class="gp-audience-number"><strong>${num(a.count)}</strong><span>гостей · ${percent}%</span></span><span class="gp-audience-contact">С Telegram ${num(a.telegram_count)} · без Telegram ${num(a.without_telegram_count)}</span></span><span class="gp-audience-open" aria-hidden="true">→</span></button>`;
    }).join('');
    $('gpDistributionLegend').innerHTML=data.audiences.map(a=>{
      const percent=data.total?Math.round(a.count/data.total*100):0;
      return `<button type="button" data-audience="${a.key}" class="gp-legend-row ${filters.audience_type===a.key?'is-active':''}" aria-label="${esc(a.label)}: ${num(a.count)} гостей, ${percent}%"><i style="background:${a.color}"></i><span>${esc(a.label)}</span><strong>${num(a.count)}</strong><small>${percent}%</small></button>`;
    }).join('');
    renderChart(data,refill);
    $('gpGuestsPanel').hidden=!filters.audience_type&&!filters.segment;
    document.querySelector('.gp-audiences').hidden=!$('gpGuestsPanel').hidden;
    $('gpGuestsTitle').textContent=data.audiences.find(a=>a.key===filters.audience_type)?.label || $('gpSegment').selectedOptions[0].textContent;
    $('gpGuestsCount').textContent=`${num(data.selected_count)} гостей · с Telegram ${num(data.selected_telegram_count)} · без Telegram ${num(data.selected_without_telegram_count)}`;
    $('gpGuests').innerHTML=data.guests.length?`<table class="gp-table"><thead><tr>${sortHeader('name','Гость')}${sortHeader('health','П','Посещения')}${sortHeader('value','Ц','Ценность')}${sortHeader('engagement','В','Вовлечённость')}${sortHeader('overall','Общий балл','П 35% + Ц 40% + В 25%')}</tr></thead><tbody>${data.guests.map(r=>`<tr><td>${person(r)}</td><td>${score(r.health.score)}</td><td>${score(r.value.score)}</td><td>${score(r.engagement.score)}</td><td class="gp-overall-cell">${score(r.overall?.score)}</td></tr>`).join('')}</tbody></table>`:'<div class="gp-empty">Нет гостей с такими показателями. Попробуйте расширить диапазоны.</div>';
    pagination($('gpGuestPages'),page,data.selected_count,p=>{page=p;load({animate:false});});
    $('gpDeviationCount').textContent=`${num(data.deviation_count)} гостей с отклонениями · с Telegram ${num(data.deviation_telegram_count)} · без Telegram ${num(data.deviation_count-data.deviation_telegram_count)}`;
    renderDeviationRule();
    $('gpDeviations').innerHTML=data.deviations.length?data.deviations.map(r=>`<article class="gp-deviation-row">${person(r)}<div class="gp-triple"><span>П <b>${num(r.health.score)}</b></span><span>Ц <b>${num(r.value.score)}</b></span><span>В <b>${num(r.engagement.score)}</b></span></div><div class="gp-deviation-change">${r.deviations.map(change).join('')}</div></article>`).join(''):'<div class="gp-empty">Нет подходящих отклонений или пока недостаточно истории оценок.</div>';
    pagination($('gpDeviationPages'),deviationPage,data.deviation_count,p=>{deviationPage=p;load({animate:false});});
  }
  async function load({animate=true}={}){
    clearTimeout(timer);controller?.abort();controller=new AbortController();const own=controller;
    error('');setLoading(true,animate);
    try{const data=await api('/owner/api/guest-pulse?'+new URLSearchParams({...filters,page,deviation_page:deviationPage,sort,sort_direction:sortDirection}),{signal:own.signal});if(own===controller){render(data,animate||ringPending);setLoading(false);}}
    catch(e){if(own===controller&&e.name!=='AbortError'){responseData=null;ringAnimation?.cancel();setLoading(false);error(e.message);}}
  }
  function choose(key){filters.audience_type=filters.audience_type===key?'':key;page=1;load();}
  function syncRange(key){
    const percent=key==='deviation',factor=percent?100:1;
    const low=Math.round(filters[key+'_min']*factor),high=Math.round(filters[key+'_max']*factor);
    const track=document.querySelector(`[data-slider="${key}"]`),limit=percent?Math.max(100,high):100;
    track.style.setProperty('--range-low',`${low/limit*100}%`);
    track.style.setProperty('--range-high',`${high/limit*100}%`);
    for(const [bound,value] of [['min',low],['max',high]]){
      document.querySelectorAll(`[data-key="${key}_${bound}"]`).forEach(input=>{
        if(input.type==='range'){
          input.max=limit;
          input.setAttribute('aria-valuemin',bound==='min'?0:low);
          input.setAttribute('aria-valuemax',bound==='min'?high:limit);
          input.setAttribute('aria-valuenow',value);
        }
        input.value=value;
      });
    }
  }
  document.querySelectorAll('[data-key]').forEach(input=>input.addEventListener('input',()=>{
    if(input.value==='')return;
    const key=input.dataset.key,group=key.replace(/_(min|max)$/,''),percent=group==='deviation';
    const factor=percent?100:1,limit=percent?10000:100;
    let value=Math.max(0,Math.min(limit,Math.round(Number(input.value))));
    if(!Number.isFinite(value))return;
    value=key.endsWith('_min')?Math.min(value,Math.round(filters[group+'_max']*factor)):Math.max(value,Math.round(filters[group+'_min']*factor));
    filters[key]=value/factor;syncRange(group);
    page=1;deviationPage=1;controller?.abort();setLoading(true,!percent);clearTimeout(timer);
    if(rangeDrag?.input===input){rangeDrag.changed=true;return;}
    timer=setTimeout(()=>load({animate:!percent}),250);
  }));
  document.querySelectorAll('input[type=number][data-key]').forEach(input=>input.addEventListener('blur',()=>syncRange(input.dataset.key.replace(/_(min|max)$/, ''))));
  function trackValue(track,clientX){
    const rect=track.getBoundingClientRect(),limit=Number(track.querySelector('input').max);
    return Math.round(Math.max(0,Math.min(1,(clientX-rect.left-10)/(rect.width-20)))*limit);
  }
  function moveRange(event){
    const drag=rangeDrag;if(!drag||drag.pointerId!==event.pointerId)return;
    const value=trackValue(drag.track,event.clientX);
    if(Number(drag.input.value)===value)return;
    if(drag.overlap){
      const [low,high]=drag.track.querySelectorAll('input');
      drag.input=value<Number(low.value)?low:high;drag.overlap=false;drag.input.focus({preventScroll:true});
    }
    drag.input.value=value;drag.input.dispatchEvent(new Event('input',{bubbles:true}));
  }
  document.querySelectorAll('.gp-dual-range').forEach(track=>{
    track.addEventListener('pointerdown',event=>{
      if(event.button!==0)return;
      event.preventDefault();
      const [low,high]=track.querySelectorAll('input'),value=trackValue(track,event.clientX);
      const input=Math.abs(value-Number(low.value))<Math.abs(value-Number(high.value))?low:high;
      rangeDrag={input,track,pointerId:event.pointerId,changed:false,overlap:low.value===high.value};
      input.focus({preventScroll:true});track.setPointerCapture(event.pointerId);moveRange(event);
    });
    track.addEventListener('pointermove',moveRange);
  });
  function finishRangeDrag(event){
    const drag=rangeDrag;
    if(!drag||drag.pointerId!==event.pointerId)return;
    rangeDrag=null;
    if(!drag.changed)return;
    clearTimeout(timer);timer=setTimeout(()=>load({animate:!drag.input.dataset.key.startsWith('deviation_')}),150);
  }
  document.addEventListener('pointerup',finishRangeDrag);
  document.addEventListener('pointercancel',finishRangeDrag);
  ['health','value','engagement','deviation'].forEach(syncRange);
  $('gpAudienceList').addEventListener('click',e=>{const b=e.target.closest('[data-audience]');if(b)choose(b.dataset.audience);});
  $('gpDistributionLegend').addEventListener('click',e=>{const b=e.target.closest('[data-audience]');if(b)choose(b.dataset.audience);});
  document.querySelectorAll('[name=gpMetric]').forEach(input=>input.addEventListener('change',()=>{filters.metric=input.value;deviationPage=1;load({animate:false});}));
  document.querySelectorAll('[name=gpDeviationDirection]').forEach(input=>input.addEventListener('change',()=>{filters.deviation_direction=input.value;deviationPage=1;renderDeviationRule();load({animate:false});}));
  $('gpDeviationTelegram').addEventListener('change',event=>{filters.deviation_telegram_only=event.target.checked;deviationPage=1;renderDeviationRule();load({animate:false});});
  $('gpSegment').addEventListener('change',e=>{filters.segment=e.target.value;page=1;load();});
  $('gpReset').addEventListener('click',()=>{for(const k of ['health','value','engagement']){filters[k+'_min']=0;filters[k+'_max']=100;document.querySelectorAll(`[data-key="${k}_min"]`).forEach(e=>e.value=0);document.querySelectorAll(`[data-key="${k}_max"]`).forEach(e=>e.value=100);}['health','value','engagement'].forEach(syncRange);filters.audience_type='';filters.segment='';$('gpSegment').value='';page=1;load();});
  $('gpAllTypes').addEventListener('click',()=>{filters.audience_type='';filters.segment='';$('gpSegment').value='';page=1;load();});
  $('gpRefresh').addEventListener('click',()=>load());
  async function handoff(mode){
    if(mode==='guest'?!selectedGuestConnected:loading||!responseData)return;
    const buttons=[$('gpMail'),$('gpInteract'),$('gpDeviationInteract'),$('gpGuestInteract')];buttons.forEach(b=>b.disabled=true);
    try{const result=await api('/owner/api/guest-pulse/selection',{method:'POST',body:JSON.stringify({filters,mode,guest_id:selectedGuest})});$('gpGuestDialog').close();window.crmOpenGuestPulseInteraction(result.group);updateButtons();}
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
      const r=data.guest,h=r.health,v=r.value,e=r.engagement,o=r.overall||{},f=r.visits,g=r.games||{}; $('gpGuestName').textContent=r.name;
      const gameName=value=>value==='cs2'?'Counter-Strike 2':value==='dota2'?'Dota 2':'—';
      const gameValue=(slug,hours)=>slug?`${gameName(slug)}${hours==null?'':` · ${num(hours)} ч`}`:'—';
      const deviations=responseData?.deviations.find(x=>x.guest_id===Number(id))?.deviations||[];
      $('gpGuestDetail').innerHTML=`<div class="gp-detail-status">${esc(r.lifecycle_label)} · ${esc(r.phone||'Номер не указан')}</div>${deviations.length?`<div class="gp-detail-note">Причина попадания в отклонения:${deviations.map(change).join('')}</div>`:''}
        <section class="gp-overall-card"><div><span>Общий балл гостя</span><strong>${num(o.score)}${o.score==null?'':'<small> / 100</small>'}</strong><b>${esc(o.label||'Недостаточно данных')}</b></div><p>${o.score==null?'Баллу нужны все три оценки: П, Ц и В.':`П ${num(h.score)} × 35% + Ц ${num(v.score)} × 40% + В ${num(e.score)} × 25%`}</p></section>
        <div class="gp-detail-scores"><section class="gp-detail-card"><h3>Посещения (П)</h3><strong>${num(h.score)} ${h.delta_14d==null?'':`<small>${h.delta_14d>=0?'↑':'↓'}${num(Math.abs(h.delta_14d))} за 14 дней</small>`}</strong><small>${h.score==null?'Недостаточно данных':h.preliminary?'Предварительная оценка':'Привычка посещений'}</small>${dl([['Давность',num(h.recency)+' / 100'],['Частота',num(h.frequency)+' / 100'],['Тренд',num(h.trend)+' / 100'],['Регулярность',num(h.consistency)+' / 100'],['7 дней назад',num(h.score_7d_ago)],['14 дней назад',num(h.score_14d_ago)],['30 дней назад',num(h.score_30d_ago)]])}</section>
        <section class="gp-detail-card"><h3>Ценность (Ц)</h3><strong>${num(v.score)}</strong><small>Относительная ценность в этом клубе</small>${dl([['Пополнения · 90 дней',num(v.revenue_90d)+' ₽'],['Игровые часы · 90 дней',num(v.played_hours_90d)],['Визиты · 90 дней',num(v.visits_90d)],['Пополнения на визит',num(v.avg_check_90d)+' ₽'],['Выше гостей по полнениям',num(v.percentiles.revenue_90d)+'%'],['Выше гостей по часам',num(v.percentiles.played_hours_90d)+'%'],['Выше гостей по визитам',num(v.percentiles.visits_90d)+'%'],['Выше гостей по среднему',num(v.percentiles.avg_check_90d)+'%'],['База сравнения',num(v.reference_count)]])}</section>
        <section class="gp-detail-card"><h3>Вовлечённость (В)</h3><strong>${num(e.score)}</strong><small>Активность в Кибер Бонус</small>${dl([['Telegram',r.has_telegram?'Подключён':'Не подключён'],['Задания · 30 дней',num(e.missions_completed_30d)],['Контракты выбраны · 30 дней',num(e.contracts_selected_30d)],['Контракты выполнены · 30 дней',num(e.contracts_completed_30d)],['Все действия · 30 дней',num(e.cb_actions_30d)],['Дней активности подряд',num(e.current_streak)],['Последняя активность',date(e.last_cb_activity_at)]])}</section>
        <section class="gp-detail-card"><h3>Игровой профиль</h3><strong>${gameName(g.favorite_game)}</strong><small>По данным Steam</small>${dl([['Любимая игра · всё время',gameValue(g.favorite_game,g.favorite_game_hours)],['Самая активная · 2 недели',gameValue(g.recent_game_14d,g.recent_game_14d_hours)],['Данные обновлены',date(g.updated_at)]])}</section></div>
        <p class="gp-detail-note">${esc(h.reason_text)}</p>
        ${dl([['Последний визит',date(f.last_visit_date)],['Обычный интервал',num(f.typical_gap_days)+' дн.'],['Всего визитов',num(f.visits_total)]])}
        <div class="gp-detail-note">Восстановленные оценки основаны на сохранённых событиях. Вовлечённость за прошлые дни приблизительная: Telegram считается подключённым с первой сохранённой авторизации или активности. Игровые часы рассчитаны без перерывов; пополнения не равны бухгалтерской выручке.</div>
        <details class="gp-detail-history"><summary>Ежедневные оценки · ${data.history.length}</summary><table><thead><tr><th>Дата</th><th title="Посещения">П</th><th title="Ценность">Ц</th><th title="Вовлечённость">В</th><th>Источник</th></tr></thead><tbody>${data.history.map(x=>`<tr><td>${esc(x.snapshot_date)}</td><td>${num(x.health_score)}</td><td>${num(x.value_score)}</td><td>${num(x.engagement_score)}</td><td>${x.reconstructed?'Восстановлено':'Снимок'}</td></tr>`).join('')}</tbody></table></details>
        <details class="gp-detail-history"><summary>Переходы статуса · ${data.events.length}</summary>${data.events.map(x=>`<p>${esc(date(x.changed_at))} · ${esc(x.from_status||'Начало')} → ${esc(x.to_status)}${x.reconstructed?' · восстановлено':''}</p>`).join('')}</details>`;
      selectedGuestConnected=r.has_telegram;updateButtons();
      $('gpGuestInteract').textContent=r.has_telegram?'Взаимодействовать ↗':'Telegram не подключён';
    }catch(e){if(e.name!=='AbortError')$('gpGuestDetail').textContent=e.message;}
  }
  $('guestPulse').addEventListener('click',e=>{
    const sorter=e.target.closest('[data-sort]');
    if(sorter){
      const next=sorter.dataset.sort;
      if(sort===next)sortDirection=sortDirection==='asc'?'desc':'asc';
      else{sort=next;sortDirection=next==='name'?'asc':'desc';}
      page=1;load({animate:false});return;
    }
    const guest=e.target.closest('[data-guest]');if(guest)openGuest(guest.dataset.guest);
  });
  $('gpClose').addEventListener('click',()=>dialog.close());dialog.addEventListener('close',()=>detailController?.abort());
  dialog.addEventListener('click',e=>{if(e.target===dialog){const rect=dialog.getBoundingClientRect();if(e.clientX<rect.left||e.clientX>rect.right||e.clientY<rect.top||e.clientY>rect.bottom)dialog.close();}});
  const help=$('gpHelpDialog');let helpMotion=null,helpClosing=false;
  $('gpHelpOpen').addEventListener('click',()=>{
    helpMotion?.cancel();helpClosing=false;help.showModal();
    help.scrollTop=0;$('gpHelpOpen').setAttribute('aria-expanded','true');
    if(!reducedMotion.matches)helpMotion=help.animate([{transform:'translateX(100%)'},{transform:'translateX(0)'}],{duration:240,easing:'ease-out'});
  });
  function closeHelp(){
    if(helpClosing||!help.open)return;
    helpClosing=true;helpMotion?.cancel();
    const finish=()=>{help.close();helpClosing=false;$('gpHelpOpen').setAttribute('aria-expanded','false');};
    if(reducedMotion.matches){finish();return;}
    helpMotion=help.animate([{transform:'translateX(0)'},{transform:'translateX(100%)'}],{duration:180,easing:'ease-in'});
    helpMotion.onfinish=finish;
  }
  $('gpHelpClose').addEventListener('click',closeHelp);
  help.addEventListener('cancel',event=>{event.preventDefault();closeHelp();});
  help.addEventListener('click',event=>{
    if(event.target!==help)return;
    const rect=help.getBoundingClientRect();
    if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)closeHelp();
  });
  load();
})();
