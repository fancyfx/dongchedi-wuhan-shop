#!/usr/bin/env node
/**
 * Fetch AutoHome exact-trim config pages and decode hs_kw obfuscation.
 *
 * Usage:
 *   node scripts/autohome_live_fetch.mjs --out data.json 49472 25892
 *   node scripts/autohome_live_fetch.mjs --out data.json --ids-file ids.txt
 *
 * Requires puppeteer-core and a local Chrome. Resolves modules from
 * .external/autohome-live-node when present.
 */
import { createRequire } from 'module';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const require = createRequire(path.join(ROOT, '.external/autohome-live-node/package.json'));

let puppeteer;
try {
  puppeteer = require('puppeteer-core');
} catch (err) {
  console.error('puppeteer-core missing; run: cd .external/autohome-live-node && npm install puppeteer-core@23');
  process.exit(2);
}

function parseArgs(argv) {
  const out = { ids: [], outPath: null, delayMs: 800, timeoutMs: 60000, chrome: process.env.CHROME_PATH || '/usr/bin/google-chrome' };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--out') out.outPath = argv[++i];
    else if (a === '--ids-file') {
      const text = fs.readFileSync(argv[++i], 'utf8');
      for (const line of text.split(/\s+/)) if (/^\d+$/.test(line)) out.ids.push(Number(line));
    } else if (a === '--delay-ms') out.delayMs = Number(argv[++i]);
    else if (a === '--timeout-ms') out.timeoutMs = Number(argv[++i]);
    else if (a === '--chrome') out.chrome = argv[++i];
    else if (/^\d+$/.test(a)) out.ids.push(Number(a));
  }
  out.ids = [...new Set(out.ids)];
  if (!out.outPath) throw new Error('--out is required');
  if (!out.ids.length) throw new Error('no spec ids');
  return out;
}

async function decodeSpec(page, specId, timeoutMs) {
  const url = `https://car.autohome.com.cn/config/spec/${specId}.html`;
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: timeoutMs });
  await page.waitForFunction(() => window.config && window.config.result && window.option && window.option.result, { timeout: timeoutMs });
  await page.waitForFunction(() => {
    let c = 0, o = 0;
    for (const sheet of document.styleSheets) {
      let rules;
      try { rules = sheet.cssRules; } catch { continue; }
      for (const rule of rules) {
        const s = rule.selectorText || '';
        if (/_config/i.test(s)) c++;
        if (/_option/i.test(s)) o++;
      }
    }
    return c > 10 && o > 10;
  }, { timeout: timeoutMs });

  return page.evaluate((sid) => {
    const map = {};
    for (const sheet of document.styleSheets) {
      let rules;
      try { rules = sheet.cssRules; } catch { continue; }
      for (const rule of rules) {
        const m = (rule.selectorText || '').match(/\.hs_kw(\d+)_(\w+)/i);
        if (!m) continue;
        const content = ((rule.style && rule.style.content) || '').replace(/^["']|["']$/g, '');
        if (content && content !== 'none') map[`${m[2].toLowerCase()}:${m[1]}`] = content;
      }
    }
    function decodeHtml(html) {
      if (html == null) return '';
      return String(html)
        .replace(/&nbsp;/g, ' ')
        .replace(/<span class=['"]hs_kw(\d+)_(\w+)['"]><\/span>/gi, (_, idx, suf) => map[`${String(suf).toLowerCase()}:${idx}`] || '')
        .replace(/<[^>]+>/g, '')
        .replace(/\s+/g, ' ')
        .trim();
    }
    function pick(items) {
      if (!items || !items.length) return null;
      return items.find((v) => String(v.specid) === String(sid)) || items[0];
    }
    function valueFromItem(vi) {
      if (!vi) return '';
      let val = decodeHtml(vi.value);
      const subs = Array.isArray(vi.sublist) ? vi.sublist : [];
      if (subs.length) {
        const equipped = [];
        for (const s of subs) {
          const sn = decodeHtml(s.subname || s.name || '');
          const raw = s.subvalue != null ? s.subvalue : (s.valueitem ? s.valueitem.value : '');
          const marker = typeof raw === 'number'
            ? (raw === 1 ? '●' : raw === 0 ? '-' : String(raw))
            : decodeHtml(raw);
          if (!sn) continue;
          if (marker === '●' || marker === 1 || marker === '1') equipped.push(sn);
          else if (marker && marker !== '-' && marker !== '0') equipped.push(`${sn}:${marker}`);
        }
        if (equipped.length) {
          if (!val || val === '●') val = equipped.join('|');
          else val = `${val}|${equipped.join('|')}`;
        } else if (!val) {
          val = '-';
        }
      }
      return val;
    }
    const rows = {};
    for (const t of (window.config.result.paramtypeitems || [])) {
      for (const p of t.paramitems || []) {
        const name = decodeHtml(p.name);
        if (name) rows[name] = valueFromItem(pick(p.valueitems));
      }
    }
    for (const t of (window.option.result.configtypeitems || [])) {
      for (const c of t.configitems || []) {
        const name = decodeHtml(c.name);
        if (name) rows[name] = valueFromItem(pick(c.valueitems));
      }
    }
    let carTitle = '';
    for (const [k, v] of Object.entries(rows)) {
      if (k === '车型名称' || k === '车型') { carTitle = v; break; }
    }
    return {
      spec_id: sid,
      ok: Object.keys(rows).length >= 30,
      row_count: Object.keys(rows).length,
      title: carTitle || document.title,
      rows,
      map_size: Object.keys(map).length,
      url: `https://car.autohome.com.cn/config/spec/${sid}.html`,
    };
  }, specId);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const browser = await puppeteer.launch({
    executablePath: args.chrome,
    headless: 'new',
    args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage'],
  });
  const page = await browser.newPage();
  await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36');
  await page.setExtraHTTPHeaders({ 'Accept-Language': 'zh-CN,zh;q=0.9' });

  const results = {};
  for (let i = 0; i < args.ids.length; i++) {
    const id = args.ids[i];
    process.stderr.write(`[${i + 1}/${args.ids.length}] fetch spec ${id}...\n`);
    try {
      const decoded = await decodeSpec(page, id, args.timeoutMs);
      results[String(id)] = decoded;
      process.stderr.write(`  ok=${decoded.ok} rows=${decoded.row_count} map=${decoded.map_size}\n`);
    } catch (err) {
      results[String(id)] = {
        spec_id: id,
        ok: false,
        error: String(err && err.message ? err.message : err),
        rows: {},
        row_count: 0,
        url: `https://car.autohome.com.cn/config/spec/${id}.html`,
      };
      process.stderr.write(`  FAIL ${err.message || err}\n`);
    }
    if (i + 1 < args.ids.length) await new Promise((r) => setTimeout(r, args.delayMs));
  }
  await browser.close();
  fs.mkdirSync(path.dirname(path.resolve(args.outPath)), { recursive: true });
  fs.writeFileSync(args.outPath, JSON.stringify({
    generated_at: new Date().toISOString(),
    source: 'car.autohome.com.cn/config/spec',
    count: args.ids.length,
    results,
  }, null, 2));
  const ok = Object.values(results).filter((r) => r.ok).length;
  process.stderr.write(`done: ${ok}/${args.ids.length} ok -> ${args.outPath}\n`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
