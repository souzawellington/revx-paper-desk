'use strict';
const COLORS={D_executor:'#4ea1ff',A_c3:'#22c55e',A_c3_raw:'#a78bfa',B_bh_btc:'#f5b942'};
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const nf=(x,d=2)=>x==null||isNaN(x)?'—':Number(x).toLocaleString('pt-BR',{minimumFractionDigits:d,maximumFractionDigits:d});
const usd=(x,d=2)=>x==null?'—':(x<0?'−':'')+'$'+nf(Math.abs(x),d);
const sgn=(x,d=2)=>x==null?'—':(x>0?'+':x<0?'−':'')+'$'+nf(Math.abs(x),d);
const pct=(x,d=2)=>x==null?'—':(x>0?'+':x<0?'−':'')+nf(Math.abs(x*100),d)+'%';
const pctu=(x,d=1)=>x==null?'—':nf(x*100,d)+'%';
const cls=x=>x==null?'':x>0?'pos':x<0?'neg':'';
const pxd=x=>x==null?'—':x>=1000?nf(x,0):x>=10?nf(x,2):x>=1?nf(x,3):nf(x,4);
const stateTxt=s=>{s=String(s||'');if(s.startsWith('KILLED'))return['PARADO (kill)','bad'];if(s.startsWith('PAUSED'))return['PAUSADO','wait'];if(s.startsWith('RUNNING'))return['RODANDO','ok'];return[s,''];};
let chart,series={};
function ensureChart(){if(chart)return;const LW=window.LightweightCharts;
 chart=LW.createChart($('chart'),{autoSize:true,layout:{background:{color:'transparent'},textColor:'#8a96ad',attributionLogo:false},
  grid:{vertLines:{color:'#1a2232'},horzLines:{color:'#1a2232'}},rightPriceScale:{borderColor:'#232c3d'},
  timeScale:{borderColor:'#232c3d',timeVisible:true,secondsVisible:false},localization:{locale:'pt-BR',
  timeFormatter:t=>new Date(t*1000).toLocaleString('pt-BR',{timeZone:'Europe/London',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})}});
 const base=chart.addSeries(LW.LineSeries,{color:'#55607a',lineWidth:1,lineStyle:2,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
 series.__base=base;}
function drawChart(bots){ensureChart();const LW=window.LightweightCharts;let tmin=Infinity,tmax=0;
 for(const b of bots){if(!b.available)continue;const k=b.key;
  if(!series[k])series[k]=chart.addSeries(LW.LineSeries,{color:COLORS[k],lineWidth:2,title:b.short,priceLineVisible:false});
  const data=(b.curve||[]).map(([t,v])=>({time:t,value:v}));series[k].setData(data);
  if(data.length){tmin=Math.min(tmin,data[0].time);tmax=Math.max(tmax,data[data.length-1].time);}}
 if(tmax)series.__base.setData(tmin<tmax?[{time:tmin,value:65},{time:tmax,value:65}]:[{time:tmax,value:65}]);
 $('legend').innerHTML=bots.filter(b=>b.available).map(b=>`<span><i style="background:${COLORS[b.key]}"></i>${esc(b.short)} ${esc(b.name.split('·')[1]||'')}</span>`).join('')+'<span><i style="background:#55607a"></i>$65 inicial</span>';}
function posTable(ps,isD){if(!ps.length)return'<div class="mut">Nenhuma posição aberta.</div>';
 return`<div class="scroll"><table><tr><th>Moeda</th><th>Entrada</th><th>Stop</th><th>Alvo</th><th>Atual</th><th>Não realiz.</th></tr>${ps.map(p=>
 `<tr><td>${esc(p.coin)}</td><td>${pxd(p.entry)}</td><td>${pxd(p.stop)}</td><td>${p.tp==null?'—':pxd(p.tp)}</td><td>${pxd(p.price)}</td><td class="${cls(p.unrealized)}">${sgn(p.unrealized)} <span class="mut">${pct(p.unrealized_pct,1)}</span></td></tr>`).join('')}</table></div>`;}
function tradesTable(ts){if(!ts.length)return'<div class="mut">Nenhuma operação ainda.</div>';
 return`<div class="scroll"><table><tr><th>Quando</th><th>Moeda</th><th>Lado</th><th>Preço</th><th>Resultado</th></tr>${ts.map(t=>
 `<tr><td>${esc(t.ts||'')}</td><td>${esc(t.coin)}</td><td>${esc(t.side)}<div class="mut">${esc(t.status)}${t.reason?' · '+esc(t.reason):''}</div></td><td>${pxd(t.price)}</td><td class="${cls(t.pnl)}">${t.pnl==null?(t.notional?usd(t.notional):'—'):sgn(t.pnl)}</td></tr>`).join('')}</table></div>`;}
function critList(cs){return`<div class="scroll"><table><tr><th>Critério de morte</th><th>Agora</th><th>Status</th></tr>${cs.map(c=>{
 const k=c.tripped?'bad':c.status==='OK'?'ok':'wait';return`<tr><td>${esc(c.name)}${c.info?' <span class="mut">(só aviso)</span>':''}<div class="mut">limite ${esc(c.limit)}</div></td><td style="white-space:normal;max-width:160px">${esc(c.value)}</td><td><span class="pill ${k}">${esc(c.status)}</span></td></tr>`}).join('')}</table></div>`;}
function botCard(b){if(!b.available)return`<section class="card"><h2>${esc(b.name)}</h2><div class="mut">${esc(b.state)}</div></section>`;
 const [st,sc]=stateTxt(b.state);const tripped=b.criteria.filter(c=>c.tripped&&!c.info).length;
 return`<section class="card" style="border-top:3px solid ${COLORS[b.key]}"><div class="row"><h2>${esc(b.name)}</h2><span class="pill ${sc}">${esc(st)}</span></div>
 <div class="row"><span class="big">${usd(b.equity)}</span><span class="${cls(b.pnl)}" style="font-weight:700">${sgn(b.pnl)} (${pct(b.pnl_pct)})</span></div>
 <div class="kv"><span>Queda do pico</span><b class="${b.drawdown>0.1?'neg':''}">${pctu(b.drawdown,2)}</b><span>Falta p/ teto $${nf(b.ceiling,0)}</span><b>${usd(b.to_ceiling)}</b></div>
 <div class="bar"><i style="width:${Math.max(0.5,Math.min(100,(b.ceiling_progress||0)*100))}%"></i></div>
 <div class="mut">${pctu(b.ceiling_progress,1)} do teto${b.ceiling_latched?' · <b class="warn">TETO ATINGIDO: pausado</b>':''} · última rodada ${esc(b.last_run||'—')}</div>
 <h2 style="margin-top:10px">Posições abertas</h2>${posTable(b.positions,b.key==='D_executor')}
 <details><summary>Operações recentes (${b.recent.length})</summary>${tradesTable(b.recent)}</details>
 <details ${tripped?'open':''}><summary>Critérios de morte: ${tripped?`<b class="neg">${tripped} disparou</b>`:'nenhum disparou'}</summary>${critList(b.criteria)}</details></section>`;}
function deskCard(d){if(!d||d.error)return`<h2>Mesa / auditor</h2><div class="mut">${esc(d&&d.error||'indisponível')}</div>`;
 const t=d.thresholds,c=d.checks,ok=x=>x?'<span class="pill ok">OK</span>':'<span class="pill wait">ainda não</span>';
 return`<div class="row"><h2>Mesa (diário paper) · progresso do auditor</h2><span class="pill ${d.go?'ok':'wait'}">${d.go?'GO':'ainda sem GO'}</span></div>
 <div class="bar"><i style="width:${Math.min(100,d.n/t.threshold_trades*100)}%;background:var(--y)"></i></div>
 <div class="scroll"><table><tr><th>Métrica</th><th>Agora</th><th>Precisa</th><th></th></tr>
 <tr><td>Operações</td><td>${d.n}</td><td>≥ ${t.threshold_trades}</td><td>${ok(c.trades)}</td></tr>
 <tr><td>Taxa de acerto</td><td>${pctu(d.win_rate)}</td><td>≥ ${pctu(t.threshold_win_rate,0)}</td><td>${ok(c.win_rate)}</td></tr>
 <tr><td>Expectativa</td><td>${nf(d.expectancy_r,3)}R</td><td>≥ +${nf(t.threshold_expectancy_r,1)}R</td><td>${ok(c.expectancy_r)}</td></tr>
 <tr><td>Queda máxima</td><td>${pctu(d.max_dd,2)}</td><td>≤ ${pctu(t.threshold_max_dd,0)}</td><td>${ok(c.max_dd)}</td></tr></table></div>
 <div class="mut">Ensaio acelerado (paper_fast): ${d.fast.n} operações · acerto ${pctu(d.fast.win_rate)} · ${nf(d.fast.expectancy_r,3)}R. O GO só vem com todas as metas OK.</div>
 <details><summary>Posições abertas da mesa (${d.open.length})</summary>${d.open.length?`<div class="scroll"><table><tr><th>Moeda</th><th>Entrada</th><th>Stop</th><th>Alvo</th><th>Aberta</th></tr>${d.open.map(p=>`<tr><td>${esc(p.coin)}</td><td>${pxd(p.entry)}</td><td>${pxd(p.stop)}</td><td>${pxd(p.tp)}</td><td>${esc(p.opened||'')}</td></tr>`).join('')}</table></div>`:'<div class="mut">Nenhuma.</div>'}</details>
 <details><summary>Resultados recentes (${d.results.length})</summary>${d.results.length?`<div class="scroll"><table><tr><th>Quando</th><th>Moeda</th><th>R</th><th>Saída</th></tr>${d.results.map(r=>`<tr><td>${esc(r.ts)}</td><td>${esc(r.coin)}</td><td class="${cls(r.r)}">${r.r==null?'—':(r.r>0?'+':'')+nf(r.r,2)+'R'}</td><td>${esc(r.note)}</td></tr>`).join('')}</table></div>`:'<div class="mut">Nenhum.</div>'}</details>`;}
async function tick(){try{const r=await fetch('/api/live',{cache:'no-store',credentials:'same-origin'});if(!r.ok)throw new Error('HTTP '+r.status);
 const s=await r.json();$('upd').textContent=s.now_london;$('mode').textContent='modo: '+(s.execution_mode==='live'?'⚠ LIVE':'simulado ('+s.execution_mode+')');
 const P=s.prices;$('prices').innerHTML=Object.entries(P.px||{}).sort().map(([k,v])=>`<span><b>${esc(k.replace('-USD',''))}</b> $${pxd(v.mid)} <span class="${cls(v.chg24)}">${pct(v.chg24,1)}</span></span>`).join('')||'<span class="mut">sem preços</span>';
 $('pxinfo').innerHTML=P.stale?`<span class="warn">${esc(P.error||'preços desatualizados')}${P.updated?' · último bom '+esc(P.updated):''}</span>`:`há ${nf(P.age_s,0)} s`;
 $('bots').innerHTML=s.bots.map(botCard).join('');$('desk').innerHTML=deskCard(s.desk);drawChart(s.bots);$('errs').innerHTML='';}
 catch(e){$('errs').innerHTML=`<div class="err">Sem ligação ao painel (${esc(e.message)}). Tentando de novo…</div>`;}}
tick();setInterval(tick,30000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)tick();});
