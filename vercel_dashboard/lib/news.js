'use strict';
(function(){
var S={snap:null};
function $(id){return document.getElementById(id)}
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function num(x){return typeof x==='number'&&isFinite(x)}
function usd(x){return num(x)?'$'+x.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}):'—'}
function pct(x,d){return num(x)?(100*x).toFixed(d==null?1:d)+'%':'—'}
function fx(x,d){return num(x)?x.toFixed(d):'—'}
function px(x){if(!num(x))return'—';var d=x>=1000?2:x>=10?3:x>=1?4:6;return x.toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d})}
function tLon(v,full){if(!v)return'—';var ms=typeof v==='number'?v:Date.parse(v);try{return new Date(ms).toLocaleString('pt-BR',full?{timeZone:'Europe/London',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}:{timeZone:'Europe/London',hour:'2-digit',minute:'2-digit'})}catch(e){return new Date(ms).toISOString().slice(11,16)}}
var STATE={PAPER_TRAINING:['run','PAPER_TRAINING'],HALTED_MAX_DRAWDOWN:['halt','HALTED_MAX_DRAWDOWN'],CEILING_PAUSED:['ceil','CEILING_PAUSED']};
function showStale(m){var e=$('stale');e.textContent=m;e.style.display=m?'block':'none'}

function rules(N){var r=N.rules||{};$('rules').innerHTML=[
 ['Início',usd(r.start)],['Teto',usd(r.ceiling)+' → pausa'],['Kill DD',pct(r.dd_kill,0)+' do pico'],['Maker',pct(r.maker_fee,2)],['Taker',pct(r.taker_fee,2)],
 ['Slippage',pct(r.slippage,2)+' + spread'],['Risco/trade',pct(r.risk_pct,1)],['Janela notícia',(r.window_min||60)+' min'],['Notícia velha',(r.max_age_min||90)+' min'],['GO precisa',(r.min_trades||40)+' trades/livro']
].map(function(x){return '<span class="chip">'+esc(x[0])+' <b>'+esc(x[1])+'</b></span>'}).join('');
 $('meta').innerHTML='Universo Revolut X: <b>'+esc(N.universe_n)+'</b> moedas USD (UK), <b>'+esc(N.liquid_n)+'</b> com liquidez/spread aceitáveis · Trending CoinGecko: '+
  ((N.trending||[]).map(function(s){return '<span class="tag">'+esc(s)+'</span>'}).join('')||'—')+
  ((N.veto||[]).length?' · Veto (notícia negativa): '+N.veto.map(function(s){return '<span class="tag neg">'+esc(s)+'</span>'}).join(''):'')+
  ((N.source_errors||[]).length?' · <span class="neg">fontes com erro: '+esc(N.source_errors.join(', '))+'</span>':'')+' · início '+esc(tLon(N.started,1))}

function cards(N){var h='';(N.cards||[]).forEach(function(c){var st=STATE[c.state]||['run',c.state];
 var prog=num(c.equity)?Math.max(0,Math.min(1,(c.equity-c.start)/(c.ceiling-c.start))):0;
 var ddr=num(c.drawdown_now)?Math.max(0,Math.min(1,c.drawdown_now/c.dd_limit)):0;
 var n=c.counts||{};
 h+='<div class="card '+st[0]+'"><div class="row"><h2>'+esc(c.name)+'</h2><span class="pill '+st[0]+'">'+esc(st[1])+'</span></div>'+
 '<div class="mut mono">'+esc(c.id)+'</div><div class="mut" style="font-size:12px;margin-top:4px">'+esc(c.rule)+'</div>'+
 '<div class="row" style="margin-top:6px"><span class="big mono">'+usd(c.equity)+'</span><span class="mono '+(num(c.pnl)&&c.pnl<0?'neg':'pos')+'">'+(num(c.pnl)&&c.pnl>=0?'+':'')+usd(c.pnl)+'</span></div>'+
 '<div class="lbl"><span>Progresso até '+usd(c.ceiling)+'</span><span class="mono">'+pct(prog,1)+'</span></div><div class="bar"><i style="width:'+(100*prog).toFixed(1)+'%;background:linear-gradient(90deg,var(--acc2),var(--vault))"></i></div>'+
 '<div class="lbl"><span>Queda do pico '+pct(c.drawdown_now,1)+' / kill '+pct(c.dd_limit,0)+'</span><span class="mono">faltam '+pct(c.dd_room,1)+'</span></div><div class="bar"><i style="width:'+(100*ddr).toFixed(1)+'%;background:'+(ddr>.6?'var(--ask)':ddr>.3?'var(--gold)':'var(--cy)')+'"></i></div>'+
 '<div class="kv mono"><div><span>Trades</span>'+esc(c.trades)+'/'+esc(c.need_trades)+'</div><div><span>Win rate</span>'+pct(c.win_rate,0)+'</div><div><span>Expect.</span>'+(num(c.expectancy_r)?(c.expectancy_r>=0?'+':'')+c.expectancy_r.toFixed(2)+'R':'—')+'</div>'+
 '<div><span>Avaliadas</span>'+esc(n.evaluated||0)+'</div><div><span>Entradas</span>'+esc(n.placed||0)+'</div><div><span>Custos</span>'+usd(c.fees)+'</div></div>'+
 ((c.positions||[]).length?'<div class="verdict">Abertas: '+c.positions.map(function(p){return esc(p.coin.replace('-USD',''))+' @ '+px(p.entry)+' (SL '+px(p.stop)+' · TP '+px(p.tp)+')'}).join(' · ')+'</div>':'')+
 ((c.orders||[]).length?'<div class="verdict">Ordens: '+c.orders.map(function(o){return esc(o.coin.replace('-USD',''))+' '+esc(o.kind)+(num(o.limit)?' limite '+px(o.limit):'')}).join(' · ')+'</div>':'')+
 '<div class="verdict">Veredito: <b>'+esc(c.verdict)+'</b></div></div>'});
 $('books').innerHTML=h||'<div class="card">Sem livros ainda.</div>'}

function chart(N){var svg=$('chart'),C=N.curve||{},W=1000,H=220,lo=Infinity,hi=-Infinity,t0=Infinity,t1=-Infinity,o=[];
 Object.keys(C).forEach(function(b){(C[b]||[]).forEach(function(p){if(num(p[1])){lo=Math.min(lo,p[1]);hi=Math.max(hi,p[1]);t0=Math.min(t0,p[0]);t1=Math.max(t1,p[0])}})});
 if(!isFinite(lo)||t1<=t0){svg.innerHTML='<text x="500" y="110" fill="#8B93A7" text-anchor="middle">sem pontos ainda</text>';return}
 lo=Math.min(lo,65)-0.5;hi=Math.max(hi,65)+0.5;
 function X(t){return (t-t0)/(t1-t0)*(W-60)}function Y(v){return 8+(hi-v)/(hi-lo)*(H-26)}
 o.push('<line x1="0" x2="'+(W-60)+'" y1="'+Y(65)+'" y2="'+Y(65)+'" stroke="#1E2330" stroke-dasharray="4 3"/><text x="'+(W-56)+'" y="'+(Y(65)+4)+'" fill="#8B93A7" font-size="11">$65</text>');
 o.push('<text x="0" y="'+(H-4)+'" fill="#8B93A7" font-size="11">'+esc(tLon(t0,1))+'</text><text x="'+(W-160)+'" y="'+(H-4)+'" fill="#8B93A7" font-size="11">'+esc(tLon(t1,1))+'</text>');
 var col={news_momo:'#06B6D4',news_pullback:'#F59E0B'};
 Object.keys(C).forEach(function(b){var d=(C[b]||[]).filter(function(p){return num(p[1])}).map(function(p,i){return (i?'L':'M')+X(p[0]).toFixed(1)+' '+Y(p[1]).toFixed(1)}).join(' ');
  if(d)o.push('<path d="'+d+'" fill="none" stroke="'+(col[b]||'#6366F1')+'" stroke-width="2"/>')});
 svg.innerHTML=o.join('')}

function sigs(N){var T=N.signals||[];var h='<tr><th>Hora</th><th>Moeda</th><th>Score</th><th>Volume</th><th>15 min</th><th>Desde notícia</th><th>24 h</th><th>Spread</th><th>Decisão</th></tr>';
 T.forEach(function(r){var dec=r.decision?esc(r.decision):Object.keys(r.books||{}).map(function(k){var v=String(r.books[k]);return '<div class="'+(v.indexOf('ACEITE')===0?'ok':'no')+'"><b>'+esc(k.replace('news_',''))+'</b>: '+esc(v)+'</div>'}).join('');
  h+='<tr class="mono"><td>'+esc(tLon(r.t))+'</td><td>'+esc(r.coin)+'</td><td>+'+esc(r.score)+'</td><td>'+(num(r.vol_ratio)?fx(r.vol_ratio,1)+'×':'—')+'</td><td>'+pct(r.mom_15m,2)+'</td><td>'+pct(r.runup,2)+'</td><td>'+pct(r.chg_24h,1)+'</td><td>'+(num(r.spread_bps)?fx(r.spread_bps,0)+' bps':'—')+'</td><td style="text-align:left">'+dec+'</td></tr>'});
 $('sigs').innerHTML=T.length?h:'<tr><td class="mut">Ainda nenhuma moeda avaliada — só acontece quando sai uma notícia positiva nova (menos de 90 min) sobre uma moeda da Revolut X.</td></tr>'}

function news(N){var T=N.news||[];var h='<tr><th>Hora</th><th>Fonte</th><th>Título</th><th>Moedas</th><th>Decisão</th></tr>';
 T.forEach(function(r){var sc=r.scores||{};h+='<tr><td class="mono">'+esc(tLon(r.t))+'</td><td>'+esc(r.source)+'</td><td>'+esc(r.title)+'</td><td>'+Object.keys(sc).map(function(k){return '<span class="tag '+(sc[k]>0?'pos':sc[k]<0?'neg':'')+'">'+esc(k)+' '+(sc[k]>0?'+':'')+esc(sc[k])+'</span>'}).join('')+'</td><td style="white-space:normal;text-align:left" class="mut">'+esc(r.decision)+'</td></tr>'});
 $('news').innerHTML=T.length?h:'<tr><td class="mut">Sem notícias com moeda ainda.</td></tr>'}

function trades(N){var T=(N.trades||[]).slice().reverse().slice(0,25);
 var h='<tr><th>Saída</th><th>Livro</th><th>Moeda</th><th>Tipo</th><th>Entrada</th><th>SL</th><th>TP</th><th>Saída px</th><th>Motivo</th><th>R</th><th>PnL</th></tr>';
 T.forEach(function(t){h+='<tr class="mono"><td>'+esc(tLon(t.exit,1))+'</td><td>'+esc(String(t.book).replace('news_',''))+'</td><td>'+esc(String(t.coin).replace('-USD',''))+'</td><td>'+esc(t.kind)+'</td><td>'+px(t.entry)+'</td><td>'+px(t.stop)+'</td><td>'+px(t.tp)+'</td><td>'+px(t.exit_px)+'</td><td>'+esc(t.reason)+'</td><td class="'+(t.r>=0?'pos':'neg')+'">'+(t.r>=0?'+':'')+fx(t.r,2)+'</td><td class="'+(t.pnl>=0?'pos':'neg')+'">'+usd(t.pnl)+'</td></tr>'});
 $('trades').innerHTML=T.length?h:'<tr><td class="mut">Ainda sem trades fechados — o bot só entra quando notícia positiva + volume + preço confirmam (nunca força trades).</td></tr>'}

function render(j){var s=j&&j.snapshot;if(!s){showStale('Ainda sem dados da box.');return}
 S.snap=s;var N=s.news;$('upd').textContent=tLon(s.generated_at*1000,1);tick();
 if(!N||!N.available){showStale('Bot de notícias ainda sem dados'+(N&&N.why?' ('+N.why+')':'')+'.');return}
 rules(N);cards(N);chart(N);sigs(N);news(N);trades(N)}
function tick(){if(!S.snap)return;var a=Math.round(Date.now()/1000-S.snap.generated_at);$('age').textContent='(há '+(a<120?a+' s':Math.round(a/60)+' min')+')';
 if(a>300)showStale('Dados com '+Math.round(a/60)+' min — a box pode estar em pausa.');else if(S.snap.news&&S.snap.news.available)showStale('')}
function load(){fetch(location.origin+'/api/snapshot',{cache:'no-store',credentials:'same-origin'}).then(function(r){if(!r.ok)throw new Error('HTTP '+r.status);return r.json()}).then(render).catch(function(e){showStale('Não consegui buscar os dados ('+e.message+'). Tento de novo em 30 s.')})}
load();setInterval(load,30000);setInterval(tick,5000);
})();
