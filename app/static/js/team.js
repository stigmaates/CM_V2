(() => {
'use strict';
const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=v=>new Intl.NumberFormat('ru-RU').format(v||0);
const pct=v=>v===null?'—':`${num(v)}%`;
let today=null, controller=null;
const stateText={HTTP_403:'API-ключ не имеет доступа к сотрудникам или сменам.',langame_club_mapping_required:'Нужно сопоставить клуб с Langame.',invalid_shift_dates:'Langame вернул некорректные даты смен.'};
function render(data){
 today=data.today;
 for(const key of ['registration','cohort']){const range=data[key+'_range'];$(key+'From').value=range[0];$(key+'To').value=range[1];$(key+'From').max=today;$(key+'To').max=today;}
 $('teamStatus').textContent=(data.updated_at?`Смены обновлены: ${data.updated_at.replace('T',' ')} · ${data.timezone}`:'Смены ещё не загружены.')+(data.error?' '+(stateText[data.error]||'Ошибка обновления смен. Сохранённые данные могут быть неполными.'):(data.stale?' · Данные смен требуют обновления.':''));
 const total={name:'Итого',admin_id:'total',club_registrations:0,module_registrations:0,module_estimated:0,cohort:0,visit1:0,visit2:0,visit3:0};
 data.admins.forEach(a=>Object.keys(total).filter(k=>typeof total[k]==='number').forEach(k=>total[k]+=a[k]));
 total.conversion12=total.visit1?Math.round(total.visit2/total.visit1*1000)/10:null;total.conversion23=total.visit2?Math.round(total.visit3/total.visit2*1000)/10:null;
 const all=[...data.admins,total];
 const identity=a=>`<strong>${esc(a.name)}</strong>${a.admin_id!==null&&a.admin_id!=='total'?`<small>ID ${esc(a.admin_id)}${a.work_schedule?' · '+esc(({day:'Дневные смены',night:'Ночные смены'})[a.work_schedule]||a.work_schedule):''}${a.admin_status?' · '+esc(({active:'Активен',inactive:'Неактивен',blocked:'Заблокирован'})[a.admin_status]||a.admin_status):''}</small>`:''}`;
 const cls=a=>a.admin_id===null?'team-unknown':a.admin_id==='total'?'team-total':'';
 $('teamRegistrations').innerHTML=all.map(a=>`<tr class="${cls(a)}"><td>${identity(a)}</td><td><strong>${num(a.club_registrations)}</strong></td><td><strong>${num(a.module_registrations)}</strong>${a.module_estimated?`<small>из них ≈ ${num(a.module_estimated)}</small>`:''}</td></tr>`).join('');
 $('teamFunnel').innerHTML=all.map(a=>`<tr class="${cls(a)}"><td>${identity(a)}</td>${['cohort','visit1','visit2','visit3'].map(k=>`<td><strong>${num(a[k])}</strong></td>`).join('')}<td>${pct(a.conversion12)}</td><td>${pct(a.conversion23)}</td></tr>`).join('');
 $('teamCoverage').textContent=`≈ — дата модуля восстановлена приблизительно. Без даты регистрации, вне расчёта периода: в клубе ${num(data.unknown_club_dates)}, в модуле ${num(data.unknown_module_dates)}.`;
}
async function load(){
 controller?.abort();controller=new AbortController();const own=controller;
 const params=new URLSearchParams();for(const key of ['registration','cohort']){if($(key+'From').value)params.set(key+'_from',$(key+'From').value);if($(key+'To').value)params.set(key+'_to',$(key+'To').value);}
 $('teamError').hidden=true;$('teamStatus').textContent='Обновляем отчёт…';document.querySelectorAll('.team button').forEach(b=>b.disabled=true);
 try{const response=await fetch('/owner/api/team?'+params,{signal:own.signal,headers:{Accept:'application/json'}});const data=await response.json();if(!response.ok||!data.ok)throw Error(data.error||'Не удалось загрузить отчёт');if(controller===own)render(data);}
 catch(e){if(e.name!=='AbortError'){$('teamError').textContent=e.message||'Не удалось загрузить отчёт';$('teamError').hidden=false;$('teamStatus').textContent='Отчёт не обновлён. Показаны предыдущие результаты, если они были загружены.';}}
 finally{if(controller===own)document.querySelectorAll('.team button').forEach(b=>b.disabled=false);}
}
document.querySelectorAll('[data-range]').forEach(panel=>{
 const key=panel.dataset.range;
 panel.querySelector('[data-apply]').addEventListener('click',load);
 panel.querySelectorAll('[data-preset]').forEach(button=>button.addEventListener('click',()=>{
  if(!today)return;const d=new Date(today+'T12:00:00Z');
  if(button.dataset.preset==='month')d.setUTCDate(1);else d.setUTCDate(d.getUTCDate()-((d.getUTCDay()+6)%7));
  $(key+'From').value=d.toISOString().slice(0,10);$(key+'To').value=today;load();
 }));
});
$('teamRefresh').addEventListener('click',load);load();
})();
