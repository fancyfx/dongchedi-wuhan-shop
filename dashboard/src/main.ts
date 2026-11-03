import './style.css'
import { isConfigRoute, renderConfigPage } from './config-page'

type DataIssue = {
  code: string
  message: string
  severity?: string
  field?: string
}

type SortScores = {
  config_proxy?: number | null
  space_proxy?: number | null
  fuel_proxy?: number | null
  is_suv?: boolean
  price?: number
  config_norm?: number | null
  space_norm?: number | null
  fuel_norm?: number | null
  price_score?: number
  suv_score?: number
  total_score?: number | null
  config_score?: number | null
  operating_cost_score?: number
  space_score?: number
  age_score?: number
  mileage_score?: number
  body_preference_score?: number
  data_quality_score?: number
  effective_price_wan?: number
  score_version?: string
}

type OwnerReviews = {
  summary?: string
  pros?: string[]
  cons?: string[]
  drawbacks?: string[]
  sources?: { title: string; url: string }[]
  found?: boolean
  cons_note?: string
}

type Specs = {
  specs_found?: boolean
  specs_approx?: boolean
  verified?: boolean
  match_level?: string
  configuration_source?: string
  powertrain_type?: string
  engine?: string
  wheelbase_mm?: number
  seats?: number
  body_type?: string
  features?: Record<string, unknown>
  source_url?: string
  notes?: string
}

type Listing = {
  sku: string
  title: string
  price: number
  price_type?: string
  year?: string
  plate_year?: number
  model_year?: number
  mileage_wan?: number
  city?: string
  tags?: string[]
  badges?: string[]
  detail_url: string
  shop_id?: string
  brand?: string
  manufacturer?: string
  total_score?: number | null
  evaluation?: string
  rank?: number | null
  sort_scores?: SortScores
  owner_reviews?: OwnerReviews
  specs?: Specs
  detailed_config?: Specs
  score_version?: string
  effective_price_wan?: number
  needs_cash_quote?: boolean
  condition_gate?: string
  score_warnings?: string[]
  score_eligible?: boolean
  data_issues?: DataIssue[]
  config_coverage?: number
}

type Meta = {
  shop_name?: string
  shop_id?: string
  filters?: Record<string, string | number>
  price_filter?: string
  mileage_filter?: string
  age_filter?: string
  captured_at?: string
  ranked_at?: string
  ranked_count?: number
  data_issue_count?: number
  filtered_count?: number
  notes?: string
  sort_preference?: string | string[]
  sort_weights?: Record<string, number>
  sort_formula?: string
  score_version?: string
  energy_scenario?: string
  energy_prices?: Record<string, number>
  finance_reserve_wan?: number
  bev_filter?: string
}

type SortKey = 'recommend' | 'price' | 'year' | 'mileage' | 'config' | 'score'
type TabKey = 'ranked' | 'issues'

const app = document.querySelector<HTMLDivElement>('#app')!

let rankedListings: Listing[] = []
let issueListings: Listing[] = []
let meta: Meta | null = null
let originalIndex = new Map<string, number>()

const state = {
  tab: 'ranked' as TabKey,
  q: '',
  priceMin: '',
  priceMax: '',
  suv: 'all' as 'all' | 'yes' | 'no',
  official: false,
  mileageMax: '',
  sort: 'recommend' as SortKey,
}

function esc(s: unknown): string {
  return String(s ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
}

function fmtTime(iso?: string): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso
    return d.toLocaleString('zh-CN', { hour12: false, timeZone: 'Asia/Shanghai' }) + '（上海）'
  } catch {
    return iso
  }
}

function currentSource(): Listing[] {
  return state.tab === 'issues' ? issueListings : rankedListings
}

function hasOfficial(item: Listing): boolean {
  return (item.badges || []).some((b) => b.includes('直营') || b.includes('官方保'))
}

function statsOf(items: Listing[]) {
  if (!items.length) return { count: 0, avg: 0, min: 0, max: 0 }
  const prices = items.map((x) => Number(x.price)).filter((x) => Number.isFinite(x))
  if (!prices.length) return { count: items.length, avg: 0, min: 0, max: 0 }
  const sum = prices.reduce((a, b) => a + b, 0)
  return {
    count: items.length,
    avg: Math.round((sum / prices.length) * 100) / 100,
    min: Math.min(...prices),
    max: Math.max(...prices),
  }
}

function totalOf(item: Listing): number | null {
  const value = item.total_score ?? item.sort_scores?.total_score
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function isSuv(item: Listing): boolean {
  if (typeof item.sort_scores?.is_suv === 'boolean') return item.sort_scores.is_suv
  return String(item.specs?.body_type || item.detailed_config?.body_type || '').toLowerCase().includes('suv')
}

function filtered(): Listing[] {
  const q = state.q.trim().toLowerCase()
  const pMin = state.priceMin === '' ? null : Number(state.priceMin)
  const pMax = state.priceMax === '' ? null : Number(state.priceMax)
  const mMax = state.mileageMax === '' ? null : Number(state.mileageMax)
  const source = currentSource()

  let rows = source.filter((item) => {
    if (
      q &&
      !(
        item.title.toLowerCase().includes(q) ||
        (item.manufacturer || '').toLowerCase().includes(q) ||
        (item.brand || '').toLowerCase().includes(q)
      )
    ) return false
    if (pMin != null && !Number.isNaN(pMin) && item.price < pMin) return false
    if (pMax != null && !Number.isNaN(pMax) && item.price > pMax) return false
    if (mMax != null && !Number.isNaN(mMax) && (item.mileage_wan ?? 999) > mMax) return false
    if (state.suv === 'yes' && !isSuv(item)) return false
    if (state.suv === 'no' && isSuv(item)) return false
    if (state.official && !hasOfficial(item)) return false
    return true
  })

  rows = [...rows]
  const idx = (sku: string) => originalIndex.get(sku) ?? 999999
  switch (state.sort) {
    case 'price':
      rows.sort((a, b) => a.price - b.price || idx(a.sku) - idx(b.sku))
      break
    case 'year':
      rows.sort((a, b) => (b.plate_year || b.model_year || 0) - (a.plate_year || a.model_year || 0) || idx(a.sku) - idx(b.sku))
      break
    case 'mileage':
      rows.sort((a, b) => (a.mileage_wan ?? 999) - (b.mileage_wan ?? 999) || idx(a.sku) - idx(b.sku))
      break
    case 'config':
      rows.sort((a, b) => Number(b.sort_scores?.config_proxy ?? -1) - Number(a.sort_scores?.config_proxy ?? -1) || idx(a.sku) - idx(b.sku))
      break
    case 'score':
    case 'recommend':
    default:
      if (state.tab === 'issues') {
        rows.sort((a, b) => idx(a.sku) - idx(b.sku))
      } else {
        rows.sort((a, b) => Number(totalOf(b) ?? -999) - Number(totalOf(a) ?? -999) || idx(a.sku) - idx(b.sku))
      }
  }
  return rows
}

function specsHtml(item: Listing): string {
  const specs = item.specs || item.detailed_config
  if (state.tab === 'issues' && (!specs?.specs_found || specs?.match_level === 'unverified_config')) {
    return `<div class="specs muted issue-spec"><strong>详细配置</strong>：详细配置数据不足</div>`
  }
  if (specs?.specs_found) {
    const bits = [
      specs.powertrain_type || '',
      specs.engine || '',
      specs.wheelbase_mm ? `轴距${specs.wheelbase_mm}` : '',
      specs.seats ? `${specs.seats}座` : '',
      specs.body_type || '',
      specs.verified ? '精确参配' : '',
    ].filter(Boolean)
    const feat = specs.features || {}
    const hi: string[] = []
    if (feat.aeb) hi.push('AEB')
    if (feat.cruise) hi.push(String(feat.cruise).slice(0, 16))
    if (feat.camera_360) hi.push('360影像')
    if (feat.seat_ventilation) hi.push('座椅通风')
    return `<div class="specs"><strong>公开参配</strong>：${esc(bits.join(' · '))}${hi.length ? `<div class="spec-hi">${esc(hi.slice(0, 5).join(' · '))}</div>` : ''}</div>`
  }
  return `<div class="specs muted issue-spec"><strong>详细配置</strong>：详细配置数据不足</div>`
}

function reviewHtml(item: Listing): string {
  const or = item.owner_reviews
  if (!or) return ''
  const links = (or.sources || []).slice(0, 3).map((s) => `<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)}</a>`).join(' · ')
  const pros = or.pros || []
  const cons = or.cons || or.drawbacks || []
  const parts = [
    or.summary ? `<div class="review-summary"><strong>车主口碑</strong>：${esc(or.summary)}</div>` : '',
    pros.length ? `<div class="pros"><strong>优点</strong>：${esc(pros.slice(0, 4).join('；'))}</div>` : '',
    cons.length ? `<div class="cons"><strong>缺点</strong><ul>${cons.slice(0, 6).map((c) => `<li>${esc(c)}</li>`).join('')}</ul></div>` : '',
    links ? `<div class="sources">${links}</div>` : '',
  ].filter(Boolean)
  return parts.length ? `<div class="review">${parts.join('')}</div>` : ''
}

function issuePanel(item: Listing): string {
  const issues = item.data_issues || []
  if (!issues.length && state.tab !== 'issues') return ''
  const rows = issues.length
    ? issues.map((x) => `<li><strong>${esc(x.message)}</strong>${x.field ? `<span>${esc(x.field)}</span>` : ''}</li>`).join('')
    : '<li><strong>数据不足，不参与评分</strong></li>'
  return `<div class="data-issue-panel"><div class="issue-title">数据异常 / 待补全</div><ul>${rows}</ul><div class="issue-foot">该车辆不会进入综合分、配置分及推荐排名。</div></div>`
}

function cardHtml(item: Listing): string {
  const issueMode = state.tab === 'issues' || item.score_eligible === false
  const rank = item.rank ?? 0
  const badges = item.badges || []
  const tags = (item.tags || []).slice(0, 4)
  const img = `/images/${item.sku}.jpg`
  const total = totalOf(item)
  const yearLine = item.year || [item.plate_year ? `${item.plate_year}年` : '', item.mileage_wan != null ? `${item.mileage_wan}万公里` : '', item.city || ''].filter(Boolean).join(' / ')
  const manu = item.manufacturer || '未知厂商'
  const brand = item.brand && item.brand !== item.manufacturer ? ` · ${item.brand}` : ''
  const score = item.sort_scores
  const scoreText = !issueMode && total != null
    ? `总分 ${total.toFixed(1)} · 价${Number(score?.price_score ?? 0).toFixed(0)} · 配${Number(score?.config_score ?? score?.config_norm ?? 0).toFixed(0)} · 成本${Number(score?.operating_cost_score ?? score?.fuel_norm ?? 0).toFixed(0)} · 空${Number(score?.space_score ?? score?.space_norm ?? 0).toFixed(0)}`
    : '未参与评分'
  const badgeHtml = [
    ...badges.slice(0, 3).map((b) => `<span class="pill official">${esc(b)}</span>`),
    isSuv(item) ? `<span class="pill suv">SUV</span>` : '',
    `<span class="pill manu">${esc(manu)}</span>`,
  ].join('')

  return `
  <article class="card ${issueMode ? 'issue-card' : ''}">
    <div class="cover">
      <img src="${img}" alt="${esc(item.title)}" loading="lazy" onerror="this.style.display='none'; this.nextElementSibling.style.display='grid';" />
      <div class="placeholder" style="display:none">暂无封面</div>
      <div class="badges">${badgeHtml}</div>
      ${issueMode
        ? `<div class="score-badge issue-badge">未评分</div>`
        : `<div class="score-badge">#${rank}<span class="score-badge-pts">${total?.toFixed(1) ?? '—'}</span></div>`}
    </div>
    <div class="body">
      <div class="manu-line">${esc(manu)}${esc(brand)}</div>
      <div class="title" title="${esc(item.title)}">${esc(item.title)}</div>
      <div class="meta-row">${esc(yearLine)}</div>
      <div class="price-row">
        <div class="price">${Number(item.price).toFixed(2)}<small>万</small></div>
        <div class="price-type">${esc(item.price_type || '标价')}${item.needs_cash_quote && item.effective_price_wan != null ? ` · 估${Number(item.effective_price_wan).toFixed(2)}万` : ''}</div>
      </div>
      <div class="tags">${tags.map((t) => `<span class="tag">${esc(t)}</span>`).join('')}</div>
      ${specsHtml(item)}
      ${issueMode ? issuePanel(item) : (item.evaluation ? `<div class="eval"><strong>评价</strong>：${esc(item.evaluation)}</div>` : '')}
      ${reviewHtml(item)}
      ${!issueMode && (item.needs_cash_quote || item.condition_gate === 'MANUAL_REVIEW' || (item.score_warnings || []).length)
        ? `<div class="warn">${item.condition_gate === 'MANUAL_REVIEW' ? '⚠️ 待人工确认。' : ''}${item.needs_cash_quote ? `分期展示价需询现金价；排序估算 ${Number(item.effective_price_wan ?? item.price).toFixed(2)} 万。` : ''}${esc((item.score_warnings || []).slice(0, 2).join('；'))}</div>`
        : ''}
      <div class="footer-row">
        <span class="score">${issueMode ? '详细数据补齐前不参与评分' : `全场得分排名 #${rank} · ${esc(scoreText)}`}</span>
        <span class="footer-actions">
          <a class="btn-link" href="?sku=${encodeURIComponent(item.sku)}">查看完整配置</a>
          <a class="btn-link" href="${esc(item.detail_url)}" target="_blank" rel="noopener noreferrer">详情</a>
        </span>
      </div>
    </div>
  </article>`
}

function renderShell() {
  const source = currentSource()
  const allStats = statsOf(source)
  const shop = meta?.shop_name || '懂车帝汽车商城·武汉店'
  const filters = [
    meta?.price_filter || meta?.filters?.price || '≤6万',
    meta?.mileage_filter || meta?.filters?.mileage || '≤10万公里',
    meta?.age_filter || meta?.filters?.vehicle_age || '≤10年',
    meta?.bev_filter || (meta?.filters as any)?.exclude_short_range_bev_desc || '排除短续航纯电',
  ].join(' · ')
  const w = meta?.sort_weights
  const ver = meta?.score_version || 'v2'
  const weightText = w
    ? `算法 ${ver} · 仅详细配置核验通过车辆评分 · 权重：价格${Math.round((w.price || 0) * 100)}% + 配置${Math.round((w.config || 0) * 100)}% + 使用成本${Math.round((w.operating_cost || 0) * 100)}% + 空间${Math.round((w.space || 0) * 100)}% + 其余${Math.round(((w.age || 0) + (w.mileage || 0) + (w.body_preference || 0) + (w.data_quality || 0)) * 100)}%`
    : `算法 ${ver}`

  app.innerHTML = `
    <header class="header">
      <div class="brand"><h1>武汉店二手车看板</h1><span class="badge-note">非官方 · 本地抓取数据看板</span></div>
      <div class="sub">${esc(shop)}（shop_id ${esc(meta?.shop_id || '118608')}） · 硬筛：${esc(filters)}</div>
      <div class="sort-rule">${esc(weightText)}</div>
      <div class="data-links">
        <span>数据：</span>
        <a href="/data/listings-ranked.json" target="_blank" rel="noopener noreferrer">参与评分 JSON</a>
        <a href="/data/data-issues.json" target="_blank" rel="noopener noreferrer">数据异常 JSON</a>
        <a href="/data/meta.json" target="_blank" rel="noopener noreferrer">meta</a>
      </div>
    </header>

    <nav class="data-tabs" aria-label="车源数据状态">
      <button class="data-tab ${state.tab === 'ranked' ? 'active' : ''}" data-tab="ranked">
        参与评分 <span>${rankedListings.length}</span>
      </button>
      <button class="data-tab ${state.tab === 'issues' ? 'active issue' : ''}" data-tab="issues">
        数据异常 / 待补全 <span>${issueListings.length}</span>
      </button>
    </nav>
    ${state.tab === 'issues' ? `<div class="issue-notice"><strong>这里的车辆不参与任何排名。</strong> 详细配置不足会直接显示“详细配置数据不足”；今后价格、里程、车龄、空间、能耗等关键数据异常也统一进入这里。</div>` : ''}

    <section class="stats" id="stats">
      <div class="stat"><div class="label">${state.tab === 'ranked' ? '评分车源' : '异常车源'}</div><div class="value" id="stat-count">${allStats.count}</div></div>
      <div class="stat"><div class="label">均价</div><div class="value price" id="stat-avg">${allStats.count ? allStats.avg.toFixed(2) + '万' : '—'}</div></div>
      <div class="stat"><div class="label">最低价</div><div class="value price" id="stat-min">${allStats.count ? allStats.min.toFixed(2) + '万' : '—'}</div></div>
      <div class="stat"><div class="label">最高价</div><div class="value price" id="stat-max">${allStats.count ? allStats.max.toFixed(2) + '万' : '—'}</div></div>
      <div class="stat"><div class="label">抓取时间</div><div class="value small-value">${esc(fmtTime(meta?.captured_at))}</div></div>
      <div class="stat"><div class="label">排序时间</div><div class="value small-value">${esc(fmtTime(meta?.ranked_at))}</div></div>
    </section>

    <section class="controls">
      <div class="field"><label for="q">关键词（标题/厂商）</label><input id="q" type="search" placeholder="如：哈弗 / 比亚迪 / 秦PLUS" value="${esc(state.q)}" /></div>
      <div class="field"><label for="priceMin">最低价（万）</label><input id="priceMin" type="number" min="0" step="0.1" placeholder="不限" value="${esc(state.priceMin)}" /></div>
      <div class="field"><label for="priceMax">最高价（万）</label><input id="priceMax" type="number" min="0" step="0.1" placeholder="不限" value="${esc(state.priceMax)}" /></div>
      <div class="field"><label for="mileageMax">里程上限（万公里）</label><input id="mileageMax" type="number" min="0" step="0.1" placeholder="不限" value="${esc(state.mileageMax)}" /></div>
      <div class="field"><label for="suv">车型</label><select id="suv"><option value="all" ${state.suv === 'all' ? 'selected' : ''}>全部</option><option value="yes" ${state.suv === 'yes' ? 'selected' : ''}>仅 SUV</option><option value="no" ${state.suv === 'no' ? 'selected' : ''}>非 SUV</option></select></div>
      <div class="field"><label for="sort">排序</label><select id="sort">
        <option value="recommend" ${state.sort === 'recommend' ? 'selected' : ''}>${state.tab === 'ranked' ? '综合总分' : '异常优先'}</option>
        ${state.tab === 'ranked' ? `<option value="score" ${state.sort === 'score' ? 'selected' : ''}>总分</option><option value="config" ${state.sort === 'config' ? 'selected' : ''}>更高配置分</option>` : ''}
        <option value="price" ${state.sort === 'price' ? 'selected' : ''}>更便宜</option>
        <option value="year" ${state.sort === 'year' ? 'selected' : ''}>更新上牌</option>
        <option value="mileage" ${state.sort === 'mileage' ? 'selected' : ''}>更低里程</option>
      </select></div>
      <div class="field checkbox"><input id="official" type="checkbox" ${state.official ? 'checked' : ''} /><label for="official">仅直营/官方保</label></div>
    </section>

    <div class="toolbar"><div id="result-count">显示 ${allStats.count} / ${source.length} 辆</div><div>${state.tab === 'ranked' ? '仅数据完整车辆参与综合评分' : '待补全车辆不会影响榜单排名'}</div></div>
    <section class="grid" id="grid"></section>
  `
  bindControls()
  renderList()
}

function bindControls() {
  document.querySelectorAll<HTMLButtonElement>('.data-tab').forEach((button) => {
    button.addEventListener('click', () => {
      const next = button.dataset.tab as TabKey
      if (!next || next === state.tab) return
      state.tab = next
      state.sort = 'recommend'
      renderShell()
    })
  })

  const bind = (id: string, key: keyof typeof state, as: 'string' | 'check' = 'string') => {
    const el = document.getElementById(id) as HTMLInputElement | HTMLSelectElement | null
    if (!el) return
    const handler = () => {
      if (as === 'check') (state as any)[key] = (el as HTMLInputElement).checked
      else (state as any)[key] = el.value
      renderList()
    }
    el.addEventListener('input', handler)
    el.addEventListener('change', handler)
  }
  bind('q', 'q')
  bind('priceMin', 'priceMin')
  bind('priceMax', 'priceMax')
  bind('mileageMax', 'mileageMax')
  bind('suv', 'suv')
  bind('sort', 'sort')
  bind('official', 'official', 'check')
}

function renderList() {
  const rows = filtered()
  const source = currentSource()
  const grid = document.getElementById('grid')
  const countEl = document.getElementById('result-count')
  const s = statsOf(rows)
  if (countEl) countEl.textContent = `显示 ${rows.length} / ${source.length} 辆`
  const set = (id: string, text: string) => { const el = document.getElementById(id); if (el) el.textContent = text }
  set('stat-count', String(s.count))
  set('stat-avg', s.count ? `${s.avg.toFixed(2)}万` : '—')
  set('stat-min', s.count ? `${s.min.toFixed(2)}万` : '—')
  set('stat-max', s.count ? `${s.max.toFixed(2)}万` : '—')
  if (!grid) return
  if (!rows.length) {
    grid.innerHTML = `<div class="empty">${state.tab === 'issues' ? '当前没有符合筛选条件的数据异常车源。' : '没有符合条件的车源，试试放宽筛选。'}</div>`
    return
  }
  grid.innerHTML = rows.map(cardHtml).join('')
}

async function boot() {
  if (isConfigRoute()) {
    await renderConfigPage(app)
    return
  }
  app.innerHTML = `<div class="loading">正在加载车源数据…</div>`
  try {
    const [listRes, issueRes, metaRes] = await Promise.all([
      fetch('/data/listings-ranked.json'),
      fetch('/data/data-issues.json'),
      fetch('/data/meta.json'),
    ])
    if (!listRes.ok) throw new Error(`listings-ranked.json HTTP ${listRes.status}`)
    if (!issueRes.ok) throw new Error(`data-issues.json HTTP ${issueRes.status}`)
    if (!metaRes.ok) throw new Error(`meta.json HTTP ${metaRes.status}`)
    rankedListings = await listRes.json()
    issueListings = await issueRes.json()
    meta = await metaRes.json()
    originalIndex = new Map([...rankedListings, ...issueListings].map((x, i) => [x.sku, i]))
    renderShell()
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    app.innerHTML = `<div class="error">加载失败：${esc(msg)}</div>`
  }
}

boot()
