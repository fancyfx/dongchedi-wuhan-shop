import './style.css'

type SortScores = {
  config_proxy: number
  space_proxy: number
  fuel_proxy: number
  is_suv: boolean
  price: number
  config_norm?: number
  space_norm?: number
  fuel_norm?: number
  price_score?: number
  suv_score?: number
  total_score?: number
  note?: string
}

type OwnerReviews = {
  summary?: string
  sources?: { title: string; url: string }[]
  found?: boolean
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
  total_score?: number
  evaluation?: string
  rank?: number
  sort_scores?: SortScores
  owner_reviews?: OwnerReviews
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
  notes?: string
  sort_preference?: string | string[]
  sort_weights?: Record<string, number>
  sort_formula?: string
}

type SortKey = 'recommend' | 'price' | 'year' | 'mileage' | 'config' | 'score'

const app = document.querySelector<HTMLDivElement>('#app')!

let listings: Listing[] = []
let meta: Meta | null = null
let originalIndex = new Map<string, number>()

const state = {
  q: '',
  priceMin: '',
  priceMax: '',
  suv: 'all' as 'all' | 'yes' | 'no',
  official: false,
  mileageMax: '',
  sort: 'recommend' as SortKey,
}

function esc(s: string): string {
  return s
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

function hasOfficial(item: Listing): boolean {
  const badges = item.badges || []
  return badges.some((b) => b.includes('直营') || b.includes('官方保'))
}

function statsOf(items: Listing[]) {
  if (!items.length) return { count: 0, avg: 0, min: 0, max: 0 }
  const prices = items.map((x) => x.price)
  const sum = prices.reduce((a, b) => a + b, 0)
  return {
    count: items.length,
    avg: Math.round((sum / prices.length) * 100) / 100,
    min: Math.min(...prices),
    max: Math.max(...prices),
  }
}

function totalOf(item: Listing): number {
  return item.total_score ?? item.sort_scores?.total_score ?? 0
}

function filtered(): Listing[] {
  const q = state.q.trim().toLowerCase()
  const pMin = state.priceMin === '' ? null : Number(state.priceMin)
  const pMax = state.priceMax === '' ? null : Number(state.priceMax)
  const mMax = state.mileageMax === '' ? null : Number(state.mileageMax)

  let rows = listings.filter((item) => {
    if (
      q &&
      !(
        item.title.toLowerCase().includes(q) ||
        (item.manufacturer || '').toLowerCase().includes(q) ||
        (item.brand || '').toLowerCase().includes(q)
      )
    )
      return false
    if (pMin != null && !Number.isNaN(pMin) && item.price < pMin) return false
    if (pMax != null && !Number.isNaN(pMax) && item.price > pMax) return false
    if (mMax != null && !Number.isNaN(mMax) && (item.mileage_wan ?? 999) > mMax) return false
    const isSuv = !!item.sort_scores?.is_suv
    if (state.suv === 'yes' && !isSuv) return false
    if (state.suv === 'no' && isSuv) return false
    if (state.official && !hasOfficial(item)) return false
    return true
  })

  rows = [...rows]
  switch (state.sort) {
    case 'price':
      rows.sort((a, b) => a.price - b.price || originalIndex.get(a.sku)! - originalIndex.get(b.sku)!)
      break
    case 'year':
      rows.sort(
        (a, b) =>
          (b.plate_year || b.model_year || 0) - (a.plate_year || a.model_year || 0) ||
          originalIndex.get(a.sku)! - originalIndex.get(b.sku)!,
      )
      break
    case 'mileage':
      rows.sort(
        (a, b) =>
          (a.mileage_wan ?? 999) - (b.mileage_wan ?? 999) ||
          originalIndex.get(a.sku)! - originalIndex.get(b.sku)!,
      )
      break
    case 'config':
      rows.sort(
        (a, b) =>
          (b.sort_scores?.config_proxy ?? 0) - (a.sort_scores?.config_proxy ?? 0) ||
          originalIndex.get(a.sku)! - originalIndex.get(b.sku)!,
      )
      break
    case 'score':
    case 'recommend':
    default:
      rows.sort(
        (a, b) =>
          totalOf(b) - totalOf(a) ||
          (b.sort_scores?.config_norm ?? 0) - (a.sort_scores?.config_norm ?? 0) ||
          originalIndex.get(a.sku)! - originalIndex.get(b.sku)!,
      )
  }
  return rows
}

function cardHtml(item: Listing, rank: number): string {
  const badges = item.badges || []
  const tags = (item.tags || []).slice(0, 4)
  const isSuv = !!item.sort_scores?.is_suv
  const img = `/images/${item.sku}.jpg`
  const yearLine =
    item.year ||
    [item.plate_year ? `${item.plate_year}年` : '', item.mileage_wan != null ? `${item.mileage_wan}万公里` : '', item.city || '']
      .filter(Boolean)
      .join(' / ')
  const score = item.sort_scores
  const total = totalOf(item)
  const scoreText = score
    ? `总分 ${total.toFixed(1)} · 配${(score.config_norm ?? score.config_proxy).toFixed(0)} · 空${(score.space_norm ?? score.space_proxy).toFixed(0)} · 油${(score.fuel_norm ?? score.fuel_proxy).toFixed(0)}`
    : `总分 ${total.toFixed(1)}`

  const manu = item.manufacturer || '未知厂商'
  const brand = item.brand && item.brand !== item.manufacturer ? ` · ${item.brand}` : ''

  const badgeHtml = [
    ...badges.slice(0, 3).map((b) => `<span class="pill official">${esc(b)}</span>`),
    isSuv ? `<span class="pill suv">SUV</span>` : '',
    `<span class="pill manu">${esc(manu)}</span>`,
  ].join('')

  const evalHtml = item.evaluation
    ? `<div class="eval"><strong>评价</strong>：${esc(item.evaluation)}</div>`
    : ''

  const or = item.owner_reviews
  let reviewHtml = ''
  if (or?.found && or.summary) {
    const links = (or.sources || [])
      .slice(0, 3)
      .map((s) => `<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)}</a>`)
      .join(' · ')
    reviewHtml = `<div class="review"><strong>车主口碑</strong>：${esc(or.summary)}${links ? `<div class="sources">${links}</div>` : ''}</div>`
  } else if (or && or.found === false && or.summary && !or.summary.includes('短名单外')) {
    reviewHtml = `<div class="review muted">${esc(or.summary)}</div>`
  }

  return `
  <article class="card">
    <div class="cover">
      <img src="${img}" alt="${esc(item.title)}" loading="lazy"
        onerror="this.style.display='none'; this.nextElementSibling.style.display='grid';" />
      <div class="placeholder" style="display:none">暂无封面</div>
      <div class="badges">${badgeHtml}</div>
      <div class="score-badge">${total.toFixed(1)}</div>
    </div>
    <div class="body">
      <div class="manu-line">${esc(manu)}${esc(brand)}</div>
      <div class="title" title="${esc(item.title)}">${esc(item.title)}</div>
      <div class="meta-row">${esc(yearLine)}</div>
      <div class="price-row">
        <div class="price">${item.price.toFixed(2)}<small>万</small></div>
        <div class="price-type">${esc(item.price_type || '标价')}</div>
      </div>
      <div class="tags">${tags.map((t) => `<span class="tag">${esc(t)}</span>`).join('')}</div>
      ${evalHtml}
      ${reviewHtml}
      <div class="footer-row">
        <span class="score">#${rank} ${esc(scoreText)}</span>
        <a class="btn-link" href="${esc(item.detail_url)}" target="_blank" rel="noopener noreferrer">详情</a>
      </div>
    </div>
  </article>`
}

function renderShell() {
  const allStats = statsOf(listings)
  const shop = meta?.shop_name || '懂车帝汽车商城·武汉店'
  const filters = [
    meta?.price_filter || meta?.filters?.price || '≤6万',
    meta?.mileage_filter || meta?.filters?.mileage || '≤10万公里',
    meta?.age_filter || meta?.filters?.vehicle_age || '≤10年',
  ].join(' · ')
  const w = meta?.sort_weights
  const weightText = w
    ? `综合总分：配置${Math.round(w.config * 100)}% + 空间${Math.round(w.space * 100)}% + 油耗${Math.round(w.fuel * 100)}% + 价格${Math.round(w.price * 100)}% + SUV${Math.round(w.suv * 100)}%`
    : '综合总分：配置35% + 空间25% + 油耗20% + 价格15% + SUV5%'

  app.innerHTML = `
    <header class="header">
      <div class="brand">
        <h1>武汉店二手车看板</h1>
        <span class="badge-note">非官方 · 本地抓取数据看板</span>
      </div>
      <div class="sub">${esc(shop)}（shop_id ${esc(meta?.shop_id || '118608')}） · 硬筛：${esc(filters)}</div>
      <div class="sort-rule">${esc(weightText)}</div>
    </header>

    <section class="stats" id="stats">
      <div class="stat"><div class="label">车源数</div><div class="value" id="stat-count">${allStats.count}</div></div>
      <div class="stat"><div class="label">均价</div><div class="value price" id="stat-avg">${allStats.avg.toFixed(2)}万</div></div>
      <div class="stat"><div class="label">最低价</div><div class="value price" id="stat-min">${allStats.min.toFixed(2)}万</div></div>
      <div class="stat"><div class="label">最高价</div><div class="value price" id="stat-max">${allStats.max.toFixed(2)}万</div></div>
      <div class="stat"><div class="label">抓取时间</div><div class="value" style="font-size:13px">${esc(fmtTime(meta?.captured_at))}</div></div>
      <div class="stat"><div class="label">排序时间</div><div class="value" style="font-size:13px">${esc(fmtTime(meta?.ranked_at))}</div></div>
    </section>

    <section class="controls">
      <div class="field">
        <label for="q">关键词（标题/厂商）</label>
        <input id="q" type="search" placeholder="如：哈弗 / 比亚迪 / 秦PLUS" value="${esc(state.q)}" />
      </div>
      <div class="field">
        <label for="priceMin">最低价（万）</label>
        <input id="priceMin" type="number" min="0" step="0.1" placeholder="不限" value="${esc(state.priceMin)}" />
      </div>
      <div class="field">
        <label for="priceMax">最高价（万）</label>
        <input id="priceMax" type="number" min="0" step="0.1" placeholder="不限" value="${esc(state.priceMax)}" />
      </div>
      <div class="field">
        <label for="mileageMax">里程上限（万公里）</label>
        <input id="mileageMax" type="number" min="0" step="0.1" placeholder="不限" value="${esc(state.mileageMax)}" />
      </div>
      <div class="field">
        <label for="suv">车型</label>
        <select id="suv">
          <option value="all" ${state.suv === 'all' ? 'selected' : ''}>全部</option>
          <option value="yes" ${state.suv === 'yes' ? 'selected' : ''}>仅 SUV</option>
          <option value="no" ${state.suv === 'no' ? 'selected' : ''}>非 SUV</option>
        </select>
      </div>
      <div class="field">
        <label for="sort">排序</label>
        <select id="sort">
          <option value="recommend" ${state.sort === 'recommend' ? 'selected' : ''}>综合总分</option>
          <option value="score" ${state.sort === 'score' ? 'selected' : ''}>总分（显式）</option>
          <option value="price" ${state.sort === 'price' ? 'selected' : ''}>更便宜</option>
          <option value="year" ${state.sort === 'year' ? 'selected' : ''}>更新上牌</option>
          <option value="mileage" ${state.sort === 'mileage' ? 'selected' : ''}>更低里程</option>
          <option value="config" ${state.sort === 'config' ? 'selected' : ''}>更高配置分</option>
        </select>
      </div>
      <div class="field checkbox">
        <input id="official" type="checkbox" ${state.official ? 'checked' : ''} />
        <label for="official">仅直营/官方保</label>
      </div>
    </section>

    <div class="toolbar">
      <div id="result-count">显示 ${allStats.count} / ${listings.length} 辆</div>
      <div>封面 images/{sku}.jpg · 口碑来自公开网页搜索 · 详情跳转懂车帝</div>
    </div>
    <section class="grid" id="grid"></section>
  `

  bindControls()
  renderList()
}

function bindControls() {
  const bind = (id: string, key: keyof typeof state, as: 'string' | 'check' = 'string') => {
    const el = document.getElementById(id) as HTMLInputElement | HTMLSelectElement | null
    if (!el) return
    const handler = () => {
      if (as === 'check') {
        ;(state as any)[key] = (el as HTMLInputElement).checked
      } else {
        ;(state as any)[key] = el.value
      }
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
  const grid = document.getElementById('grid')
  const countEl = document.getElementById('result-count')
  const s = statsOf(rows)
  if (countEl) countEl.textContent = `显示 ${rows.length} / ${listings.length} 辆`

  const set = (id: string, text: string) => {
    const el = document.getElementById(id)
    if (el) el.textContent = text
  }
  set('stat-count', String(s.count))
  set('stat-avg', `${s.avg.toFixed(2)}万`)
  set('stat-min', s.count ? `${s.min.toFixed(2)}万` : '—')
  set('stat-max', s.count ? `${s.max.toFixed(2)}万` : '—')

  if (!grid) return
  if (!rows.length) {
    grid.innerHTML = `<div class="empty">没有符合条件的车源，试试放宽筛选。</div>`
    return
  }
  grid.innerHTML = rows.map((item, i) => cardHtml(item, i + 1)).join('')
}

async function boot() {
  app.innerHTML = `<div class="loading">正在加载车源数据…</div>`
  try {
    const [listRes, metaRes] = await Promise.all([
      fetch('/data/listings-ranked.json'),
      fetch('/data/meta.json'),
    ])
    if (!listRes.ok) throw new Error(`listings-ranked.json HTTP ${listRes.status}`)
    if (!metaRes.ok) throw new Error(`meta.json HTTP ${metaRes.status}`)
    listings = await listRes.json()
    meta = await metaRes.json()
    originalIndex = new Map(listings.map((x, i) => [x.sku, i]))
    renderShell()
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    app.innerHTML = `<div class="error">加载失败：${esc(msg)}</div>`
  }
}

boot()
