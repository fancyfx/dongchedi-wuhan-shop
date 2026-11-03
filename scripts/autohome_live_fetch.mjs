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
    function normParamScalar(text) {
      const v = decodeHtml(text);
      if (v === '0' || v === '') return '-';
      return v;
    }
    function priceSuffix(price) {
      const n = Number(price);
      if (!(n > 1)) return '';
      return ` (¥${Number.isInteger(n) ? String(n) : String(n)})`;
    }
    function finalizeItem(item) {
      const lines = item.lines;
      if (!Array.isArray(lines) || !lines.length) {
        delete item.lines;
        return item;
      }
      const cleaned = [];
      for (const ln of lines) {
        const name = ln.name || '';
        const value = ln.value == null ? '' : String(ln.value);
        if (!name && !value) continue;
        const out = { name, value };
        if (ln.mark === 'standard' || ln.mark === 'optional') out.mark = ln.mark;
        cleaned.push(out);
      }
      // A single unnamed line is the plain value; keep lines only for real breakdowns.
      if (cleaned.length === 1 && !cleaned[0].name) delete item.lines;
      else if (!cleaned.length) delete item.lines;
      else item.lines = cleaned;
      return item;
    }
    function buildParamItem(p) {
      const name = decodeHtml(p.name);
      if (!name) return null;
      const vi = pick(p.valueitems);
      const dt = Number(p.displaytype);
      if (dt === 1 && vi && Array.isArray(vi.sublist) && vi.sublist.length) {
        const lines = [];
        for (const s of vi.sublist) {
          const subname = decodeHtml(s.subname || '');
          const sub = normParamScalar(s.subvalue);
          const ot = Number(s.optiontype);
          let value = sub;
          let mark;
          if (ot === 1) {
            value = sub === '-' ? '●' : `● ${sub}`;
            mark = 'standard';
          } else if (ot === 2) {
            value = sub === '-' ? '○' : `○ ${sub}`;
            mark = 'optional';
          }
          const line = { name: subname, value };
          if (mark) line.mark = mark;
          if (!subname && !value) continue;
          lines.push(line);
        }
        if (lines.length) {
          return finalizeItem({ name, value: lines.map((l) => l.value).join(' / '), lines });
        }
      }
      return { name, value: normParamScalar(vi ? vi.value : '') };
    }
    function buildConfigItem(c) {
      const name = decodeHtml(c.name);
      if (!name) return null;
      const vi = pick(c.valueitems);
      if (!vi) return { name, value: '-' };
      const subs = Array.isArray(vi.sublist) ? vi.sublist : [];
      if (!subs.length) {
        let value = decodeHtml(vi.value);
        if (!value) value = '-';
        return { name, value };
      }
      const lines = [];
      const displays = [];
      for (const s of subs) {
        const sn = decodeHtml(s.subname || '');
        const sv = s.subvalue == null ? '' : String(s.subvalue);
        const suffix = priceSuffix(s.price);
        if (sv === '1') {
          const lname = sn === '标配' ? '' : sn;
          const line = { name: lname, value: '●' + suffix, mark: 'standard' };
          lines.push(line);
          displays.push((lname ? `● ${lname}` : '●') + suffix);
        } else if (sv === '2') {
          const lname = sn === '选配' ? '' : sn;
          const line = { name: lname, value: '○' + suffix, mark: 'optional' };
          lines.push(line);
          displays.push((lname ? `○ ${lname}` : '○') + suffix);
        } else if (sn) {
          lines.push({ name: sn, value: sn + suffix });
          displays.push(sn + suffix);
        }
      }
      if (!lines.length) {
        let value = decodeHtml(vi.value);
        if (!value) value = '-';
        return { name, value };
      }
      return finalizeItem({ name, value: displays.join(' / '), lines });
    }
    function pushSection(sections, name, group, items) {
      const n = decodeHtml(name);
      if (!n || !items || !items.length) return;
      sections.push({ name: n, group, items });
    }
    function appendLoose(sections, nodes, group) {
      if (!Array.isArray(nodes) || !nodes.length) return;
      const grouped = nodes.some((n) => n && (
        Array.isArray(n.configitems) || Array.isArray(n.paramitems) ||
        Array.isArray(n.featureitems) || Array.isArray(n.items) || Array.isArray(n.ah100items)
      ));
      if (!grouped) return;
      for (const g of nodes) {
        if (!g) continue;
        const children = g.configitems || g.paramitems || g.featureitems || g.items || g.ah100items || [];
        const mode = Array.isArray(g.paramitems) && !Array.isArray(g.configitems) ? 'param' : 'config';
        const items = [];
        for (const child of children) {
          const item = mode === 'param' ? buildParamItem(child) : buildConfigItem(child);
          if (item) items.push(item);
        }
        pushSection(sections, g.name, group, items);
      }
    }
    function buildBagSections(sections) {
      const bag = window.bag && window.bag.result;
      const groups = bag && Array.isArray(bag.bagtypeitems) ? bag.bagtypeitems : [];
      for (const t of groups) {
        const picked = pick(t.bagitems || []);
        const vis = picked && Array.isArray(picked.valueitems) ? picked.valueitems : [];
        if (!vis.length) continue;
        const items = [];
        for (const vi of vis) {
          const iname = decodeHtml(vi.name);
          if (!iname) continue;
          let value = decodeHtml(vi.description || vi.value || '');
          if (!value) value = decodeHtml(vi.pricedesc || '') || '-';
          value += priceSuffix(vi.price);
          items.push({ name: iname, value });
        }
        pushSection(sections, t.name, 'bag', items);
      }
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
    const sections = [];
    for (const t of (window.config.result.paramtypeitems || [])) {
      const items = [];
      for (const p of t.paramitems || []) {
        const item = buildParamItem(p);
        if (item) items.push(item);
      }
      pushSection(sections, t.name, 'param', items);
    }
    const opt = window.option && window.option.result ? window.option.result : {};
    for (const t of (opt.configtypeitems || [])) {
      const items = [];
      for (const c of t.configitems || []) {
        const item = buildConfigItem(c);
        if (item) items.push(item);
      }
      pushSection(sections, t.name, 'config', items);
    }
    appendLoose(sections, opt.featureitems, 'feature');
    appendLoose(sections, opt.Ah100items, 'ah100');
    buildBagSections(sections);
    return {
      spec_id: sid,
      ok: Object.keys(rows).length >= 30,
      row_count: Object.keys(rows).length,
      title: carTitle || document.title,
      rows,
      sections,
      section_count: sections.length,
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
  const writeOut = () => {
    fs.mkdirSync(path.dirname(path.resolve(args.outPath)), { recursive: true });
    fs.writeFileSync(args.outPath, JSON.stringify({
      generated_at: new Date().toISOString(),
      source: 'car.autohome.com.cn/config/spec',
      count: args.ids.length,
      results,
    }, null, 2));
  };
  try {
    for (let i = 0; i < args.ids.length; i++) {
      const id = args.ids[i];
      process.stderr.write(`[${i + 1}/${args.ids.length}] fetch spec ${id}...\n`);
      try {
        const decoded = await decodeSpec(page, id, args.timeoutMs);
        decoded.fetched_at = new Date().toISOString();
        if (Array.isArray(decoded.sections)) decoded.section_count = decoded.sections.length;
        results[String(id)] = decoded;
        process.stderr.write(`  ok=${decoded.ok} rows=${decoded.row_count} sections=${decoded.section_count || 0} map=${decoded.map_size}\n`);
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
      writeOut();
      if (i + 1 < args.ids.length) await new Promise((r) => setTimeout(r, args.delayMs));
    }
  } finally {
    writeOut();
    await browser.close();
  }
  const ok = Object.values(results).filter((r) => r.ok).length;
  process.stderr.write(`done: ${ok}/${args.ids.length} ok -> ${args.outPath}\n`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
