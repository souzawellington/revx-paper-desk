'use strict';
(function(){
var S={snap:null,sym:null,book:''};
function $(id){return document.getElementById(id)}
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function num(x){return typeof x==='number'&&isFinite(x)}
function usd(x){return num(x)?'$'+x.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}):'—'}
function pct(x,d){return num(x)?(100*x).toFixed(d==null?1:d)+'%':'—'}
function fx(x,d){return num(x)?x.toFixed(d):'—'}
function px(x){if(!num(x))return'—';var d=x>=1000?2:x>=10?3:5;return x.toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d})}
function tLon(ms,full){if(!ms)return'—';try{return new Date(ms).toLocaleString('pt-BR',full?{timeZone:'Europe/London',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}:{timeZone:'Europe/London',hour:'2-digit',minute:'2-digit'})}catch(e){return new Date(ms).toISOString().slice(11,16)}}
var STATE={PAPER_TRAINING:['run','PAPER_TRAINING'],HALTED_MAX_DRAWDOWN:['halt','HALTED_MAX_DRAWDOWN'],CEILING_PAUSED:['ceil','CEILING_PAUSED']};
function showStale(m){var e=$('stale');e.textContent=m;e.style.display=m?'block':'none'}

function rules(E){var r=E.rules||{};$('rules').innerHTML=[
 ['Início',usd(r.start)],['Teto',usd(r.ceiling)+' → pausa'],['Kill DD',pct(r.dd_kill,0)+' do pico'],['Maker',pct(r.maker_fee,2)],['Taker',pct(r.taker_fee,2)],
 ['Slippage',pct(r.slippage,2)+' + spread'],['Taker só se edge >',pct(r.taker_min_edge,2)],['Risco/trade',pct(r.risk_pct,1)],['GO precisa',(r.min_trades||40)+' trades/livro']
].map(function(x){return '<span class="chip">'+esc(x[0])+' <b>'+esc(x[1])+'</b></span>'}).join('');
 var l2=E.l2||{};$('l2').innerHTML='<span class="mut">Livro L2 (público):</span>'+Object.keys(l2).map(function(s){var v=l2[s];return '<span>'+esc(s.replace('-USD',''))+' spread <b>'+fx(v.spread_bps,2)+' bps</b> · OBI <b class="'+(v.obi>0?'pos':'neg')+'">'+fx(v.obi,2)+'</b> <span class="mut">'+esc(tLon(v.at))+'</span></span>'}).join('')}

function cards(E){var h='';(E.cards||[]).forEach(function(c){var st=STATE[c.state]||['run',c.state];
 var prog=num(c.equity)?Math.max(0,Math.min(1,(c.equity-c.start)/(c.ceiling-c.start))):0;
 var ddr=num(c.drawdown_now)?Math.max(0,Math.min(1,c.drawdown_now/c.dd_limit)):0;
 var pnlc=num(c.pnl)&&c.pnl<0?'neg':'pos';
 h+='<div class="card '+st[0]+'"><div class="row"><h2>'+esc(c.name)+'</h2><span class="pill '+st[0]+'">'+esc(st[1])+'</span></div>'+
 '<div class="mut mono">'+esc(c.id)+(c.cycles?' · ciclo '+esc(c.cycles):'')+'</div>'+
 '<div class="row" style="margin-top:6px"><span class="big mono">'+usd(c.equity)+'</span><span class="mono '+pnlc+'">'+(num(c.pnl)&&c.pnl>=0?'+':'')+usd(c.pnl)+'</span></div>'+
 '<div class="lbl"><span>Progresso até '+usd(c.ceiling)+'</span><span class="mono">'+pct(prog,1)+'</span></div><div class="bar"><i style="width:'+(100*prog).toFixed(1)+'%;background:linear-gradient(90deg,var(--acc2),var(--vault))"></i></div>'+
 '<div class="lbl"><span>Queda do pico '+pct(c.drawdown_now,1)+' / kill '+pct(c.dd_limit,0)+'</span><span class="mono">faltam '+pct(c.dd_room,1)+'</span></div><div class="bar"><i style="width:'+(100*ddr).toFixed(1)+'%;background:'+(ddr>.6?'var(--ask)':ddr>.3?'var(--gold)':'var(--cy)')+'"></i></div>'+
 '<div class="kv mono"><div><span>Trades</span>'+esc(c.trades)+'/'+esc(c.need_trades)+'</div><div><span>Win rate</span>'+pct(c.win_rate,0)+'</div><div><span>Expect.</span>'+(num(c.expectancy_r)?(c.expectancy_r>=0?'+':'')+c.expectancy_r.toFixed(2)+'R':'—')+'</div>'+
 '<div><span>Profit F.</span>'+fx(c.profit_factor,2)+'</div><div><span>Sharpe</span>'+fx(c.sharpe,2)+'</div><div><span>Sortino</span>'+fx(c.sortino,2)+'</div>'+
 '<div><span>Max DD</span>'+pct(c.max_dd,1)+'</div><div><span>Taxas</span>'+usd(c.fees)+'</div><div><span>Abertas</span>'+((c.positions||[]).length)+' · pend '+((c.orders||[]).length)+'</div></div>'+
 '<div class="verdict">Veredito: <b>'+esc(c.verdict)+'</b></div></div>'});
 $('books').innerHTML=h||'<div class="card">Sem livros ainda.</div>'}

function tabs(E){var syms=E.symbols||[];if(!S.sym||syms.indexOf(S.sym)<0)S.sym=syms[0];
 $('symtabs').innerHTML=syms.map(function(s){return '<button class="tab'+(s===S.sym?' on':'')+'" data-s="'+esc(s)+'">'+esc(s)+'</button>'}).join('');
 Array.prototype.forEach.call($('symtabs').querySelectorAll('button'),function(b){b.onclick=function(){S.sym=b.getAttribute('data-s');draw();tabs(S.snap.ems)}});
 var sel=$('bookSel');if(sel.options.length<=1)(E.cards||[]).forEach(function(c){var o=document.createElement('option');o.value=c.id;o.textContent=c.name;sel.appendChild(o)});
 sel.onchange=function(){S.book=sel.value;draw();table()}}

function draw(){var E=S.snap&&S.snap.ems;var svg=$('chart');if(!E||!E.candles){svg.innerHTML='';return}
 var C=E.candles[S.sym]||[];if(!C.length){svg.innerHTML='<text x="500" y="190" fill="#8B93A7" text-anchor="middle">sem velas</text>';return}
 var W=1000,H=380,padR=70,padB=22,t0=C[0][0],t1=C[C.length-1][0]+60000,lo=Infinity,hi=-Infinity;
 C.forEach(function(c){lo=Math.min(lo,c[3]);hi=Math.max(hi,c[2])});
 var tr=(E.trades||[]).filter(function(t){return t.coin===S.sym&&(!S.book||t.book===S.book)&&t.exit>=t0});
 var opens=[],ords=[];(E.cards||[]).forEach(function(c){if(S.book&&c.id!==S.book)return;(c.positions||[]).forEach(function(p){if(p.coin===S.sym)opens.push(p)});(c.orders||[]).forEach(function(o){if(o.coin===S.sym)ords.push(o)})});
 opens.concat(ords).forEach(function(p){[p.stop,p.tp,p.limit,p.entry].forEach(function(v){if(num(v)){lo=Math.min(lo,v);hi=Math.max(hi,v)}})});
 var m=(hi-lo)*.06||hi*.001;lo-=m;hi+=m;
 function X(t){return (t-t0)/(t1-t0)*(W-padR)}function Y(p){return 10+(hi-p)/(hi-lo)*(H-padB-10)}
 var bw=Math.max(1,(W-padR)/C.length*.7),o=[];
 for(var g=0;g<=4;g++){var p=lo+(hi-lo)*g/4,y=Y(p);o.push('<line x1="0" x2="'+(W-padR)+'" y1="'+y+'" y2="'+y+'" stroke="#1E2330"/><text x="'+(W-padR+4)+'" y="'+(y+4)+'" fill="#8B93A7" font-size="11" class="mono">'+esc(px(p))+'</text>')}
 for(var k=0;k<C.length;k+=Math.ceil(C.length/6)){o.push('<text x="'+X(C[k][0])+'" y="'+(H-6)+'" fill="#8B93A7" font-size="11">'+esc(tLon(C[k][0]))+'</text>')}
 C.forEach(function(c){var x=X(c[0])+bw/2,up=c[4]>=c[1],col=up?'#00E676':'#FF3B69',yo=Y(c[1]),yc=Y(c[4]);
  o.push('<line x1="'+x+'" x2="'+x+'" y1="'+Y(c[2])+'" y2="'+Y(c[3])+'" stroke="'+col+'" stroke-width="1"/><rect x="'+(x-bw/2)+'" y="'+Math.min(yo,yc)+'" width="'+bw+'" height="'+Math.max(1,Math.abs(yc-yo))+'" fill="'+col+'" opacity=".85"/>')});
 tr.forEach(function(t){var xa=X(Math.max(t.fill,t0)),xb=X(t.exit)+bw;
  o.push('<line x1="'+xa+'" x2="'+xb+'" y1="'+Y(t.tp)+'" y2="'+Y(t.tp)+'" stroke="#10B981" stroke-dasharray="4 3"/><line x1="'+xa+'" x2="'+xb+'" y1="'+Y(t.stop)+'" y2="'+Y(t.stop)+'" stroke="#FF3B69" stroke-dasharray="4 3"/>');
  if(t.fill>=t0){var ya=Y(t.entry);o.push('<path d="M'+(xa+bw/2)+' '+(ya-1)+' l-6 11 h12 z" fill="#00E676" stroke="#060709"><title>entrada '+esc(t.kind)+' '+esc(px(t.entry))+' · '+esc(t.book)+'</title></path>')}
  o.push('<circle cx="'+(X(t.exit)+bw/2)+'" cy="'+Y(t.exit_px)+'" r="5" fill="'+(t.r>=0?'#F59E0B':'#FF3B69')+'" stroke="#060709"><title>saída '+esc(t.reason)+' '+esc(px(t.exit_px))+' · '+(t.r>=0?'+':'')+esc(fx(t.r,2))+'R</title></circle>')});
 opens.forEach(function(p){var xa=X(Math.max(p.since,t0));
  o.push('<line x1="'+xa+'" x2="'+(W-padR)+'" y1="'+Y(p.tp)+'" y2="'+Y(p.tp)+'" stroke="#10B981" stroke-width="1.5"/><line x1="'+xa+'" x2="'+(W-padR)+'" y1="'+Y(p.stop)+'" y2="'+Y(p.stop)+'" stroke="#FF3B69" stroke-width="1.5"/><line x1="'+xa+'" x2="'+(W-padR)+'" y1="'+Y(p.entry)+'" y2="'+Y(p.entry)+'" stroke="#06B6D4" stroke-dasharray="2 2"/>');
  if(p.since>=t0)o.push('<path d="M'+(xa+bw/2)+' '+(Y(p.entry)-1)+' l-6 11 h12 z" fill="#00E676" stroke="#060709"/>')});
 ords.forEach(function(q){if(num(q.limit)){var y=Y(q.limit);o.push('<line x1="'+X(Math.max(q.placed,t0))+'" x2="'+(W-padR)+'" y1="'+y+'" y2="'+y+'" stroke="#6366F1" stroke-width="1.5" stroke-dasharray="6 3"><title>limite '+esc(px(q.limit))+'</title></line>')}});
 svg.innerHTML=o.join('');
 $('chinfo').textContent=C.length+' velas 1m · '+tr.length+' trades · '+opens.length+' abertas · '+ords.length+' ordens'}

function table(){var E=S.snap&&S.snap.ems;var T=((E&&E.trades)||[]).filter(function(t){return !S.book||t.book===S.book}).slice().reverse().slice(0,25);
 var h='<tr><th>Saída</th><th>Livro</th><th>Moeda</th><th>Tipo</th><th>Entrada</th><th>SL</th><th>TP</th><th>Saída px</th><th>Motivo</th><th>R</th><th>PnL</th></tr>';
 T.forEach(function(t){h+='<tr class="mono"><td>'+esc(tLon(t.exit,1))+'</td><td>'+esc(t.book.replace('ems_',''))+'</td><td>'+esc(t.coin.replace('-USD',''))+'</td><td>'+esc(t.kind)+(t.catchup?' ↺':'')+'</td><td>'+px(t.entry)+'</td><td>'+px(t.stop)+'</td><td>'+px(t.tp)+'</td><td>'+px(t.exit_px)+'</td><td>'+esc(t.reason)+'</td><td class="'+(t.r>=0?'pos':'neg')+'">'+(t.r>=0?'+':'')+fx(t.r,2)+'</td><td class="'+(t.pnl>=0?'pos':'neg')+'">'+usd(t.pnl)+'</td></tr>'});
 $('trades').innerHTML=T.length?h:'<tr><td class="mut">Ainda sem trades fechados — os livros só entram quando o sinal pré-registado aparece (nunca forçam trades).</td></tr>'}

function events(E){var ev=E.events||[];$('events').innerHTML='<b>Eventos</b> <span class="mut">(kill por DD, teto de $1.000)</span>'+(ev.length?'<table>'+ev.slice().reverse().map(function(e){return '<tr><td>'+esc(tLon(e.ts,1))+'</td><td>'+esc(e.book)+'</td><td>'+esc(e.type)+'</td><td>'+esc(e.equity)+'</td></tr>'}).join('')+'</table>':'<div class="mut">nenhum</div>')}

function render(j){var s=j&&j.snapshot;if(!s){showStale('Ainda sem dados da box.');return}
 S.snap=s;S.server=j.server_now;var E=s.ems;
 $('upd').textContent=tLon(s.generated_at*1000,1);tick();
 if(!E||!E.available){showStale('Livros EMS ainda sem dados'+(E&&E.why?' ('+E.why+')':'')+'.');return}
 rules(E);cards(E);tabs(E);draw();table();events(E)}
function tick(){if(!S.snap)return;var a=Math.round(Date.now()/1000-S.snap.generated_at);$('age').textContent='(há '+(a<120?a+' s':Math.round(a/60)+' min')+')';
 if(a>300)showStale('Dados com '+Math.round(a/60)+' min — a box pode estar em pausa. Os livros recuperam as velas em falta quando ela voltar.');else if(S.snap.ems&&S.snap.ems.available)showStale('')}
function load(){fetch(location.origin+'/api/snapshot',{cache:'no-store',credentials:'same-origin'}).then(function(r){if(!r.ok)throw new Error('HTTP '+r.status);return r.json()}).then(render).catch(function(e){showStale('Não consegui buscar os dados ('+e.message+'). Tento de novo em 30 s.')})}
load();setInterval(load,30000);setInterval(tick,5000);
})();
