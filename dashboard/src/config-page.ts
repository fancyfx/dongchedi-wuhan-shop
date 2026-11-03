import './config-page.css'

export type ConfigRoute = {
  sku: string
  spec: string
}

type SpecMeta = {
  title?: string
  url?: string
  file?: string
}

type LiveIndex = {
  sku_to_spec?: Record<string, string | number>
  specs?: Record<string, SpecMeta>
}

type ConfigLine = {
  name?: string
  value?: unknown
  mark?: string
}

type ConfigItem = {
  name?: string
  value?: unknown
  lines?: unknown[]
}

type ConfigSection = {
  name?: string
  group?: string
  items?: unknown[]
}

type LivePayload = {
  schema_version?: string
  title?: string
  url?: string
  sections?: unknown[]
}

type GroupBlock = {
  group: string
  sections: ConfigSection[]
}

function esc(value: unknown): string {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
}

function safeDecode(value: string): string {
  try {
    return decodeURIComponent(value)
  } catch {
    return value
  }
}

function safeHttp(value: string): boolean {
  try {
    const url = new URL(value)
    return url.protocol === 'http:' || url.protocol === 'https:'
  } catch {
    return false
  }
}

function textOf(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function isLoneDash(value: string): boolean {
  return value.trim() === '-'
}

function paintMarks(escaped: string): string {
  return escaped
    .replaceAll('●', '<span class="mark-std">●</span>')
    .replaceAll('○', '<span class="mark-opt">○</span>')
}

function valueSpan(value: unknown): string {
  const text = value == null ? '' : String(value)
  if (isLoneDash(text)) return `<span class="mark-none">${esc(text)}</span>`
  return paintMarks(esc(text))
}

/** Query `?sku=` / `?spec=`, hash `#/config?sku=`, `#/config?spec=`, `#/config/{specId}`. */
export function parseConfigRoute(loc: { search: string; hash: string } = window.location): ConfigRoute | null {
  const search = new URLSearchParams(loc.search)
  let active = search.has('sku') || search.has('spec')
  let sku = search.has('sku') ? (search.get('sku') ?? '') : ''
  let spec = search.has('spec') ? (search.get('spec') ?? '') : ''

  const hash = loc.hash || ''
  if (hash.startsWith('#/config')) {
    const rest = hash.slice('#/config'.length)
    if (rest === '' || rest.startsWith('?') || rest.startsWith('/')) {
      active = true
      let pathSpec = ''
      let query = ''
      if (rest.startsWith('/')) {
        const qIdx = rest.indexOf('?')
        const raw = qIdx >= 0 ? rest.slice(1, qIdx) : rest.slice(1)
        pathSpec = safeDecode(raw.split('/')[0] || '').trim()
        query = qIdx >= 0 ? rest.slice(qIdx + 1) : ''
      } else if (rest.startsWith('?')) {
        query = rest.slice(1)
      }
      const hq = new URLSearchParams(query)
      if (hq.has('sku')) sku = hq.get('sku') ?? ''
      if (hq.has('spec')) spec = hq.get('spec') ?? ''
      else if (pathSpec) spec = pathSpec
    }
  }

  if (!active) return null
  return { sku: sku.trim(), spec: spec.trim() }
}

export function isConfigRoute(loc?: { search: string; hash: string }): boolean {
  return parseConfigRoute(loc) != null
}

async function fetchJson(url: string): Promise<unknown | null> {
  try {
    const res = await fetch(url)
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

function asIndex(data: unknown): LiveIndex | null {
  if (!data || typeof data !== 'object') return null
  return data as LiveIndex
}

function asPayload(data: unknown): LivePayload | null {
  if (!data || typeof data !== 'object') return null
  const sections = (data as LivePayload).sections
  if (!Array.isArray(sections) || sections.length === 0) return null
  return data as LivePayload
}

function resolveSpecId(route: ConfigRoute, index: LiveIndex | null): string {
  if (route.spec) return route.spec
  if (!route.sku || !index?.sku_to_spec) return ''
  const mapped = index.sku_to_spec[route.sku]
  if (mapped == null) return ''
  return String(mapped).trim()
}

function normalizeSection(raw: unknown): ConfigSection {
  if (raw && typeof raw === 'object') return raw as ConfigSection
  return { name: raw == null ? '' : String(raw), items: [] }
}

function normalizeItem(raw: unknown): ConfigItem {
  if (raw && typeof raw === 'object') return raw as ConfigItem
  return { name: '', value: raw == null ? '' : String(raw) }
}

function asLine(raw: unknown): ConfigLine {
  if (raw && typeof raw === 'object') return raw as ConfigLine
  return { value: raw == null ? '' : String(raw) }
}

function lineDisplayValue(line: ConfigLine): string {
  const value = line.value == null ? '' : String(line.value)
  if (isLoneDash(value)) return value
  const hasMark = value.includes('●') || value.includes('○')
  if (!hasMark && line.mark === 'standard') return value ? `● ${value}` : '●'
  if (!hasMark && line.mark === 'optional') return value ? `○ ${value}` : '○'
  return value
}

function lineHtml(line: ConfigLine): string {
  const shown = lineDisplayValue(line)
  const lone = isLoneDash(shown)
  const markClass = lone
    ? 'mark-none'
    : line.mark === 'standard' || shown.includes('●')
      ? 'mark-std'
      : line.mark === 'optional' || shown.includes('○')
        ? 'mark-opt'
        : ''
  const name = line.name == null || String(line.name) === ''
    ? ''
    : `<span class="cfg-line-name">${esc(line.name)}</span>`
  const body = lone ? `<span class="mark-none">${esc(shown)}</span>` : paintMarks(esc(shown))
  return `<div class="cfg-line ${markClass}">${name}<span class="cfg-line-value">${body}</span></div>`
}

function valueHtml(item: ConfigItem): string {
  const lines = Array.isArray(item.lines) && item.lines.length > 1 ? item.lines : null
  if (!lines) return `<div class="cfg-value">${valueSpan(item.value)}</div>`
  return `<div class="cfg-value"><div class="cfg-lines">${lines.map((line) => lineHtml(asLine(line))).join('')}</div></div>`
}

function itemHtml(raw: unknown): string {
  const item = normalizeItem(raw)
  const name = item.name == null ? '' : String(item.name)
  return `<div class="cfg-item"><div class="cfg-name">${esc(name)}</div>${valueHtml(item)}</div>`
}

function sectionHtml(raw: unknown): string {
  const section = normalizeSection(raw)
  const name = section.name == null ? '' : String(section.name)
  const items = Array.isArray(section.items) ? section.items : []
  return `<article class="cfg-section"><h3>${esc(name)}</h3><div class="cfg-items">${items.map(itemHtml).join('')}</div></article>`
}

function groupSections(sections: unknown[]): GroupBlock[] {
  const blocks: GroupBlock[] = []
  for (const raw of sections) {
    const section = normalizeSection(raw)
    const group = textOf(section.group)
    const last = blocks[blocks.length - 1]
    if (last && last.group === group) last.sections.push(section)
    else blocks.push({ group, sections: [section] })
  }
  return blocks
}

const GROUP_LABELS: Record<string, string> = {
  param: '参数',
  config: '配置',
  feature: '特色配置',
  ah100: 'AH-100',
  bag: '选装包',
}

function groupsHtml(sections: unknown[]): string {
  return groupSections(sections).map((block) => {
    const label = GROUP_LABELS[block.group] || ''
    const head = label ? `<h2>${esc(label)}</h2>` : ''
    return `<section class="cfg-group">${head}${block.sections.map(sectionHtml).join('')}</section>`
  }).join('')
}

function headerHtml(opts: { title: string; sku: string; specId: string; url: string }): string {
  const bits = [
    opts.sku ? `<span>SKU ${esc(opts.sku)}</span>` : '',
    opts.specId ? `<span>参配 ${esc(opts.specId)}</span>` : '',
    opts.url && safeHttp(opts.url)
      ? `<a href="${esc(opts.url)}" target="_blank" rel="noopener noreferrer">在汽车之家打开</a>`
      : '',
  ].filter(Boolean)
  const meta = bits.length ? `<div class="cfg-meta">${bits.join('')}</div>` : ''
  return `
    <header class="cfg-header">
      <a class="btn-link cfg-back" href="./">返回车源列表</a>
      <h1 class="cfg-title">${esc(opts.title)}</h1>
      ${meta}
    </header>`
}

function legendHtml(): string {
  return `
    <ul class="cfg-legend">
      <li><span class="mark-std">●</span> 标配</li>
      <li><span class="mark-opt">○</span> 选配</li>
      <li><span class="mark-none">-</span> 无</li>
    </ul>`
}

function missingHtml(sku: string, specId: string, title = ''): string {
  return `
    <div class="cfg-page">
      ${headerHtml({ title: title || '完整配置', sku, specId, url: '' })}
      <div class="empty cfg-missing">该车暂无汽车之家完整参配</div>
    </div>`
}

function pageHtml(payload: LivePayload, meta: SpecMeta | undefined, sku: string, specId: string): string {
  const title = textOf(payload.title) || textOf(meta?.title) || '完整配置'
  const url = textOf(payload.url) || textOf(meta?.url)
  return `
    <div class="cfg-page">
      ${headerHtml({ title, sku, specId, url })}
      ${legendHtml()}
      ${groupsHtml(payload.sections || [])}
    </div>`
}

export async function renderConfigPage(root: HTMLElement): Promise<void> {
  const route = parseConfigRoute()
  if (!route) {
    root.innerHTML = missingHtml('', '')
    return
  }
  root.innerHTML = `
    <div class="cfg-page">
      <a class="btn-link cfg-back" href="./">返回车源列表</a>
      <div class="loading">正在加载完整配置…</div>
    </div>`
  document.title = '完整配置 · 武汉店二手车看板'

  const index = asIndex(await fetchJson('/data/live-config/index.json'))
  const specId = resolveSpecId(route, index)
  if (!specId) {
    root.innerHTML = missingHtml(route.sku, '')
    return
  }

  const payload = asPayload(await fetchJson(`/data/live-config/${encodeURIComponent(specId)}.json`))
  const meta = index?.specs?.[specId]
  if (!payload) {
    root.innerHTML = missingHtml(route.sku, specId, textOf(meta?.title))
    return
  }

  const title = textOf(payload.title) || textOf(meta?.title) || '完整配置'
  document.title = `${title} · 完整配置`
  root.innerHTML = pageHtml(payload, meta, route.sku, specId)
}
