// node build_page.mjs — gera lib/page.mjs a partir de lib/page.html + lib/app.js
import fs from 'node:fs';
const h = fs.readFileSync(new URL('./lib/page.html', import.meta.url), 'utf8');
const j = fs.readFileSync(new URL('./lib/app.js', import.meta.url), 'utf8');
const eh = fs.readFileSync(new URL('./lib/ems.html', import.meta.url), 'utf8');
const ej = fs.readFileSync(new URL('./lib/ems.js', import.meta.url), 'utf8');
const nh = fs.readFileSync(new URL('./lib/news.html', import.meta.url), 'utf8');
const nj = fs.readFileSync(new URL('./lib/news.js', import.meta.url), 'utf8');
fs.writeFileSync(new URL('./lib/page.mjs', import.meta.url), '// GERADO por build_page.mjs a partir de lib/page.html, lib/app.js, lib/ems.html, lib/ems.js, lib/news.html e lib/news.js — não editar à mão.\nexport const PAGE_HTML = ' + JSON.stringify(h) + ';\nexport const APP_JS = ' + JSON.stringify(j) + ';\nexport const EMS_HTML = ' + JSON.stringify(eh) + ';\nexport const EMS_JS = ' + JSON.stringify(ej) + ';\nexport const NEWS_HTML = ' + JSON.stringify(nh) + ';\nexport const NEWS_JS = ' + JSON.stringify(nj) + ';\n');
