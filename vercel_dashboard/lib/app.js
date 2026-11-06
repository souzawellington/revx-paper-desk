(function(){
'use strict';
var STALE_S = 300, TZ = 'Europe/London';
function $(id){return document.getElementById(id)}
function el(tag, cls, text){var e=document.createElement(tag); if(cls) e.className=cls; if(text!==undefined&&text!==null) e.textContent=String(text); return e}
function n(x,d){return (typeof x==='number'&&isFinite(x))?x.toLocaleString('pt-BR',{minimumFractionDigits:d,maximumFractionDigits:d}):'—'}
function usd(x){return (typeof x==='number'&&isFinite(x))?'$'+n(x,2):'—'}
function px(x){if(typeof x!=='number'||!isFinite(x))return '—'; var d=x>=1000?2:x>=1?4:6; return n(x,d)}
function pct(x){return (typeof x==='number'&&isFinite(x))?(x>=0?'+':'')+n(x*100,2)+'%':'—'}
function cls(x){return (typeof x==='number'&&x<0)?'neg':(typeof x==='number'&&x>0?'pos':'')}
function london(s){try{return new Intl.DateTimeFormat('pt-BR',{timeZone:TZ,day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'}).format(new Date(s*1000))}catch(e){return '—'}}
function table(heads, rows){var w=el('div','scroll'),t=el('table'),tr=el('tr');heads.forEach(function(h){tr.appendChild(el('th',null,h))});t.appendChild(tr);
  rows.forEach(function(r){var row=el('tr');r.forEach(function(c){var td=el('td',c&&c.c,c&&c.t!==undefined?c.t:c);row.appendChild(td)});t.appendChild(row)});w.appendChild(t);return w}
function spark(curve){
  var ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 300 60');svg.setAttribute('preserveAspectRatio','none');
  if(!curve||curve.length<2)return svg;
  var xs=curve.map(function(p){return p[0]}),ys=curve.map(function(p){return p[1]});
  var x0=Math.min.apply(null,xs),x1=Math.max.apply(null,xs),y0=Math.min.apply(null,ys),y1=Math.max.apply(null,ys);if(y1-y0<1e-9){y0-=1;y1+=1}if(x1===x0)x1=x0+1;
  var d=curve.map(function(p,i){return (i?'L':'M')+((p[0]-x0)/(x1-x0)*298+1).toFixed(1)+' '+(58-(p[1]-y0)/(y1-y0)*56).toFixed(1)}).join(' ');
  var path=document.createElementNS(ns,'path');path.setAttribute('d',d);path.setAttribute('fill','none');path.setAttribute('stroke',ys[ys.length-1]>=ys[0]?'#22c55e':'#ef4444');path.setAttribute('stroke-width','2');path.setAttribute('vector-effect','non-scaling-stroke');svg.appendChild(path);return svg}
function botCard(b){
  var c=el('div','card');var h=el('div','row');h.appendChild(el('h2',null,b.name||b.key));
  var st=el('span','pill '+(b.killed||b.any_tripped?'bad':(String(b.state||'').indexOf('RUNNING')===0?'ok':'warn')),b.killed?'KILL (parado)':(b.state||'?'));h.appendChild(st);c.appendChild(h);
  if(b.available===false){c.appendChild(el('div','mut',b.state||'indisponível'));return c}
  var r=el('div','row');var eq=el('div','big',usd(b.equity));r.appendChild(eq);var pl=el('div',cls(b.pnl));pl.textContent=(b.pnl>=0?'+':'')+usd(b.pnl).replace('$-','-$')+'  ('+pct(b.pnl_pct)+')';r.appendChild(pl);c.appendChild(r);
  c.appendChild(el('div','mut','Início '+usd(b.start)+' · Queda desde o pico (DD) '+pct(-(b.drawdown||0)).replace('+','')+' · Teto '+usd(b.ceiling)+(b.ceiling_latched?' (ATINGIDO)':'')));
  var bar=el('div','bar'),i=el('i');i.style.width=Math.max(0,Math.min(100,(b.ceiling_progress||0)*100)).toFixed(1)+'%';bar.appendChild(i);c.appendChild(bar);
  c.appendChild(spark(b.curve));
  var ps=b.positions||[];
  c.appendChild(el('div','mut',ps.length?('Posições abertas: '+ps.length):'Sem posições abertas'));
  if(ps.length)c.appendChild(table(['Moeda','Entrada','Agora','Stop','Alvo','Resultado'],ps.map(function(p){return [p.coin,px(p.entry),px(p.price),px(p.stop),px(p.tp),{t:usd(p.unrealized)+' '+pct(p.unrealized_pct),c:cls(p.unrealized)}]})));
  var rc=b.recent||[];
  if(rc.length){var d=el('details');d.appendChild(el('summary',null,'Últimas operações ('+rc.length+')'));
    d.appendChild(table(['Hora','Moeda','Lado','Preço','Resultado','Motivo'],rc.map(function(t){return [t.ts||'—',t.coin,t.side,px(t.price),{t:t.pnl!=null?usd(t.pnl):(t.notional!=null?usd(t.notional):'—'),c:cls(t.pnl)},(t.reason||t.status||'')]})));c.appendChild(d)}
  var cr=b.criteria||[];
  if(cr.length){var d2=el('details');d2.appendChild(el('summary',null,'Critérios de parada automática'+(b.any_tripped?' — ALGUM DISPAROU':'')));
    d2.appendChild(table(['Critério','Valor','Limite','Estado'],cr.map(function(k){return [k.name,k.value,k.limit,{t:k.status,c:k.tripped?'neg':''}]})));c.appendChild(d2)}
  if(b.last_run)c.appendChild(el('div','mut','Última execução do bot: '+b.last_run));
  return c}
function deskCard(d){
  var c=$('desk');c.textContent='';c.appendChild(el('h2',null,'Auditor da mesa (regras do GO)'));
  if(!d||d.error){c.appendChild(el('div','mut',d&&d.error||'sem dados'));return}
  var th=d.thresholds||{},ck=d.checks||{};
  c.appendChild(table(['Métrica','Atual','Meta','OK?'],[
    ['Trades',String(d.n),'≥ '+th.threshold_trades,ck.trades?'sim':'não'],
    ['Taxa de acerto',pct(d.win_rate).replace('+',''),'≥ '+pct(th.threshold_win_rate).replace('+',''),ck.win_rate?'sim':'não'],
    ['Expectativa (R)',n(d.expectancy_r,2),'≥ '+n(th.threshold_expectancy_r,2),ck.expectancy_r?'sim':'não'],
    ['Queda máx. (DD)',pct(d.max_dd).replace('+',''),'≤ '+pct(th.threshold_max_dd).replace('+',''),ck.max_dd?'sim':'não']]));
  c.appendChild(el('div','mut','GO: '+(d.go?'SIM':'ainda não')+' · ensaio rápido: '+(d.fast?d.fast.n:0)+' trades'));
  if((d.open||[]).length)c.appendChild(table(['Aberta','Entrada','Stop','Alvo','Desde'],d.open.map(function(p){return [p.coin,px(p.entry),px(p.stop),px(p.tp),p.opened||'—']})));
  if((d.results||[]).length){var x=el('details');x.appendChild(el('summary',null,'Últimos resultados'));x.appendChild(table(['Hora','Moeda','R','US$'],d.results.map(function(r){return [r.ts||'—',r.coin,{t:n(r.r,2),c:cls(r.r)},{t:usd(r.usd),c:cls(r.usd)}]})));c.appendChild(x)}
}
var last=null;
function render(j){
  var s=j&&j.snapshot;
  if(!s){$('upd').textContent='sem dados ainda';showStale('Ainda não chegaram dados da box.');return}
  last=s.generated_at;$('upd').textContent=london(s.generated_at)+' (Londres)';$('mode').textContent=(s.execution_mode||'?')+' · SIMULADO';
  var P=(s.prices||{}).px||{},pr=$('prices');pr.textContent='';Object.keys(P).forEach(function(k){var v=P[k]||{},sp=el('span');sp.appendChild(el('b',null,k.replace('-USD','')+' '));sp.appendChild(document.createTextNode(px(v.mid)+' '));sp.appendChild(el('span',cls(v.chg24),pct(v.chg24)));pr.appendChild(sp)});
  $('pxinfo').textContent=(s.prices&&s.prices.error)?('⚠ '+s.prices.error):(s.prices&&s.prices.stale?'preços atrasados':'');
  var bx=$('bots');bx.textContent='';(s.bots||[]).forEach(function(b){bx.appendChild(botCard(b))});
  var off=el('div','card');off.appendChild(el('h2',null,'Bot C · day-trade'));off.appendChild(el('span','pill','DESLIGADO (só liga com ordem sua)'));bx.appendChild(off);
  deskCard(s.desk);tick()}
function showStale(msg){var e=$('stale');e.textContent=msg;e.style.display=msg?'block':'none'}
function tick(){if(!last)return;var a=Math.floor(Date.now()/1000)-last;$('age').textContent='· há '+(a<90?a+' s':Math.round(a/60)+' min');
  showStale(a>STALE_S?('⚠ DADOS ATRASADOS: última atualização há '+Math.round(a/60)+' min (mais de 5 min). O envio da box pode ter parado — os números abaixo podem estar desatualizados.'):'')}
function load(){fetch(location.origin+'/api/snapshot',{cache:'no-store',credentials:'same-origin'}).then(function(r){if(!r.ok)throw new Error('HTTP '+r.status);return r.json()}).then(render).catch(function(e){showStale('Não consegui buscar os dados ('+e.message+'). Tento de novo em 30 s.')})}
load();setInterval(load,30000);setInterval(tick,5000);
document.addEventListener('visibilitychange',function(){if(!document.hidden)load()});
})();
