let SYM=null, pxChart=null, pxSeries=null, pxMarkers=null, pxStop=null, ddChart=null, ddSeries=null;
let DCOIN=null, DTF=240, dChart=null, dCandle=null, dMarkers=null, dLines=[], eqChart=null, eqPaper=null, eqReplay=null;
const f=(x,d=2)=>x==null||isNaN(x)?'–':Number(x).toLocaleString('pt-BR',{maximumFractionDigits:d,minimumFractionDigits:Math.min(d,2)});
const pct=x=>x==null?'–':(x*100).toFixed(2)+'%';
const t=s=>new Date(s*1000).toLocaleString('pt-BR');
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
// TradingView Lightweight Charts v5 (vendorizado em /vendor; Apache-2.0; attributionLogo ligado)
const LW=window.LightweightCharts;
const LWOPT={layout:{background:{type:'solid',color:'#151821'},textColor:'#8a90a2',attributionLogo:true},
  grid:{vertLines:{color:'#1e2230'},horzLines:{color:'#1e2230'}},rightPriceScale:{borderColor:'#232838'},
  timeScale:{borderColor:'#232838',timeVisible:true,secondsVisible:false},crosshair:{mode:0},autoSize:true,
  localization:{locale:'pt-BR'}};
const mkChart=id=>LW.createChart(document.getElementById(id),LWOPT);
const candleOpt={upColor:'#21c37a',downColor:'#ff5470',borderVisible:false,wickUpColor:'#21c37a',wickDownColor:'#ff5470',priceFormat:{type:'price',precision:6,minMove:0.000001}};
const lineOpt=(color,style=0,w=1)=>({color,lineWidth:w,lineStyle:style,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false,pointMarkersVisible:false});
const snap=(ts,step,t0,t1)=>Math.min(t1,Math.max(t0,Math.floor(ts/step)*step));

async function state(){
  const s=await (await fetch('/api/state')).json();
  if(!SYM){SYM=s.symbols[0];document.getElementById('tabs').innerHTML=s.symbols.map(x=>`<button data-s="${x}">${x}</button>`).join('');
    document.querySelectorAll('#tabs button').forEach(b=>b.onclick=()=>{SYM=b.dataset.s;chart()});}
  document.querySelectorAll('#tabs button').forEach(b=>b.classList.toggle('on',b.dataset.s==SYM));
  const a=s.account; document.getElementById('src').textContent='Conta: '+a.source+(s.dry_run?' · dry-run':'');
  const m=s.risk.mode||'—', mp=document.getElementById('mode'); mp.textContent='Risco: '+m; mp.className='pill '+({NORMAL:'ok',REDUCE:'warn',SUSPEND:'bad'}[m]||'');
  const cb=s.circuit||{}, cp=document.getElementById('cb'); cp.textContent='Circuit breaker: '+(cb.tripped?'DISPARADO · '+cb.reason:'ok ('+(cb.errors||0)+' erros)'); cp.className='pill '+(cb.tripped?'bad':'ok');
  const last=s.equity_series.at(-1);
  document.getElementById('k-eq').textContent=a.equity_quote!=null?f(a.equity_quote)+' '+s.quote:(last?f(last[1])+' '+s.quote:'–');
  document.getElementById('k-dd').textContent=pct(s.risk.dd)+' / '+pct(s.risk.max_dd);
  document.getElementById('k-lim').textContent=pct(s.risk.reduce_at)+' / '+pct(s.risk.suspend_at);
  document.getElementById('k-cyc').textContent=s.cycles[0]?t(s.cycles[0].ts):'sem ciclos';
  // saldos
  let h='';
  if(a.balances){h='<tr><th>Moeda</th><th>Disponível</th><th>Reservado</th><th>Total</th><th>Valor '+s.quote+'</th></tr>'+
    a.balances.map(b=>`<tr><td>${esc(b.currency)}</td><td>${f(b.available,8)}</td><td>${f(b.reserved,8)}</td><td>${f(b.total,8)}</td><td>${b.currency==s.quote?f(b.total):f(b.value_quote)}</td></tr>`).join('');}
  else if(a.error){h=`<tr><td class="r">${esc(a.error)}</td></tr>`}
  else{const ps=Object.entries(a.positions||{});h='<tr><th>Símbolo</th><th>Qtd</th><th>Entrada</th><th>Stop ATR</th><th>P/L</th></tr>'+
    (ps.length?ps.map(([k,p])=>{const px=(s.prices[k]||{}).mid;const pl=px?(px/p.entry-1):null;return `<tr><td>${k}</td><td>${f(p.qty,8)}</td><td>${f(p.entry)}</td><td>${f(p.stop)}</td><td class="${pl>=0?'g':'r'}">${pct(pl)}</td></tr>`}).join(''):'<tr><td colspan=5 class="m">Sem posições paper</td></tr>');
    if(a.auth_error)h+=`<tr><td colspan=5 class="r">${esc(a.auth_error)}</td></tr>`;}
  if(a.error&&a.balances===undefined&&!a.positions)h=`<tr><td class="r">${esc(a.error)}</td></tr>`;
  document.getElementById('bal').innerHTML=h;
  document.getElementById('prices').innerHTML=s.prices.error?`<tr><td class="r">${esc(s.prices.error)}</td></tr>`:
    Object.entries(s.prices).map(([k,p])=>`<tr><td>${k}</td><td>${f(p.mid)}</td><td class="m">bid ${f(p.bid)} · ask ${f(p.ask)}</td></tr>`).join('');
  // ordens
  const act=(a.active_orders||[]).map(o=>`<tr><td>ativa</td><td>${esc(o.symbol)}</td><td>${esc(o.side)}</td><td>${esc(o.quantity||o.qty)}</td><td>${esc(o.price)}</td><td>${esc(o.status||o.state)}</td></tr>`);
  const po=s.orders.map(o=>`<tr><td>${t(o.ts)}</td><td>${esc(o.symbol)}</td><td class="${o.side=='BUY'?'g':'r'}">${o.side}</td><td>${f(o.qty,8)}</td><td>${f(o.price)}</td><td>${esc(o.status)} <span class="m">${esc(o.reason)}</span></td></tr>`);
  const st=s.staged.map(o=>`<tr><td>staged</td><td>${esc(o.ticker)}</td><td>${esc(o.side)}</td><td>${f(o.qty,8)}</td><td>${f(o.ref_price)}</td><td>STAGED</td></tr>`);
  const rows=[...act,...st,...po]; document.getElementById('ord').innerHTML='<tr><th>Quando</th><th>Símbolo</th><th>Lado</th><th>Qtd</th><th>Preço</th><th>Estado</th></tr>'+(rows.join('')||'<tr><td colspan=6 class="m">Sem ordens</td></tr>');
  // decisões
  document.getElementById('dec').innerHTML='<tr><th>Ciclo</th><th>Símbolo</th><th>Ação</th><th>Detalhe / motivo</th></tr>'+
    (s.cycles.flatMap(c=>c.decisions.map(d=>`<tr><td>${t(c.ts)}</td><td>${esc(d.ticker)}</td><td class="${d.action=='BUY'?'g':d.action=='SELL'?'r':'y'}">${d.action}</td><td>${esc(d.reason||('alloc '+pct(d.alloc)+' · p '+f(d.p,3)+' · b '+f(d.b,2)+' · EV '+f(d.ev,4)))}</td></tr>`)).join('')||'<tr><td colspan=4 class="m">Sem ciclos registados</td></tr>');
  // dd chart (LWC area)
  const dd=[];{const seen={};for(const x of s.equity_series){const tt=Math.floor(+x[0]);if(!seen[tt]){seen[tt]=1;dd.push({time:tt,value:-(x[2]||0)*100})}}dd.sort((a,b)=>a.time-b.time)}
  if(!ddChart){ddChart=mkChart('dd');ddSeries=ddChart.addSeries(LW.AreaSeries,{lineColor:'#ff5470',topColor:'rgba(255,84,112,.05)',bottomColor:'rgba(255,84,112,.30)',lineWidth:2,priceFormat:{type:'percent'}})}
  ddSeries.setData(dd);
  document.getElementById('upd').textContent='Atualizado '+new Date().toLocaleTimeString('pt-BR');
}

async function chart(){
  const c=await (await fetch('/api/chart?symbol='+SYM+'&interval=60')).json();
  document.querySelectorAll('#tabs button').forEach(b=>b.classList.toggle('on',b.dataset.s==SYM));
  if(!Array.isArray(c.candles))return;
  const seen={};const cs=c.candles.map(x=>({time:Math.floor(+x.start/1000),open:+x.open,high:+x.high,low:+x.low,close:+x.close}))
    .filter(x=>!seen[x.time]&&(seen[x.time]=1)).sort((a,b)=>a.time-b.time);
  if(!pxChart){pxChart=mkChart('px');pxSeries=pxChart.addSeries(LW.CandlestickSeries,candleOpt);pxMarkers=LW.createSeriesMarkers(pxSeries,[]);pxStop=pxChart.addSeries(LW.LineSeries,lineOpt('#f5b942',2,1))}
  pxSeries.setData(cs);
  if(!cs.length){pxMarkers.setMarkers([]);pxStop.setData([]);return}
  const t0=cs[0].time,t1=cs.at(-1).time,mk=[],st=[];let stop=null;
  c.markers.slice().sort((a,b)=>a.ts-b.ts).forEach(m=>{const tt=snap(Math.floor(m.ts),3600,t0,t1);
    if(m.side=='BUY'){mk.push({time:tt,position:'belowBar',color:'#21c37a',shape:'arrowUp',text:'Entrada'});if(m.stop){stop=+m.stop;st.push({time:tt,value:stop})}}
    else{mk.push({time:tt,position:'aboveBar',color:'#ff5470',shape:'arrowDown',text:'Saída'});if(stop!=null){st.push({time:tt,value:stop});stop=null}}});
  if(stop!=null)st.push({time:t1,value:stop});
  const uniq=a=>{const o={};a.forEach(p=>o[p.time]=p);return Object.values(o).sort((x,y)=>x.time-y.time)};
  pxMarkers.setMarkers(mk.sort((a,b)=>a.time-b.time));pxStop.setData(uniq(st));
}
async function desk(){
  const d=await (await fetch('/api/desk')).json(); if(d.error){document.getElementById('desk-kpis').innerHTML=`<div class="r">${esc(d.error)}</div>`;return}
  const s=d.stats, th=d.thresholds, ok=b=>b?'g':'r';
  const k=(l,v,c)=>`<div class="kpi"><div class="l">${l}</div><div class="v ${c||''}">${v}</div></div>`;
  let kp=k('Trades paper (≥'+th.threshold_trades+')',s.n,ok(s.n>=th.threshold_trades))+k('Win rate (≥'+pct(th.threshold_win_rate)+')',pct(s.win_rate),ok(s.win_rate>=th.threshold_win_rate))
   +k('Expectancy (≥+'+th.threshold_expectancy_r+'R)',f(s.expectancy_r,3)+'R',ok(s.expectancy_r>=th.threshold_expectancy_r))+k('Max DD (≤'+pct(th.threshold_max_dd)+')',pct(s.max_dd),ok(s.max_dd<=th.threshold_max_dd));
  if(d.replay)kp+=k('Replay histórico',d.replay.full.n+' trades · '+f(d.replay.full.expectancy_r,2)+'R · '+(d.replay.go?'GO':'NO-GO'),d.replay.go?'g':'r');
  document.getElementById('desk-kpis').innerHTML=kp;
  const T=(id,head,rows,empty)=>document.getElementById(id).innerHTML='<tr>'+head.map(h=>`<th>${h}</th>`).join('')+'</tr>'+(rows.join('')||`<tr><td colspan=${head.length} class="m">${empty}</td></tr>`);
  T('d-watch',['Moeda','Âncora','Flip','Tag'],d.watchlist.map(w=>`<tr><td>${esc(w.coin)}</td><td>${f(w.anchor_low,6)}</td><td>${esc(w.flip_date)}</td><td class="${w.tag=='PRIME'?'g':''}">${esc(w.tag)}</td></tr>`),'Sem flips de alta ativos');
  T('d-zones',['Moeda','#','Zona','Estado'],d.zones.filter(z=>z.status!='INVALID').map(z=>`<tr><td>${esc(z.coin)}</td><td>${z.rank}</td><td>${f(z.zone_bottom,6)}–${f(z.zone_top,6)}</td><td class="${z.status=='CONFIRMED'||z.status=='USED'?'g':z.status=='TESTED'?'y':''}">${esc(z.status)}</td></tr>`),'Sem zonas');
  T('d-outbox',['Quando','Tipo','Moeda','Estado','Gráfico'],d.outbox.map(a=>`<tr title="${esc(a.text)}"><td>${esc(a.created_at)}</td><td class="${a.type=='EXIT_NOW'?'r':a.type=='ENTRY_ALERT'?'g':'y'}">${esc(a.type)}</td><td>${esc(a.coin||'')}</td><td>${esc(a.status)}</td><td>${a.chart_url?`<a href="${a.chart_url}" target="_blank" style="color:#7c5cff">ver</a>`:''}</td></tr>`),'Outbox vazio');
  T('d-pos',['Moeda','Entrada','Stop','Âncora','BE'],d.positions.map(p=>`<tr><td>${esc(p.coin)}</td><td>${f(p.entry,6)}</td><td>${f(p.stop,6)}</td><td>${f(p.anchor_low,6)}</td><td>${p.at_be=='True'?'sim':'não'}</td></tr>`),'Sem posições');
  T('d-journal',['Quando','Trade','Linha','Valor','R','Modo'],d.journal.map(j=>`<tr><td>${esc(j.ts)}</td><td>${esc(j.coin)}</td><td>${esc(j.line)}</td><td>${f(j.amount_usd||j.price)}</td><td>${j.r?f(j.r,2):''}</td><td class="m">${esc(j.mode)}</td></tr>`),'Journal vazio');
  await deskChart(); await deskEquity();
}
async function deskCoins(){
  const cs=await (await fetch('/api/desk/coins')).json(); const sel=document.getElementById('d-coin');
  if(!cs.length){sel.innerHTML='<option>sem moedas</option>';return}
  if(!DCOIN||!cs.includes(DCOIN)){const prio=['BAT-USD','BTC-USD'];DCOIN=cs.find(x=>prio.includes(x))||cs[0]}
  sel.innerHTML=cs.map(x=>`<option ${x==DCOIN?'selected':''}>${esc(x)}</option>`).join('');
  sel.onchange=()=>{DCOIN=sel.value;deskChart(true)};
  document.querySelectorAll('#d-tf button').forEach(b=>b.onclick=()=>{DTF=+b.dataset.tf;document.querySelectorAll('#d-tf button').forEach(x=>x.classList.toggle('on',x==b));deskChart(true)});
}
async function deskChart(fit){
  if(!DCOIN)return;
  const d=await (await fetch('/api/desk/chart?coin='+encodeURIComponent(DCOIN)+'&tf='+DTF)).json(); if(d.error)return;
  document.getElementById('d-src').textContent=DCOIN+' · '+({60:'1H',240:'4H',1440:'1D'}[DTF])+' · velas: '+d.source+' · '+d.zones.length+' zonas · '+d.trades.length+' trades';
  if(!dChart){dChart=mkChart('d-chart');dCandle=dChart.addSeries(LW.CandlestickSeries,candleOpt);dMarkers=LW.createSeriesMarkers(dCandle,[])}
  dLines.forEach(s=>dChart.removeSeries(s));dLines=[];
  dCandle.setData(d.candles);
  if(!d.candles.length){dMarkers.setMarkers([]);return}
  const step=DTF*60,t0=d.candles[0].time,t1=d.candles.at(-1).time,sn=x=>snap(x,step,t0,t1);
  const seg=(a,b,v,color,style,w,title)=>{if(v==null||a==null)return;const s=dChart.addSeries(LW.LineSeries,{...lineOpt(color,style,w),title:title||''});
    const x0=sn(a),x1=sn(b??t1);s.setData(x1>x0?[{time:x0,value:v},{time:x1,value:v}]:[{time:x0,value:v}]);dLines.push(s)};
  d.zones.forEach(z=>{const c=z.status=='TESTED'?'#f5b942':(['USED','EXPIRED','INVALID'].includes(z.status)?'#5b6275':'#21c37a');
    seg(z.from,z.to,z.top,c,0,1,'FVG #'+(z.rank||'')+' '+z.status);seg(z.from,z.to,z.bottom,c,2,1,'')});
  const mk=[];
  d.trades.forEach(tr=>{const rep=tr.source=='replay';const a=tr.open,b=tr.close??t1;
    if(a==null||b<t0)return;
    seg(a,b,tr.entry,'#4ea1ff',rep?3:1,1,rep?'':'entrada');seg(a,b,tr.initial_stop??tr.stop,'#ff5470',rep?3:0,rep?1:2,rep?'':'stop');
    if(tr.stop!=null&&tr.initial_stop!=null&&Math.abs(tr.stop-tr.initial_stop)>1e-12)seg(a,b,tr.stop,'#ff8aa0',2,1,'stop BE');
    if(tr.tp!=null)seg(a,b,tr.tp,'#21c37a',rep?3:0,rep?1:2,rep?'':'TP');
    if(a>=t0)mk.push({time:sn(a),position:'belowBar',color:rep?'#8a90a2':'#4ea1ff',shape:rep?'circle':'arrowUp',text:rep?'◆':'Entrada'});
    if(tr.close!=null&&tr.close>=t0){const good=(tr.exit??0)>(tr.entry??0);
      mk.push({time:sn(tr.close),position:'aboveBar',color:good?'#21c37a':'#ff5470',shape:rep?'circle':'arrowDown',text:(rep?'◆ ':'')+tr.rule+(tr.r!=null?' '+f(tr.r,2)+'R':'')})}});
  d.plans.forEach(p=>{seg(p.created,t1,p.entry,'#4ea1ff',1,1,'plano entrada');seg(p.created,t1,p.stop,'#ff5470',1,1,'plano stop');if(p.tp)seg(p.created,t1,p.tp,'#21c37a',1,1,'plano TP')});
  dMarkers.setMarkers(mk.sort((a,b)=>a.time-b.time));
  if(fit)dChart.timeScale().fitContent();
}
async function deskEquity(){
  const e=await (await fetch('/api/desk/equity')).json();
  if(!eqChart){eqChart=mkChart('d-eq');eqReplay=eqChart.addSeries(LW.LineSeries,{color:'#8a90a2',lineWidth:1,title:'replay histórico',priceLineVisible:false});
    eqPaper=eqChart.addSeries(LW.LineSeries,{color:'#7c5cff',lineWidth:2,title:'paper (journal)',priceLineVisible:false})}
  eqReplay.setData(e.replay.map(([time,value])=>({time,value})));eqPaper.setData(e.paper.map(([time,value])=>({time,value})));
}
async function loop(){try{await state();await chart()}catch(e){console.error(e)}try{await desk()}catch(e){console.error(e)}}
deskCoins().then(()=>deskChart(true)).catch(console.error);
loop();setInterval(state,5000);setInterval(chart,60000);setInterval(()=>desk().catch(console.error),15000);
