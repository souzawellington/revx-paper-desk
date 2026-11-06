// Função única (Fluid compute): página com Basic Auth, JSON do snapshot e endpoint de ingestão da box.
import { put, get } from '@vercel/blob';
import { createApp, BLOB_PATH } from '../lib/core.mjs';

const store = process.env.BLOB_READ_WRITE_TOKEN ? {
  async put(text) {
    await put(BLOB_PATH, text, { access: 'private', addRandomSuffix: false, allowOverwrite: true, contentType: 'application/json', cacheControlMaxAge: 60 });
  },
  async get() {
    const r = await get(BLOB_PATH, { access: 'private', useCache: false });
    if (!r || !r.stream) return null;
    return JSON.parse(await new Response(r.stream).text());
  },
} : null;

const app = createApp({ env: process.env, store });
export default { fetch: (request) => app.handle(request) };
