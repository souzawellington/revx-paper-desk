// Núcleo testável da página SIMULADA: autenticação, validação de snapshot e roteamento.
// Nunca contém segredos: utilizador/senha/token vêm de variáveis de ambiente da Vercel (DASH_USER, DASH_PASSWORD, INGEST_TOKEN).
import { createHash, timingSafeEqual } from 'node:crypto';
import { PAGE_HTML, APP_JS, EMS_HTML, EMS_JS, NEWS_HTML, NEWS_JS } from './page.mjs';

export const MAX_BYTES = 512 * 1024;
export const BLOB_PATH = 'snapshot/latest.json';
const STALE_REREAD_S = 180, BLOB_REREAD_EVERY_S = 300;

export function safeEqual(a, b) {
  const ha = createHash('sha256').update(String(a ?? '')).digest();
  const hb = createHash('sha256').update(String(b ?? '')).digest();
  return timingSafeEqual(ha, hb) && String(a ?? '').length === String(b ?? '').length;
}

export function checkBasic(header, user, pass) {
  if (!user || !pass || !header || !/^Basic\s+/i.test(header)) return false;
  let dec;
  try { dec = Buffer.from(header.replace(/^Basic\s+/i, ''), 'base64').toString('utf8'); } catch { return false; }
  const i = dec.indexOf(':');
  if (i < 0) return false;
  const okU = safeEqual(dec.slice(0, i), user), okP = safeEqual(dec.slice(i + 1), pass);
  return okU && okP;
}

export function checkBearer(header, token) {
  if (!token || token.length < 24 || !header || !/^Bearer\s+/i.test(header)) return false;
  return safeEqual(header.replace(/^Bearer\s+/i, '').trim(), token);
}

const BAD_VAL = [/-----BEGIN [A-Z ]+-----/, /private\.pem/i, /\.revx-keys/i, /REVX_[A-Z_]*\s*[=:]/, /\beyJ[\w-]{10,}\.[\w-]{10,}/];
const BAD_KEY = /(api[_-]?key|secret|token|passw|pwd|\bpem\b|private|credential|auth|cookie|session|signature|bearer|env|path|revx)/i;

export function findSecret(obj, secrets = []) {
  const s = JSON.stringify(obj);
  for (const x of secrets) if (x && x.length >= 6 && s.includes(x)) return 'segredo conhecido';
  for (const r of BAD_VAL) if (r.test(s)) return 'valor suspeito';
  let bad = null;
  (function walk(o, p) {
    if (bad) return;
    if (Array.isArray(o)) o.forEach((v, i) => walk(v, `${p}[${i}]`));
    else if (o && typeof o === 'object') for (const [k, v] of Object.entries(o)) { if (BAD_KEY.test(k)) { bad = `campo ${p}.${k}`; return; } walk(v, `${p}.${k}`); }
  })(obj, '$');
  return bad;
}

export function validateSnapshot(obj, nowS, secrets = []) {
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return 'não é objeto';
  if (obj.simulated !== true || obj.live_orders !== false) return 'só aceito snapshots SIMULADOS';
  if (obj.schema !== 1) return 'schema desconhecido';
  if (typeof obj.generated_at !== 'number' || obj.generated_at > nowS + 300 || obj.generated_at < nowS - 86400) return 'generated_at inválido';
  if (!Array.isArray(obj.bots)) return 'bots em falta';
  const leak = findSecret(obj, secrets);
  if (leak) return `rejeitado (${leak})`;
  return null;
}

const SEC_HEADERS = {
  'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY', 'Referrer-Policy': 'no-referrer',
  'Cache-Control': 'no-store, max-age=0', 'X-Robots-Tag': 'noindex, nofollow',
  'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
};
function res(status, body, type = 'application/json; charset=utf-8', extra = {}) {
  return new Response(typeof body === 'string' ? body : JSON.stringify(body), { status, headers: { 'Content-Type': type, ...SEC_HEADERS, ...extra } });
}

// mem: { snap, receivedAt, source, lastBlobRead } — estado em memória da instância (Fluid compute reutiliza a instância).
export function createApp({ env, store, nowS = () => Math.floor(Date.now() / 1000), mem = { snap: null, receivedAt: 0, source: 'none', lastBlobRead: 0 } }) {
  const user = env.DASH_USER, pass = env.DASH_PASSWORD, token = env.INGEST_TOKEN;
  const configured = !!(user && pass && pass.length >= 12 && token && token.length >= 24);
  const secrets = [pass, token].filter(Boolean);

  async function loadFromBlob() {
    if (!store) return;
    mem.lastBlobRead = nowS();
    try {
      const b = await store.get();
      if (b && typeof b.generated_at === 'number' && (!mem.snap || b.generated_at > mem.snap.generated_at) && !validateSnapshot(b, nowS(), secrets)) {
        mem.snap = b; mem.receivedAt = b.generated_at; mem.source = 'blob';
      }
    } catch (e) { mem.blobError = 'falha ao ler cópia durável'; }
  }

  return {
    mem,
    async handle(request) {
      const url = new URL(request.url);
      let path = url.searchParams.get('r') || url.pathname;
      if (path !== '/' && path.endsWith('/')) path = path.slice(0, -1);
      const m = request.method.toUpperCase();
      if (path === '/healthz') return res(200, { ok: true });
      if (!configured) return res(503, { error: 'página não configurada (variáveis de ambiente em falta)' });

      if (path === '/api/ingest') {
        if (m !== 'POST') return res(405, { error: 'só POST' }, undefined, { Allow: 'POST' });
        if (!checkBearer(request.headers.get('authorization'), token)) return res(401, { error: 'token inválido' });
        const len = Number(request.headers.get('content-length') || 0);
        if (len > MAX_BYTES) return res(413, { error: 'snapshot grande demais' });
        const text = await request.text();
        if (text.length > MAX_BYTES) return res(413, { error: 'snapshot grande demais' });
        let obj; try { obj = JSON.parse(text); } catch { return res(400, { error: 'JSON inválido' }); }
        const err = validateSnapshot(obj, nowS(), secrets);
        if (err) return res(422, { error: err });
        if (mem.snap && obj.generated_at < mem.snap.generated_at) return res(200, { ok: true, ignored: 'mais antigo que o atual' });
        mem.snap = obj; mem.receivedAt = nowS(); mem.source = 'memory';
        let persisted = false;
        if (request.headers.get('x-persist') === '1' && store) {
          try { await store.put(text); persisted = true; } catch (e) { return res(200, { ok: true, persisted: false, warn: 'cópia durável falhou' }); }
        }
        return res(200, { ok: true, persisted });
      }

      if (!checkBasic(request.headers.get('authorization'), user, pass))
        return res(401, 'Autenticação necessária', 'text/plain; charset=utf-8', { 'WWW-Authenticate': 'Basic realm="Bots SIMULADOS", charset="UTF-8"' });
      if (m !== 'GET' && m !== 'HEAD') return res(405, { error: 'só leitura' }, undefined, { Allow: 'GET' });

      if (path === '/' || path === '/index.html') return res(200, PAGE_HTML, 'text/html; charset=utf-8');
      if (path === '/app.js') return res(200, APP_JS, 'text/javascript; charset=utf-8');
      if (path === '/ems' || path === '/ems.html') return res(200, EMS_HTML, 'text/html; charset=utf-8');
      if (path === '/ems.js') return res(200, EMS_JS, 'text/javascript; charset=utf-8');
      if (path === '/news' || path === '/news.html') return res(200, NEWS_HTML, 'text/html; charset=utf-8');
      if (path === '/news.js') return res(200, NEWS_JS, 'text/javascript; charset=utf-8');
      if (path === '/api/snapshot') {
        const now = nowS();
        if (!mem.snap || (now - mem.receivedAt > STALE_REREAD_S && now - mem.lastBlobRead > BLOB_REREAD_EVERY_S)) await loadFromBlob();
        if (!mem.snap) return res(200, { snapshot: null, source: 'none', server_now: now });
        return res(200, { snapshot: mem.snap, source: mem.source, received_at: mem.receivedAt, server_now: now });
      }
      return res(404, { error: 'não encontrado' });
    },
  };
}
