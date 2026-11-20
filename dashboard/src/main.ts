import './style.css'
import { isConfigRoute, renderConfigPage } from './config-page'
import {
  coverImgHtml,
  esc,
  gearboxClass,
  renderCompareDrawerBody,
  renderDetailDrawerBody,
  renderMethodologyModalBody,
  scoreBarsHtml,
} from './drawer'
import {
  blankToday,
  fixtureBannerHtml,
  missingToday,
  normalizeToday,
  reconcileToday,
  renderTodayPanel,
  todayModeFromSearch,
  type TodayFilter,
  type TodayMode,
  type TodayUpdates,
} from './today'
import type { Listing, Meta, PresetKey, SortKey } from './types'

const app = document.querySelector<HTMLDivElement>('#app')!

let rankedListings: Listing[] = []
let meta: Meta | null = null
let todayData: TodayUpdates = missingToday('尚未加载')
let highlightSkus = new Set<string>()

const state = {
  preset: 'all' as PresetKey,
  sort: 'recommend' as SortKey,
  q: '',
  priceMax: '',
  activeSku: null as string | null,
  drawerMode: null as null | 'detail' | 'today' | 'compare' | 'methodology',
  todayFilter: 'all' as TodayFilter,
  compareSkus: [] as string[],
}

function fmtTime(iso?: string): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso
    return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Shanghai' })
  } catch {
    return iso
  }
}

function isSuv(item: Listing): boolean {
  if (typeof item.sort_scores?.is_suv === 'boolean') return item.sort_scores.is_suv
  return String(item.specs?.body_type || item.detailed_config?.body_type || '').toLowerCase().includes('suv')
}

function hasL2(item: Listing): boolean {
  const f = (item.specs?.features || {}) as Record<string, unknown>
  return Boolean(f.acc && f.aeb && (f.lka || f.lane_centering))
}

function matchesPreset(item: Listing, preset: PresetKey): boolean {
  const p = item.v3_profile
  const bt = String(item.specs?.body_type || '')
  switch (preset) {
    case 'at':
      return p?.gearbox_tier === 'AT'
    case 'under5':
      return Number(item.price) <= 5.0
    case 'lowmile':
      return (item.mileage_wan ?? 99) <= 4.0
    case 'suv':
      return isSuv(item) || String(p?.drive_short || '').includes('四驱')
    case 'sedan_b':
      return bt.includes('中型车')
    case 'l2':
      return hasL2(item)
    default:
      return true
  }
}

function filteredListings(): Listing[] {
  const q = state.q.trim().toLowerCase()
  const pMax = state.priceMax === '' ? null : Number(state.priceMax)
  let rows = rankedListings.filter((item) => {
    if (!matchesPreset(item, state.preset)) return false
    if (pMax != null && !Number.isNaN(pMax) && Number(item.price) > pMax) return false
    if (q) {
      const hay = [
        item.sku,
        item.title,
        item.brand || '',
        item.manufacturer || '',
        item.v3_profile?.gearbox_label || '',
        item.v3_profile?.archetype_badge || '',
      ]
        .join(' ')
        .toLowerCase()
      if (!hay.includes(q)) return false
    }
    return true
  })

  rows = [...rows]
  switch (state.sort) {
    case 'price':
      rows.sort((a, b) => a.price - b.price || (a.rank ?? 99) - (b.rank ?? 99))
      break
    case 'discount':
      rows.sort(
        (a, b) =>
          (a.v3_profile?.discount_fold ?? 99) - (b.v3_profile?.discount_fold ?? 99) ||
          (a.rank ?? 99) - (b.rank ?? 99),
      )
      break
    case 'mileage':
      rows.sort((a, b) => (a.mileage_wan ?? 99) - (b.mileage_wan ?? 99) || (a.rank ?? 99) - (b.rank ?? 99))
      break
    case 'config':
      rows.sort(
        (a, b) =>
          (b.sort_scores?.config_score ?? 0) - (a.sort_scores?.config_score ?? 0) ||
          (a.rank ?? 99) - (b.rank ?? 99),
      )
      break
    case 'powertrain':
      rows.sort(
        (a, b) =>
          (b.sort_scores?.powertrain_score ?? 0) - (a.sort_scores?.powertrain_score ?? 0) ||
          (a.rank ?? 99) - (b.rank ?? 99),
      )
      break
    case 'recommend':
    default:
      rows.sort((a, b) => (a.rank ?? 999) - (b.rank ?? 999))
  }
  return rows
}

function isDefaultView(): boolean {
  return state.preset === 'all' && state.sort === 'recommend' && !state.q.trim() && !state.priceMax
}

function presetCounts(): Record<PresetKey, number> {
  return {
    all: rankedListings.length,
    at: rankedListings.filter((x) => matchesPreset(x, 'at')).length,
    under5: rankedListings.filter((x) => matchesPreset(x, 'under5')).length,
    lowmile: rankedListings.filter((x) => matchesPreset(x, 'lowmile')).length,
    suv: rankedListings.filter((x) => matchesPreset(x, 'suv')).length,
    sedan_b: rankedListings.filter((x) => matchesPreset(x, 'sedan_b')).length,
    l2: rankedListings.filter((x) => matchesPreset(x, 'l2')).length,
  }
}

function cardInnerHtml(item: Listing, hero = false): string {
  const p = item.v3_profile
  const rankNo = String(item.rank ?? '—').padStart(2, '0')
  const total = item.total_score ?? item.sort_scores?.total_score
  const compared = state.compareSkus.includes(item.sku)
  const isNewTop = highlightSkus.has(item.sku)
  const yearMile = [
    item.plate_year ? `${item.plate_year}年上牌` : '',
    item.mileage_wan != null ? `${item.mileage_wan.toFixed(2)}万公里` : '',
    item.specs?.body_type || '',
  ]
    .filter(Boolean)
    .join(' · ')
  const mechLine = [p?.engine_summary, p?.rear_suspension_short, p?.drive_short, p?.fuel_grade]
    .filter(Boolean)
    .join(' · ')
  const feats = (p?.feature_highlights || []).slice(0, hero ? 7 : 5)

  return `
    <article class="car-card ${hero ? 'hero-card' : ''} ${item.rank === 1 ? 'rank-one' : ''} ${compared ? 'is-compared' : ''}" data-sku="${esc(item.sku)}">
      <div class="card-media" data-open-detail="${esc(item.sku)}">
        ${coverImgHtml(item)}
        <div class="media-top">
          <span class="rank-chip ${item.rank && item.rank <= 3 ? `top-${item.rank}` : ''}">#${rankNo}</span>
          ${isNewTop ? `<span class="today-new-chip">今日新进前10</span>` : ''}
          ${p?.discount_fold ? `<span class="fold-chip">${p.discount_fold}折</span>` : ''}
        </div>
        <button type="button" class="cmp-toggle ${compared ? 'active' : ''}" data-cmp-toggle="${esc(item.sku)}" aria-pressed="${compared ? 'true' : 'false'}">
          ${compared ? '✓ 已选对比' : '+ 加入对比'}
        </button>
      </div>
      <div class="card-body">
        <div class="card-kicker">
          <span class="arch-tag">${esc(p?.archetype_badge || '严选车源')}</span>
          <span class="score-pill">严选分 <strong>${total != null ? total.toFixed(1) : '—'}</strong></span>
        </div>
        <h3 class="card-title" data-open-detail="${esc(item.sku)}" title="${esc(item.title)}">${esc(item.title)}</h3>
        <div class="card-sub">${esc(yearMile)}</div>

        <div class="price-block">
          <span class="cash-price">${Number(item.price).toFixed(2)}<small>万</small></span>
          ${p?.msrp_wan ? `<span class="msrp-info"><del>指导价 ${p.msrp_wan.toFixed(2)}万</del>${p.saved_wan ? ` · 省${p.saved_wan.toFixed(1)}万` : ''}</span>` : ''}
        </div>

        <div class="mech-bar">
          <span class="gb-badge ${gearboxClass(p?.gearbox_tier)}">${esc(p?.gearbox_label || '自动')}</span>
          <span class="mech-text">${esc(mechLine)}</span>
        </div>

        ${feats.length ? `<div class="feat-pills">${feats.map((f) => `<span>${esc(f)}</span>`).join('')}</div>` : ''}

        ${scoreBarsHtml(item, !hero)}

        <p class="advisor-line" title="${esc(p?.recommend_reason || item.evaluation || '')}">${esc(p?.recommend_reason || item.evaluation || '')}</p>

        <div class="card-actions">
          <button type="button" class="btn-report" data-open-detail="${esc(item.sku)}">买手深度报告</button>
          <a class="btn-ghost" href="?sku=${encodeURIComponent(item.sku)}">完整参配</a>
          <a class="btn-ghost" href="${esc(item.detail_url)}" target="_blank" rel="noopener noreferrer">原车页 ↗</a>
        </div>
      </div>
    </article>`
}

function mastheadHtml(): string {
  const onSale = meta?.on_sale_count ?? '—'
  const vetoed = meta?.vetoed_count ?? '—'
  const reserved = meta?.reserved_count ?? 0
  const rankedCnt = rankedListings.length
  const bd = meta?.veto_breakdown
  const vetoDetail = bd
    ? `新能源 ${bd.ev_phev ?? 0} / 三缸 ${bd.three_cyl ?? 0} / 干式双离合 ${bd.dry_dct ?? 0}`
    : '纯电插混 / 三缸 / 干式双离合'
  const todayBadge = todayData.has_snapshot
    ? (todayData.counts.added + todayData.counts.updated_price + todayData.counts.removed_sold)
    : 0

  return `
    <header class="masthead">
      <div class="masthead-top">
        <div class="brand-lockup">
          <div class="eyebrow">DONGCHEDI WUHAN · CURATED TOP 30</div>
          <h1>武汉店二手车看板 · Top 30 严选推荐</h1>
          <p class="lead">专为「平时不开、仅节假日偶尔开、高配低价且好维护」重写算法与展厅体验。已实时清理全部已售车，锁单车辆自动隐藏。</p>
        </div>
        <div class="masthead-actions">
          <button type="button" class="action-pill" id="btn-open-methodology">选车铁律 &amp; 权重说明</button>
          <button type="button" class="action-pill accent" id="btn-open-today">
            今日数据变动
            ${todayBadge > 0 ? `<span class="action-count">${todayBadge}</span>` : ''}
          </button>
        </div>
      </div>

      <div class="funnel-strip">
        <div class="funnel-step">
          <span>在售库存</span>
          <strong>${onSale} 台</strong>
        </div>
        <div class="funnel-arrow">→</div>
        <div class="funnel-step veto">
          <span>四大铁律剔除</span>
          <strong>-${vetoed} 台</strong>
          <small>${esc(vetoDetail)}</small>
        </div>
        ${reserved > 0 ? `
        <div class="funnel-arrow">→</div>
        <div class="funnel-step muted">
          <span>锁单隐藏</span>
          <strong>${reserved} 台</strong>
        </div>` : ''}
        <div class="funnel-arrow">→</div>
        <div class="funnel-step final">
          <span>严选入榜</span>
          <strong>Top ${rankedCnt}</strong>
          <small>更新于 ${esc(fmtTime(meta?.ranked_at))}</small>
        </div>
      </div>
    </header>`
}

function filterBarHtml(shown: Listing[]): string {
  const counts = presetCounts()
  const presets: [PresetKey, string][] = [
    ['all', `全部严选 (${counts.all})`],
    ['at', `成熟 AT (${counts.at})`],
    ['under5', `5万以内 (${counts.under5})`],
    ['lowmile', `4万km内 (${counts.lowmile})`],
    ['suv', `SUV / 四驱 (${counts.suv})`],
    ['sedan_b', `B级高速轿 (${counts.sedan_b})`],
    ['l2', `带L2智驾 (${counts.l2})`],
  ]
  const avgPrice = shown.length ? (shown.reduce((a, b) => a + b.price, 0) / shown.length).toFixed(2) : '—'
  const minPrice = shown.length ? Math.min(...shown.map((x) => x.price)).toFixed(2) : '—'

  return `
    <section class="filter-dock" aria-label="筛选与排序">
      <div class="preset-row">
        ${presets
          .map(
            ([k, label]) =>
              `<button type="button" class="preset-chip ${state.preset === k ? 'active' : ''}" data-preset="${k}">${esc(label)}</button>`,
          )
          .join('')}
      </div>
      <div class="filter-controls">
        <div class="ctrl-search">
          <input id="ctrl-q" type="search" placeholder="搜车型 / 品牌 / SKU（如 君威 / 爱信 / 探界者）" value="${esc(state.q)}" />
        </div>
        <div class="ctrl-item">
          <label for="ctrl-pmax">最高价(万)</label>
          <input id="ctrl-pmax" type="number" min="0" max="6" step="0.1" placeholder="6.0" value="${esc(state.priceMax)}" />
        </div>
        <div class="ctrl-item">
          <label for="ctrl-sort">排序</label>
          <select id="ctrl-sort">
            <option value="recommend" ${state.sort === 'recommend' ? 'selected' : ''}>V3 综合严选分</option>
            <option value="powertrain" ${state.sort === 'powertrain' ? 'selected' : ''}>三大件最稳</option>
            <option value="config" ${state.sort === 'config' ? 'selected' : ''}>配置最丰富</option>
            <option value="discount" ${state.sort === 'discount' ? 'selected' : ''}>折旧最狠 (几折)</option>
            <option value="price" ${state.sort === 'price' ? 'selected' : ''}>最低现金价</option>
            <option value="mileage" ${state.sort === 'mileage' ? 'selected' : ''}>最低表显里程</option>
          </select>
        </div>
        <div class="ctrl-summary">
          显示 <strong>${shown.length}</strong> / ${rankedListings.length} 台 · 均价 <b>${avgPrice}万</b> · 起价 <b>${minPrice}万</b>
        </div>
      </div>
    </section>`
}

function compareBarHtml(): string {
  if (!state.compareSkus.length) return ''
  const selected = state.compareSkus
    .map((sku) => rankedListings.find((x) => x.sku === sku))
    .filter((x): x is Listing => Boolean(x))
  return `
    <div class="compare-dock">
      <div class="cmp-dock-list">
        <span class="cmp-dock-label">已选对比 (${selected.length}/3)：</span>
        ${selected.map((x) => `<span class="cmp-chip">#${x.rank} ${esc(x.series || x.title.slice(0, 10))} <button type="button" data-cmp-remove="${esc(x.sku)}">×</button></span>`).join('')}
      </div>
      <div class="cmp-dock-actions">
        <button type="button" class="btn-clear-cmp" id="btn-clear-cmp">清空</button>
        <button type="button" class="btn-open-cmp" id="btn-open-cmp" ${selected.length < 2 ? 'disabled' : ''}>
          ${selected.length < 2 ? '再选 1 台开始对比' : `横向对比 (${selected.length} 台)`}
        </button>
      </div>
    </div>`
}

function drawerHostHtml(): string {
  if (!state.drawerMode) return ''
  let title = ''
  let body = ''
  let extraCls = ''

  if (state.drawerMode === 'detail' && state.activeSku) {
    const item = rankedListings.find((x) => x.sku === state.activeSku)
    if (item) {
      title = `买手深度报告 · 严选 #${String(item.rank ?? '—').padStart(2, '0')}`
      body = renderDetailDrawerBody(item)
      extraCls = 'wide'
    }
  } else if (state.drawerMode === 'compare') {
    const selected = state.compareSkus
      .map((sku) => rankedListings.find((x) => x.sku === sku))
      .filter((x): x is Listing => Boolean(x))
    title = `严选车源横向对比（${selected.length} 台）`
    body = renderCompareDrawerBody(selected)
    extraCls = 'extra-wide'
  } else if (state.drawerMode === 'methodology') {
    title = 'V3 选车铁律与评分方法论'
    body = renderMethodologyModalBody()
    extraCls = 'wide'
  } else if (state.drawerMode === 'today') {
    title = '每日库存与价格对账日志'
    body = renderTodayPanel({
      data: todayData,
      filter: state.todayFilter,
      fixtureMode: todayModeFromSearch(location.search) === 'fixture',
      onBoard: new Set(rankedListings.map((item) => item.sku)),
      highlightCardsHtml: '',
    })
    extraCls = 'wide'
  }

  if (!body) return ''
  return `
    <div class="drawer-backdrop" id="drawer-backdrop">
      <aside class="drawer-panel ${extraCls}" role="dialog" aria-modal="true" aria-label="${esc(title)}">
        <div class="drawer-top">
          <strong>${esc(title)}</strong>
          <button type="button" class="drawer-close" id="btn-close-drawer" aria-label="关闭">✕</button>
        </div>
        <div class="drawer-scroll">${body}</div>
      </aside>
    </div>`
}

function renderCatalogSection(): string {
  const shown = filteredListings()
  if (!shown.length) {
    return `<div class="empty-state">当前筛选条件下没有入围 Top 30 车源，点击“全部严选”即可重置。</div>`
  }
  const usePodium = isDefaultView() && shown.length >= 3
  if (!usePodium) {
    return `<section class="cards-grid">${shown.map((x) => cardInnerHtml(x, false)).join('')}</section>`
  }
  const top1 = shown[0]
  const top23 = shown.slice(1, 3)
  const rest = shown.slice(3)
  return `
    <section class="podium-section">
      <div class="sec-head">
        <h2>买手头号三甲 · Top 3</h2>
        <span>机械可靠性 × 节假日刚需高配 × 高折旧性价比综合最优</span>
      </div>
      <div class="podium-lead">${cardInnerHtml(top1, true)}</div>
      <div class="podium-runners">${top23.map((x) => cardInnerHtml(x, false)).join('')}</div>
    </section>
    ${rest.length ? `
    <section class="catalog-section">
      <div class="sec-head">
        <h2>严选阵容 · 第 4 – ${shown.length} 名</h2>
        <span>点击任意卡片查看针对性验车清单与完整车主口碑</span>
      </div>
      <div class="cards-grid">${rest.map((x) => cardInnerHtml(x, false)).join('')}</div>
    </section>` : ''}`
}

function renderApp() {
  const shown = filteredListings()
  app.innerHTML = `
    <div class="page-shell">
      ${mastheadHtml()}
      ${todayModeFromSearch(location.search) === 'fixture' ? fixtureBannerHtml() : ''}
      ${filterBarHtml(shown)}
      <main id="catalog-main">${renderCatalogSection()}</main>
      <footer class="site-footer">
        <span>数据口径：懂车帝汽车商城·武汉店（shop_id=118608）实车与现金价 + 汽车之家实测参配 + 车质网公开口碑</span>
        <span class="footer-links">
          <a href="/data/listings-ranked.json" target="_blank" rel="noopener noreferrer">Top 30 JSON</a>
          <a href="/data/meta.json" target="_blank" rel="noopener noreferrer">Meta</a>
          <a href="/data/today-updates.json" target="_blank" rel="noopener noreferrer">今日变动 JSON</a>
        </span>
      </footer>
    </div>
    ${compareBarHtml()}
    ${drawerHostHtml()}
  `
  bindEvents()
}

function toggleCompare(sku: string) {
  const idx = state.compareSkus.indexOf(sku)
  if (idx >= 0) {
    state.compareSkus.splice(idx, 1)
  } else {
    if (state.compareSkus.length >= 3) state.compareSkus.shift()
    state.compareSkus.push(sku)
  }
  renderApp()
}

function bindEvents() {
  document.querySelectorAll<HTMLButtonElement>('[data-preset]').forEach((btn) => {
    btn.addEventListener('click', () => {
      state.preset = (btn.dataset.preset as PresetKey) || 'all'
      renderApp()
    })
  })

  const qInput = document.getElementById('ctrl-q') as HTMLInputElement | null
  if (qInput) {
    qInput.addEventListener('input', () => {
      state.q = qInput.value
      const pos = qInput.selectionStart
      renderApp()
      const nextEl = document.getElementById('ctrl-q') as HTMLInputElement | null
      if (nextEl) {
        nextEl.focus()
        if (pos != null) nextEl.setSelectionRange(pos, pos)
      }
    })
  }

  const pMaxInput = document.getElementById('ctrl-pmax') as HTMLInputElement | null
  pMaxInput?.addEventListener('change', () => {
    state.priceMax = pMaxInput.value
    renderApp()
  })

  const sortSel = document.getElementById('ctrl-sort') as HTMLSelectElement | null
  sortSel?.addEventListener('change', () => {
    state.sort = (sortSel.value as SortKey) || 'recommend'
    renderApp()
  })

  document.querySelectorAll<HTMLElement>('[data-open-detail]').forEach((el) => {
    el.addEventListener('click', (e) => {
      if ((e.target as HTMLElement).closest('[data-cmp-toggle]')) return
      const sku = el.dataset.openDetail
      if (!sku) return
      state.activeSku = sku
      state.drawerMode = 'detail'
      renderApp()
    })
  })

  document.querySelectorAll<HTMLButtonElement>('[data-cmp-toggle]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation()
      const sku = btn.dataset.cmpToggle
      if (sku) toggleCompare(sku)
    })
  })

  document.querySelectorAll<HTMLButtonElement>('[data-cmp-remove]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const sku = btn.dataset.cmpRemove
      if (!sku) return
      state.compareSkus = state.compareSkus.filter((s) => s !== sku)
      if (state.drawerMode === 'compare' && state.compareSkus.length === 0) {
        state.drawerMode = null
      }
      renderApp()
    })
  })

  document.getElementById('btn-clear-cmp')?.addEventListener('click', () => {
    state.compareSkus = []
    renderApp()
  })

  document.getElementById('btn-open-cmp')?.addEventListener('click', () => {
    if (state.compareSkus.length >= 2) {
      state.drawerMode = 'compare'
      renderApp()
    }
  })

  document.getElementById('btn-open-methodology')?.addEventListener('click', () => {
    state.drawerMode = 'methodology'
    renderApp()
  })

  document.getElementById('btn-open-today')?.addEventListener('click', () => {
    state.drawerMode = 'today'
    renderApp()
  })

  document.getElementById('btn-close-drawer')?.addEventListener('click', () => {
    state.drawerMode = null
    renderApp()
  })

  document.getElementById('drawer-backdrop')?.addEventListener('click', (e) => {
    if ((e.target as HTMLElement).id === 'drawer-backdrop') {
      state.drawerMode = null
      renderApp()
    }
  })

  document.getElementById('today-use-fixture')?.addEventListener('click', () => {
    void setTodayMode('fixture')
  })
  document.getElementById('today-use-live')?.addEventListener('click', () => {
    void setTodayMode('live')
  })
  document.querySelectorAll<HTMLButtonElement>('[data-today-filter]').forEach((btn) => {
    btn.addEventListener('click', () => {
      state.todayFilter = (btn.dataset.todayFilter as TodayFilter) || 'all'
      renderApp()
    })
  })
  document.querySelectorAll<HTMLButtonElement>('[data-jump-sku]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const sku = btn.dataset.jumpSku || ''
      state.activeSku = sku
      state.drawerMode = 'detail'
      renderApp()
    })
  })
}

async function pullToday(): Promise<TodayUpdates> {
  const mode = todayModeFromSearch(location.search)
  if (mode === 'missing') return missingToday('未加载今日快照。')
  if (mode === 'blank') return blankToday()
  const path = mode === 'fixture' ? '/data/today-updates.fixture.json' : '/data/today-updates.json'
  try {
    const res = await fetch(path)
    if (!res.ok) return missingToday(`暂无今日更新数据（HTTP ${res.status}）`)
    return normalizeToday(await res.json())
  } catch (err) {
    return missingToday(`今日更新读取失败：${err instanceof Error ? err.message : String(err)}`)
  }
}

function applyToday(next: TodayUpdates) {
  todayData = reconcileToday(next, rankedListings, [])
  highlightSkus = new Set(todayData.highlights.map((item) => item.sku))
}

async function setTodayMode(mode: TodayMode) {
  const url = new URL(location.href)
  if (mode === 'live') url.searchParams.delete('today')
  else url.searchParams.set('today', mode)
  history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`)
  applyToday(await pullToday())
  renderApp()
}

window.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && state.drawerMode) {
    state.drawerMode = null
    renderApp()
  }
})

async function boot() {
  if (isConfigRoute()) {
    await renderConfigPage(app)
    return
  }
  app.innerHTML = `<div class="loading-screen">正在加载 Top 30 严选展厅…</div>`
  try {
    const tabParam = new URLSearchParams(location.search).get('tab')
    if (tabParam === 'today') state.drawerMode = 'today'
    const todayPromise = pullToday()
    const [listRes, metaRes] = await Promise.all([
      fetch('/data/listings-ranked.json'),
      fetch('/data/meta.json'),
    ])
    if (!listRes.ok) throw new Error(`listings-ranked.json HTTP ${listRes.status}`)
    if (!metaRes.ok) throw new Error(`meta.json HTTP ${metaRes.status}`)
    rankedListings = (await listRes.json()).slice(0, 30)
    meta = await metaRes.json()
    applyToday(await todayPromise)
    renderApp()
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    app.innerHTML = `<div class="error-screen">数据加载失败：${esc(msg)}</div>`
  }
}

boot()
