import test from 'node:test';
import assert from 'node:assert/strict';
import { createApp, checkBasic, checkBearer, validateSnapshot, findSecret } from '../lib/core.mjs';

// Synthetic unit-test fixtures only. They are not a real user, password, or ingest token.
const ENV = { DASH_USER: 'paper', DASH_PASSWORD: 'pw-for-tests-123456', INGEST_TOKEN: 'ingest-token-for-tests-0123456789abcdef' };
const B = 'https://x.test';
const basic = (u, p) => 'Basic ' + Buffer.from(`${u}:${p}`).toString('base64');
let T = 1_800_000_000;
const snap = (o = {}) => ({ schema: 1, simulated: true, live_orders: false, generated_at: T, execution_mode: 'paper_autonomous', bots: [{ key: 'B_bh_btc', equity: 65.5 }], ...o });
function fakeStore() { const s = { data: null, puts: 0, gets: 0, async put(t) { s.puts++; s.data = t; }, async get() { s.gets++; return s.data ? JSON.parse(s.data) : null; } }; return s; }
const mk = (store = fakeStore(), env = ENV) => ({ store, app: createApp({ env, store, nowS: () => T }) });
const ingest = (app, body, extra = {}) => app.handle(new Request(B + '/api/ingest', { method: 'POST', headers: { authorization: 'Bearer ' + ENV.INGEST_TOKEN, 'content-type': 'application/json', ...extra }, body: typeof body === 'string' ? body : JSON.stringify(body) }));
const getp = (app, p, auth) => app.handle(new Request(B + p, { headers: auth ? { authorization: auth } : {} }));

test('basic auth: certo / errado / ausente', () => {
  assert.equal(checkBasic(basic('paper', ENV.DASH_PASSWORD), 'paper', ENV.DASH_PASSWORD), true);
  assert.equal(checkBasic(basic('paper', 'x'), 'paper', ENV.DASH_PASSWORD), false);
  assert.equal(checkBasic(basic('outro', ENV.DASH_PASSWORD), 'paper', ENV.DASH_PASSWORD), false);
  assert.equal(checkBasic(null, 'paper', ENV.DASH_PASSWORD), false);
  assert.equal(checkBasic(basic('paper', ''), 'paper', ''), false);
});

test('bearer: exige token longo e exato', () => {
  assert.equal(checkBearer('Bearer ' + ENV.INGEST_TOKEN, ENV.INGEST_TOKEN), true);
  assert.equal(checkBearer('Bearer ' + ENV.INGEST_TOKEN + 'x', ENV.INGEST_TOKEN), false);
  assert.equal(checkBearer('Bearer short', 'short'), false);
});

test('página, app.js e snapshot pedem senha (401 + WWW-Authenticate)', async () => {
  const { app } = mk();
  for (const p of ['/', '/app.js', '/api/snapshot', '/qualquer']) {
    const r = await getp(app, p); assert.equal(r.status, 401, p);
    assert.match(r.headers.get('www-authenticate'), /Basic/);
  }
  const r = await getp(app, '/', basic('paper', 'errada')); assert.equal(r.status, 401);
});

test('rewrite ?r= também é protegido', async () => {
  const { app } = mk();
  assert.equal((await getp(app, '/api/main?r=/api/snapshot')).status, 401);
});

test('fluxo: ingest -> snapshot com senha devolve dados', async () => {
  const { app, store } = mk();
  assert.equal((await ingest(app, snap())).status, 200);
  assert.equal(store.puts, 0, 'sem X-Persist não grava no Blob');
  const r = await getp(app, '/api/snapshot', basic('paper', ENV.DASH_PASSWORD));
  assert.equal(r.status, 200); assert.equal(r.headers.get('cache-control'), 'no-store, max-age=0');
  const j = await r.json(); assert.equal(j.source, 'memory'); assert.equal(j.snapshot.bots[0].equity, 65.5);
  const h = await getp(app, '/', basic('paper', ENV.DASH_PASSWORD));
  assert.equal(h.status, 200); const html = await h.text(); assert.match(html, /SIMULADO/);
  assert.match(h.headers.get('content-security-policy'), /default-src 'none'/);
});

test('X-Persist grava no Blob e instância fria recupera do Blob', async () => {
  const store = fakeStore();
  const a = createApp({ env: ENV, store, nowS: () => T });
  const r = await ingest(a, snap(), { 'x-persist': '1' }); assert.deepEqual(await r.json(), { ok: true, persisted: true });
  assert.equal(store.puts, 1);
  const cold = createApp({ env: ENV, store, nowS: () => T + 10 });
  const j = await (await getp(cold, '/api/snapshot', basic('paper', ENV.DASH_PASSWORD))).json();
  assert.equal(j.source, 'blob'); assert.equal(j.snapshot.generated_at, T);
  // leituras do Blob são limitadas: com memória fresca não volta a ler
  await getp(cold, '/api/snapshot', basic('paper', ENV.DASH_PASSWORD)); assert.equal(store.gets, 1);
});

test('ingest rejeita token errado, não-simulado, live_orders, segredos', async () => {
  const { app } = mk();
  const bad = await app.handle(new Request(B + '/api/ingest', { method: 'POST', headers: { authorization: 'Bearer nope-nope-nope-nope-nope-nope' }, body: '{}' }));
  assert.equal(bad.status, 401);
  const basicOnly = await app.handle(new Request(B + '/api/ingest', { method: 'POST', headers: { authorization: basic('paper', ENV.DASH_PASSWORD) }, body: JSON.stringify(snap()) }));
  assert.equal(basicOnly.status, 401, 'senha da página não serve para ingest');
  assert.equal((await ingest(app, snap({ simulated: false }))).status, 422);
  assert.equal((await ingest(app, snap({ live_orders: true }))).status, 422);
  assert.equal((await ingest(app, snap({ note: '-----BEGIN PRIVATE KEY-----abc' }))).status, 422);
  assert.equal((await ingest(app, snap({ api_key: 'x' }))).status, 422);
  assert.equal((await ingest(app, snap({ bots: [{ key: 'x', note: ENV.DASH_PASSWORD }] }))).status, 422);
  assert.equal((await ingest(app, snap({ msg: 'see /home/box/.revx-keys/private.pem' }))).status, 422);
  assert.equal((await ingest(app, snap({ generated_at: T + 3600 }))).status, 422);
  assert.equal((await ingest(app, '{nope')).status, 400);
  assert.equal((await ingest(app, 'x'.repeat(600 * 1024))).status, 413);
});

test('snapshot mais antigo é ignorado', async () => {
  const { app } = mk();
  await ingest(app, snap({ generated_at: T }));
  const j = await (await ingest(app, snap({ generated_at: T - 60 }))).json();
  assert.ok(j.ignored);
});

test('sem variáveis de ambiente: falha fechada (503), healthz não expõe dados', async () => {
  const app = createApp({ env: {}, store: null });
  assert.equal((await getp(app, '/')).status, 503);
  const h = await getp(app, '/healthz'); assert.equal(h.status, 200); assert.deepEqual(await h.json(), { ok: true });
});

test('métodos de escrita na página são recusados', async () => {
  const { app } = mk();
  const r = await app.handle(new Request(B + '/api/snapshot', { method: 'POST', headers: { authorization: basic('paper', ENV.DASH_PASSWORD) }, body: '{}' }));
  assert.equal(r.status, 405);
});

test('validateSnapshot / findSecret', () => {
  assert.equal(validateSnapshot(snap(), T), null);
  assert.ok(findSecret({ a: { REVX_API_KEY: 1 } }));
  assert.ok(findSecret({ a: 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.x' }));
  assert.equal(findSecret({ key: 'B_bh_btc', coin: 'BTC-USD' }), null);
});

test('página não tem segredos embutidos', async () => {
  const { PAGE_HTML, APP_JS } = await import('../lib/page.mjs');
  for (const s of [PAGE_HTML, APP_JS]) { assert.doesNotMatch(s, /BEGIN [A-Z ]*KEY|REVX_API_KEY|INGEST_TOKEN|DASH_PASSWORD/); }
  assert.match(APP_JS, /Europe\/London/); assert.match(APP_JS, /STALE_S = 300/);
});

test('EMS: /ems e /ems.js atrás da mesma autenticação, só leitura, sem botões de ordem/live', async () => {
  const { app } = mk();
  assert.equal((await getp(app, '/ems')).status, 401);
  assert.equal((await getp(app, '/ems.js')).status, 401);
  const h = await app.handle(new Request(B + '/ems', { headers: { authorization: basic('paper', ENV.DASH_PASSWORD) } }));
  assert.equal(h.status, 200); const html = await h.text();
  assert.match(html, /<script src="\/ems.js"><\/script>/); assert.match(html, /PAPER ONLY/);
  assert.doesNotMatch(html, /cdn|tailwind|fontawesome|https?:\/\//i);
  const j = await app.handle(new Request(B + '/ems.js', { headers: { authorization: basic('paper', ENV.DASH_PASSWORD) } }));
  assert.equal(j.status, 200); const js = await j.text();
  assert.doesNotMatch(js, /Math\.random|method:\s*['"]POST|promote|kill_switch|REVX_API_KEY|INGEST_TOKEN|DASH_PASSWORD/);
  assert.doesNotMatch(html + js, /<button[^>]*(kill|live|promote)/i);
  assert.match(js, /Europe\/London/);
});

test('NEWS: /news e /news.js atrás da mesma autenticação, só leitura, sem links externos nem botões', async () => {
  const { app } = mk();
  assert.equal((await getp(app, '/news')).status, 401);
  assert.equal((await getp(app, '/news.js')).status, 401);
  const h = await app.handle(new Request(B + '/news', { headers: { authorization: basic('paper', ENV.DASH_PASSWORD) } }));
  assert.equal(h.status, 200); const html = await h.text();
  assert.match(html, /<script src="\/news.js"><\/script>/); assert.match(html, /PAPER ONLY/);
  assert.doesNotMatch(html, /cdn|tailwind|fontawesome|https?:\/\//i);
  const j = await app.handle(new Request(B + '/news.js', { headers: { authorization: basic('paper', ENV.DASH_PASSWORD) } }));
  assert.equal(j.status, 200); const js = await j.text();
  assert.doesNotMatch(js, /Math\.random|method:\s*['"]POST|promote|kill_switch|REVX_API_KEY|INGEST_TOKEN|DASH_PASSWORD|innerHTML=r\.title/);
  assert.doesNotMatch(html + js, /<button[^>]*(kill|live|promote)/i);
  assert.match(js, /Europe\/London/); assert.match(js, /esc\(r\.title\)/);
});
