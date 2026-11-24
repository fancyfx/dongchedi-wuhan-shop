import './style.css'
import { isConfigRoute, renderConfigPage } from './config-page'
import {
  coverImgHtml,
  esc,
  gearboxClass,
  miniMetersHtml,
  renderCompareDrawerBody,
  renderDetailDrawerBody,
  renderFilterSheetBody,
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
import type { BoardKey, Listing, Meta, PresetKey, ShopScopeKey, SortKey } from './types'

const app = document.querySelector<HTMLDivElement>('#app')!

let wuhanListings: Listing[] = []
let nationalListings: Listing[] = []
let meta: Meta | null = null
let todayData: TodayUpdates = missingToday('尚未加载')
let highlightSkus = new Set<string>()

const state = {
  board: 'wuhan' as BoardKey,
  preset: 'all' as PresetKey,
  shopScope: 'all' as ShopScopeKey,
  city: '',
  sort: 'recommend' as SortKey,
  q: '',
  priceMax: '',
  activeSku: null as string | null,
  drawerMode: null as null | 'detail' | 'today' | 'compare' | 'methodology' | 'filter',
  todayFilter: 'all' as TodayFilter,
  compareSkus: [] as string[],
}

function activeListings(): Listing[] {
  return state.board === 'wuhan' ? wuhanListings : nationalListings
}

function findListingBySku(sku: string): Listing | undefined {
  return activeListings().find((x) => x.sku === sku) || nationalListings.find((x) => x.sku === sku) || wuhanListings.find((x) => x.sku === sku)
}

function boardFromSearch(search: string): BoardKey {
  const value = new URLSearchParams(search).get('board')
  return value === 'national' ? 'national' : 'wuhan'
}

function setBoard(next: BoardKey) {
  if (state.board === next) return
  state.board = next
  if (next === 'wuhan') {
    state.shopScope = 'all'
    state.city = ''
    if (state.preset === 'wuhan') state.preset = 'all'
  }
  const url = new URL(location.href)
  url.searchParams.set('board', next)
  history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`)
  renderApp()
}

function landedPrice(item: Listing): number {
  return Number(item.effective_price_wan ?? item.landed_price_wan ?? item.price)
}

function cashPrice(item: Listing): number {
  return Number(item.cash_price_wan ?? item.price)
}

function isLocalWuhan(item: Listing): boolean {
  if (typeof item.is_local_wuhan === 'boolean') return item.is_local_wuhan
  return item.shop_id === '118608' || item.city === '武汉'
}

function originShortLabel(item: Listing): string {
  if (item.shop_short_name) return item.shop_short_name
  if (item.city) return `${item.city}店`
  return isLocalWuhan(item) ? '武汉店' : '直营店'
}

function fmtTime(iso?: string): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso
    return d.toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      timeZone: 'Asia/Shanghai',
    })
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
    case 'wuhan':
      return isLocalWuhan(item)
    case 'at':
      return p?.gearbox_tier === 'AT' || p?.gearbox_tier === 'E_CVT'
    case 'under5':
      return landedPrice(item) <= 5.0
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

function matchesShopScope(item: Listing): boolean {
  if (state.board === 'wuhan') return true
  if (state.shopScope === 'wuhan') return isLocalWuhan(item)
  if (state.shopScope === 'low_freight') {
    return isLocalWuhan(item) || (item.logistics_fee_yuan ?? 9999) <= 1000
  }
  return true
}

function filteredListings(): Listing[] {
  const source = activeListings()
  const q = state.q.trim().toLowerCase()
  const pMax = state.priceMax === '' ? null : Number(state.priceMax)
  let rows = source.filter((item) => {
    if (!matchesShopScope(item)) return false
    if (state.board === 'national' && state.city && (item.city || '') !== state.city) return false
    if (!matchesPreset(item, state.preset)) return false
    if (pMax != null && !Number.isNaN(pMax) && landedPrice(item) > pMax) return false
    if (q) {
      const hay = [
        item.sku,
        item.title,
        item.city || '',
        item.shop_short_name || '',
        item.shop_name || '',
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
      rows.sort((a, b) => landedPrice(a) - landedPrice(b) || (a.rank ?? 99) - (b.rank ?? 99))
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
  return (
    state.preset === 'all' &&
    (state.board === 'wuhan' || state.shopScope === 'all') &&
    (state.board === 'wuhan' || !state.city) &&
    state.sort === 'recommend' &&
    !state.q.trim() &&
    !state.priceMax
  )
}

function presetCounts(): Record<PresetKey, number> {
  const source = activeListings()
  return {
    all: source.length,
    wuhan: source.filter((x) => matchesPreset(x, 'wuhan')).length,
    at: source.filter((x) => matchesPreset(x, 'at')).length,
    under5: source.filter((x) => matchesPreset(x, 'under5')).length,
    lowmile: source.filter((x) => matchesPreset(x, 'lowmile')).length,
    suv: source.filter((x) => matchesPreset(x, 'suv')).length,
    sedan_b: source.filter((x) => matchesPreset(x, 'sedan_b')).length,
    l2: source.filter((x) => matchesPreset(x, 'l2')).length,
  }
}

function cardInnerHtml(item: Listing, hero = false): string {
  const p = item.v3_profile
  const rankNo = String(item.rank ?? '—').padStart(2, '0')
  const total = item.total_score ?? item.sort_scores?.total_score
  const compared = state.compareSkus.includes(item.sku)
  const isNewTop = highlightSkus.has(item.sku)
  const topClass = item.rank && item.rank <= 3 ? `top-card-${item.rank}` : ''
  const local = isLocalWuhan(item)
  const effWan = landedPrice(item)
  const bareWan = cashPrice(item)
  const logiYuan = Math.max(0, Math.round(item.logistics_fee_yuan ?? 0))
  const pdiffYuan = Math.max(0, Math.round(item.plate_fee_diff_yuan ?? 0))
  const originLbl = originShortLabel(item)
  const yearMile = [
    item.plate_year ? `${item.plate_year}年` : '',
    item.mileage_wan != null ? `${item.mileage_wan.toFixed(2)}万km` : '',
    item.specs?.body_type || '',
  ]
    .filter(Boolean)
    .join(' · ')
  const mechLine = [p?.engine_summary, p?.rear_suspension_short, p?.drive_short, p?.fuel_grade]
    .filter(Boolean)
    .join(' · ')
  const feats = (p?.feature_highlights || []).slice(0, hero ? 7 : 6)

  const breakdownHtml = local
    ? `<div class="cost-breakdown local">武汉店本地提车 · 免物流费（本地上牌费 500 元）</div>`
    : `<div class="cost-breakdown remote">裸车 ${bareWan.toFixed(2)}万 + 官方物流 ${logiYuan}元${pdiffYuan > 0 ? ` + 异地上牌差 ${pdiffYuan}元` : ''}</div>`

  const originBadgeText = local ? '武汉本地' : `${originLbl}${logiYuan > 0 ? ` · ${logiYuan}物流` : ''}`
  const crossRankBadge =
    state.board === 'wuhan'
      ? item.national_rank
        ? `<span class="cross-rank-chip">全国#${item.national_rank}</span>`
        : ''
      : item.wuhan_rank
        ? `<span class="cross-rank-chip">武汉#${item.wuhan_rank}</span>`
        : ''

  return `
    <article class="car-card ${hero ? 'hero-card' : ''} ${topClass} ${compared ? 'is-compared' : ''}" data-sku="${esc(item.sku)}">
      <div class="card-media" data-open-detail="${esc(item.sku)}">
        ${coverImgHtml(item)}
        <div class="media-top">
          <span class="rank-chip ${item.rank && item.rank <= 3 ? `top-${item.rank}` : ''}">#${rankNo}</span>
          ${crossRankBadge}
          ${p?.archetype_badge ? `<span class="media-arch">${esc(p.archetype_badge)}</span>` : ''}
          ${isNewTop ? `<span class="today-new-chip">新进前10</span>` : ''}
          ${p?.discount_fold ? `<span class="fold-chip">${p.discount_fold}折</span>` : ''}
        </div>
        <div class="media-bottom">
          <button type="button" class="cmp-toggle ${compared ? 'active' : ''}" data-cmp-toggle="${esc(item.sku)}" aria-pressed="${compared ? 'true' : 'false'}">
            ${compared ? '✓ 已选对比' : '+ 对比'}
          </button>
          <span class="media-score">严选 <strong>${total != null ? total.toFixed(1) : '—'}</strong></span>
        </div>
      </div>
      <div class="card-body">
        <div class="card-head-meta">
          <div class="head-meta-left">
            <span class="origin-badge ${local ? 'local' : 'remote'}">${esc(originBadgeText)}</span>
            <span class="card-sub">${esc(yearMile)}</span>
          </div>
          <span class="head-score-desktop">严选分 <strong>${total != null ? total.toFixed(1) : '—'}</strong></span>
        </div>
        <h3 class="card-title" data-open-detail="${esc(item.sku)}" title="${esc(item.title)}">${esc(item.title)}</h3>

        <div class="price-block">
          <span class="cash-price">${effWan.toFixed(2)}<small>万</small></span>
          <span class="price-tag-mini">${local ? '现金价' : '到汉价'}</span>
          ${p?.msrp_wan ? `<span class="msrp-info"><del>${p.msrp_wan.toFixed(2)}万</del>${p.saved_wan ? `<b class="saved-badge">省${p.saved_wan.toFixed(1)}万</b>` : ''}</span>` : ''}
        </div>
        ${breakdownHtml}

        <div class="mech-bar">
          <span class="gb-badge ${gearboxClass(p?.gearbox_tier)}">${esc(p?.gearbox_label || '自动')}</span>
          <span class="mech-text">${esc(mechLine)}</span>
        </div>

        ${feats.length ? `<div class="feat-pills">${feats.map((f) => `<span>${esc(f)}</span>`).join('')}</div>` : ''}

        ${hero ? `<div class="hero-only-bars">${scoreBarsHtml(item)}</div>` : ''}
        <div class="card-meters">${miniMetersHtml(item)}</div>

        <p class="advisor-line" title="${esc(p?.recommend_reason || item.evaluation || '')}">${esc(p?.recommend_reason || item.evaluation || '')}</p>

        <div class="card-actions">
          <button type="button" class="btn-report" data-open-detail="${esc(item.sku)}">买手报告 &amp; 验车</button>
          <a class="btn-ghost" href="?sku=${encodeURIComponent(item.sku)}">参配</a>
          <a class="btn-ghost" href="${esc(item.detail_url)}" target="_blank" rel="noopener noreferrer">原车 ↗</a>
        </div>
      </div>
    </article>`
}

function mastheadHtml(): string {
  const isWuhan = state.board === 'wuhan'
  const wuhanMeta = meta?.boards?.wuhan
  const nationalMeta = meta?.boards?.national

  const activeOnSale = isWuhan ? (wuhanMeta?.on_sale_count ?? '—') : (nationalMeta?.on_sale_count ?? meta?.on_sale_count ?? '—')
  const activeVetoed = isWuhan ? (wuhanMeta?.vetoed_count ?? '—') : (nationalMeta?.vetoed_count ?? meta?.vetoed_count ?? '—')
  const activeReserved = isWuhan ? (wuhanMeta?.reserved_count ?? 0) : (nationalMeta?.reserved_count ?? meta?.reserved_count ?? 0)
  const activeEligible = isWuhan ? (wuhanMeta?.eligible_count ?? meta?.wuhan_eligible_count) : (nationalMeta?.eligible_count ?? meta?.library_scored_count)
  const currentList = activeListings()
  const rankedCnt = currentList.length
  const localCntInNational = nationalListings.filter(isLocalWuhan).length
  const remoteCntInNational = Math.max(0, nationalListings.length - localCntInNational)
  const wuhanFloor = wuhanMeta?.display_score_floor ?? meta?.wuhan_display_score_floor
  const todayBadge = todayData.has_snapshot
    ? todayData.counts.added + todayData.counts.updated_price + todayData.counts.removed_sold
    : 0

  const eyebrow = isWuhan
    ? 'DONGCHEDI WUHAN · LOCAL DIRECT SHOP'
    : 'DONGCHEDI NATIONAL · DIRECT SHOPS → WUHAN'
  const heading = isWuhan ? `武汉榜 · 本地直提 Top ${rankedCnt || 30}` : `全国榜 · 直营到汉 Top ${rankedCnt || 30}`
  const lead = isWuhan
    ? '聚焦武汉官方直营店本地现车，免异地物流费、本地上牌标准，可随时到店实看试驾，独立执行 V3.2 严选排名。'
    : '覆盖全国多城官方直营店仓（武汉/长沙/合肥/南京/郑州/重庆/成都），自动计入官方到汉物流费与异地上牌差额，统一以到汉总价≤6万横评。'

  return `
    <header class="masthead">
      <div class="masthead-top">
        <div class="brand-lockup">
          <div class="eyebrow">${eyebrow}</div>
          <h1>${heading}</h1>
          <p class="lead">${lead}</p>
        </div>
        <div class="masthead-actions">
          <button type="button" class="action-pill" id="btn-open-methodology">选车铁律</button>
          <button type="button" class="action-pill accent" id="btn-open-today">
            今日变动${todayBadge > 0 ? `<span class="action-count">${todayBadge}</span>` : ''}
          </button>
        </div>
      </div>

      <nav class="board-switcher" role="tablist" aria-label="切换榜单">
        <button
          type="button"
          role="tab"
          aria-selected="${isWuhan ? 'true' : 'false'}"
          class="board-tab ${isWuhan ? 'active' : ''}"
          data-board="wuhan"
        >
          <span class="bt-main">
            <strong>武汉榜</strong>
            <span class="bt-count">Top ${wuhanListings.length}</span>
          </span>
          <span class="bt-sub">本地直提 · 免物流现车</span>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected="${!isWuhan ? 'true' : 'false'}"
          class="board-tab ${!isWuhan ? 'active' : ''}"
          data-board="national"
        >
          <span class="bt-main">
            <strong>全国榜</strong>
            <span class="bt-count">Top ${nationalListings.length}</span>
          </span>
          <span class="bt-sub">全国直营 · 含运费到汉比价</span>
        </button>
      </nav>

      <div class="funnel-strip" aria-label="数据清洗漏斗">
        <span class="funnel-chip">${isWuhan ? '武汉在售' : '全国在售'} <b>${activeOnSale}</b></span>
        <span class="funnel-sep">→</span>
        <span class="funnel-chip veto">铁律否决 <b>-${activeVetoed}</b></span>
        ${activeReserved > 0 ? `<span class="funnel-sep">→</span><span class="funnel-chip muted">锁单藏 <b>${activeReserved}</b></span>` : ''}
        ${activeEligible != null ? `<span class="funnel-sep">→</span><span class="funnel-chip">参评 <b>${activeEligible}</b></span>` : ''}
        <span class="funnel-sep">→</span>
        <span class="funnel-chip final">${
          isWuhan
            ? `武汉榜 <b>Top ${rankedCnt}</b>${wuhanFloor != null ? `（≥${Number(wuhanFloor).toFixed(1)}分）` : ''}`
            : `全国榜 <b>Top ${rankedCnt}</b>${rankedCnt ? `（汉${localCntInNational}/外${remoteCntInNational}）` : ''}`
        }</span>
        <span class="funnel-time">更新 ${esc(fmtTime(meta?.ranked_at))}</span>
      </div>
    </header>`
}

function stickyBarHtml(shown: Listing[]): string {
  const isWuhan = state.board === 'wuhan'
  const source = activeListings()
  const counts = presetCounts()
  const presets: [PresetKey, string][] = isWuhan
    ? [
        ['all', `全部 ${counts.all}`],
        ['suv', `SUV/四驱 ${counts.suv}`],
        ['l2', `L2智驾 ${counts.l2}`],
        ['lowmile', `4万km内 ${counts.lowmile}`],
        ['under5', `5万内 ${counts.under5}`],
        ['at', `AT/电混 ${counts.at}`],
        ['sedan_b', `B级轿 ${counts.sedan_b}`],
      ]
    : [
        ['all', `全部 ${counts.all}`],
        ['wuhan', `武汉本地 ${counts.wuhan}`],
        ['suv', `SUV/四驱 ${counts.suv}`],
        ['l2', `L2智驾 ${counts.l2}`],
        ['lowmile', `4万km内 ${counts.lowmile}`],
        ['under5', `5万内 ${counts.under5}`],
        ['at', `AT/电混 ${counts.at}`],
        ['sedan_b', `B级轿 ${counts.sedan_b}`],
      ]
  const avgPrice = shown.length ? (shown.reduce((a, b) => a + landedPrice(b), 0) / shown.length).toFixed(2) : '—'
  const activeFilterCount =
    (state.q.trim() ? 1 : 0) +
    (state.priceMax ? 1 : 0) +
    (!isWuhan && state.shopScope !== 'all' ? 1 : 0) +
    (!isWuhan && state.city ? 1 : 0)

  const scopeChip =
    !isWuhan && state.shopScope === 'wuhan'
      ? `<button type="button" class="active-chip" id="btn-clear-scope">仅武汉 ×</button>`
      : !isWuhan && state.shopScope === 'low_freight'
        ? `<button type="button" class="active-chip" id="btn-clear-scope">运费≤1k ×</button>`
        : ''

  return `
    <section class="sticky-bar" aria-label="筛选与排序">
      <div class="preset-row">
        ${presets
          .map(
            ([k, label]) =>
              `<button type="button" class="preset-chip ${state.preset === k ? 'active' : ''}" data-preset="${k}">${esc(label)}</button>`,
          )
          .join('')}
      </div>
      <div class="bar-ctrl-row">
        <div class="bar-stats">
          <strong>${shown.length}</strong><span class="bar-total">/${source.length}台</span>
          <span class="bar-avg">${isWuhan ? '全款均' : '到汉均'} <b>${avgPrice}万</b></span>
          ${scopeChip}
          ${!isWuhan && state.city ? `<button type="button" class="active-chip" id="btn-clear-city">${esc(state.city)} ×</button>` : ''}
          ${state.q.trim() ? `<button type="button" class="active-chip" id="btn-clear-q">${esc(state.q.trim())} ×</button>` : ''}
          ${state.priceMax ? `<button type="button" class="active-chip" id="btn-clear-pmax">≤${esc(state.priceMax)}万 ×</button>` : ''}
        </div>

        <div class="desktop-only-inputs">
          <input id="ctrl-q" type="search" placeholder="${isWuhan ? '搜车型 / 品牌' : '搜车型 / 城市 / 品牌'}" value="${esc(state.q)}" />
          <input id="ctrl-pmax" type="number" min="0" max="6" step="0.1" placeholder="${isWuhan ? '现金上限' : '到汉上限'}" value="${esc(state.priceMax)}" />
        </div>

        <div class="bar-actions">
          <select id="ctrl-sort" aria-label="排序方式">
            <option value="recommend" ${state.sort === 'recommend' ? 'selected' : ''}>综合严选</option>
            <option value="powertrain" ${state.sort === 'powertrain' ? 'selected' : ''}>三大件稳</option>
            <option value="config" ${state.sort === 'config' ? 'selected' : ''}>高配优先</option>
            <option value="discount" ${state.sort === 'discount' ? 'selected' : ''}>折数最低</option>
            <option value="price" ${state.sort === 'price' ? 'selected' : ''}>${isWuhan ? '现金价低' : '到汉总价'}</option>
            <option value="mileage" ${state.sort === 'mileage' ? 'selected' : ''}>里程最低</option>
          </select>
          <button type="button" class="filter-sheet-btn ${activeFilterCount > 0 ? 'has-active' : ''}" id="btn-open-filter">
            筛选${activeFilterCount > 0 ? `<span class="fs-badge">${activeFilterCount}</span>` : ''}
          </button>
        </div>
      </div>
    </section>`
}

function compareBarHtml(): string {
  if (!state.compareSkus.length) return ''
  const selected = state.compareSkus
    .map((sku) => findListingBySku(sku))
    .filter((x): x is Listing => Boolean(x))
  return `
    <div class="compare-dock">
      <div class="cmp-dock-list">
        <span class="cmp-dock-label">对比 (${selected.length}/3)</span>
        ${selected.map((x) => `<span class="cmp-chip">#${x.rank} ${esc(x.series || x.title.slice(0, 8))} <button type="button" data-cmp-remove="${esc(x.sku)}">×</button></span>`).join('')}
      </div>
      <div class="cmp-dock-actions">
        <button type="button" class="btn-clear-cmp" id="btn-clear-cmp">清空</button>
        <button type="button" class="btn-open-cmp" id="btn-open-cmp" ${selected.length < 2 ? 'disabled' : ''}>
          ${selected.length < 2 ? '再选1台' : `对比 ${selected.length} 台`}
        </button>
      </div>
    </div>`
}

function drawerHostHtml(shownCount: number): string {
  if (!state.drawerMode) return ''
  let title = ''
  let body = ''
  let extraCls = ''
  const source = activeListings()

  if (state.drawerMode === 'detail' && state.activeSku) {
    const item = findListingBySku(state.activeSku)
    if (item) {
      const boardLbl = item.board_scope === 'wuhan' || (state.board === 'wuhan' && isLocalWuhan(item)) ? '武汉榜' : '全国榜'
      title = `买手深度报告 · ${boardLbl} #${String(item.rank ?? '—').padStart(2, '0')}`
      body = renderDetailDrawerBody(item, state.board)
      extraCls = 'wide'
    }
  } else if (state.drawerMode === 'compare') {
    const selected = state.compareSkus
      .map((sku) => findListingBySku(sku))
      .filter((x): x is Listing => Boolean(x))
    title = `严选车源横向对比（${selected.length} 台）`
    body = renderCompareDrawerBody(selected)
    extraCls = 'extra-wide'
  } else if (state.drawerMode === 'filter') {
    const cityMap = new Map<string, number>()
    for (const item of source) {
      const c = item.city || (isLocalWuhan(item) ? '武汉' : '')
      if (c) cityMap.set(c, (cityMap.get(c) || 0) + 1)
    }
    const cityCounts = [...cityMap.entries()].sort((a, b) => b[1] - a[1])
    title = state.board === 'wuhan' ? '武汉榜筛选、预算与排序' : '全国榜门店范围、预算与排序'
    body = renderFilterSheetBody({
      board: state.board,
      q: state.q,
      priceMax: state.priceMax,
      sort: state.sort,
      shopScope: state.shopScope,
      city: state.city,
      cityCounts,
      shownCount,
      totalCount: source.length,
    })
    extraCls = 'compact-sheet'
  } else if (state.drawerMode === 'methodology') {
    title = 'V3 选车铁律与评分方法论'
    body = renderMethodologyModalBody()
    extraCls = 'wide'
  } else if (state.drawerMode === 'today') {
    const allBoardSkus = new Set([...wuhanListings.map((x) => x.sku), ...nationalListings.map((x) => x.sku)])
    title = '每日库存与价格对账日志'
    body = renderTodayPanel({
      data: todayData,
      filter: state.todayFilter,
      fixtureMode: todayModeFromSearch(location.search) === 'fixture',
      onBoard: allBoardSkus,
      highlightCardsHtml: '',
    })
    extraCls = 'wide'
  }

  if (!body) return ''
  return `
    <div class="drawer-backdrop" id="drawer-backdrop">
      <aside class="drawer-panel ${extraCls}" role="dialog" aria-modal="true" aria-label="${esc(title)}">
        <div class="sheet-handle" aria-hidden="true"><span></span></div>
        <div class="drawer-top">
          <strong>${esc(title)}</strong>
          <button type="button" class="drawer-close" id="btn-close-drawer" aria-label="关闭">✕</button>
        </div>
        <div class="drawer-scroll">${body}</div>
      </aside>
    </div>`
}

function renderCatalogSection(shown: Listing[]): string {
  const isWuhan = state.board === 'wuhan'
  const boardName = isWuhan ? '武汉榜' : '全国榜'
  const totalInBoard = activeListings().length
  if (!shown.length) {
    return `
      <div class="empty-state">
        <p>当前筛选条件下没有入围${boardName} Top ${totalInBoard || 30} 车源</p>
        <button type="button" class="btn-report" id="btn-empty-reset">恢复${boardName}全部 ${totalInBoard} 台</button>
      </div>`
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
        <h2>${isWuhan ? '武汉榜头号三甲 · 本地直提 Top 3' : '全国榜头号三甲 · 直营到汉 Top 3'}</h2>
        <span>${isWuhan ? '武汉店现车免物流 × 新世代高配 SUV 主导' : '全国直营跨城横评 × 已计入到汉运费与上牌差'}</span>
      </div>
      <div class="podium-lead">${cardInnerHtml(top1, true)}</div>
      <div class="podium-runners">${top23.map((x) => cardInnerHtml(x, false)).join('')}</div>
    </section>
    ${
      rest.length
        ? `
    <section class="catalog-section">
      <div class="sec-head">
        <h2>${boardName}严选阵容 · 第 4 – ${shown.length} 名</h2>
        <span>点卡片看针对性验车清单与真实口碑</span>
      </div>
      <div class="cards-grid">${rest.map((x) => cardInnerHtml(x, false)).join('')}</div>
    </section>`
        : ''
    }`
}

function renderApp() {
  const shown = filteredListings()
  document.body.classList.toggle('no-scroll', Boolean(state.drawerMode))
  app.innerHTML = `
    <div class="page-shell">
      ${mastheadHtml()}
      ${todayModeFromSearch(location.search) === 'fixture' ? fixtureBannerHtml() : ''}
      ${stickyBarHtml(shown)}
      <main id="catalog-main">${renderCatalogSection(shown)}</main>
      <footer class="site-footer">
        <span>懂车帝官方直营双榜严选（武汉榜本地直提 / 全国榜含到汉物流费横评）+ 汽车之家实测参配</span>
        <span class="footer-links">
          <a href="/data/listings-ranked-wuhan.json" target="_blank" rel="noopener noreferrer">武汉榜 JSON</a>
          <a href="/data/listings-ranked.json" target="_blank" rel="noopener noreferrer">全国榜 JSON</a>
          <a href="/data/meta.json" target="_blank" rel="noopener noreferrer">Meta</a>
          <a href="/data/today-updates.json" target="_blank" rel="noopener noreferrer">今日变动 JSON</a>
        </span>
      </footer>
    </div>
    ${compareBarHtml()}
    ${drawerHostHtml(shown.length)}
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
  document.querySelectorAll<HTMLButtonElement>('[data-board]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const next = btn.dataset.board === 'national' ? 'national' : 'wuhan'
      setBoard(next)
    })
  })

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

  document.getElementById('btn-clear-q')?.addEventListener('click', () => {
    state.q = ''
    renderApp()
  })
  document.getElementById('btn-clear-pmax')?.addEventListener('click', () => {
    state.priceMax = ''
    renderApp()
  })
  document.getElementById('btn-clear-scope')?.addEventListener('click', () => {
    state.shopScope = 'all'
    renderApp()
  })
  document.getElementById('btn-clear-city')?.addEventListener('click', () => {
    state.city = ''
    renderApp()
  })
  document.getElementById('btn-empty-reset')?.addEventListener('click', () => {
    state.preset = 'all'
    state.shopScope = 'all'
    state.city = ''
    state.q = ''
    state.priceMax = ''
    state.sort = 'recommend'
    renderApp()
  })

  document.getElementById('btn-open-filter')?.addEventListener('click', () => {
    state.drawerMode = 'filter'
    renderApp()
  })

  // Filter Sheet bindings
  const sheetBoardLbl = state.board === 'wuhan' ? '武汉榜' : '全国榜'
  const sheetQ = document.getElementById('sheet-q') as HTMLInputElement | null
  sheetQ?.addEventListener('input', () => {
    state.q = sheetQ.value
    const applyBtn = document.getElementById('btn-sheet-apply')
    if (applyBtn) {
      applyBtn.textContent = `查看 ${filteredListings().length} / ${activeListings().length} 台${sheetBoardLbl}`
    }
  })
  const sheetPmax = document.getElementById('sheet-pmax') as HTMLInputElement | null
  sheetPmax?.addEventListener('input', () => {
    state.priceMax = sheetPmax.value
    const applyBtn = document.getElementById('btn-sheet-apply')
    if (applyBtn) {
      applyBtn.textContent = `查看 ${filteredListings().length} / ${activeListings().length} 台${sheetBoardLbl}`
    }
  })
  document.querySelectorAll<HTMLButtonElement>('[data-sheet-kw]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const kw = btn.dataset.sheetKw || ''
      state.q = state.q.trim() === kw ? '' : kw
      renderApp()
    })
  })
  document.querySelectorAll<HTMLButtonElement>('[data-sheet-pmax]').forEach((btn) => {
    btn.addEventListener('click', () => {
      state.priceMax = btn.dataset.sheetPmax ?? ''
      renderApp()
    })
  })
  document.querySelectorAll<HTMLButtonElement>('[data-sheet-scope]').forEach((btn) => {
    btn.addEventListener('click', () => {
      state.shopScope = (btn.dataset.sheetScope as ShopScopeKey) || 'all'
      renderApp()
    })
  })
  document.querySelectorAll<HTMLButtonElement>('[data-sheet-city]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const c = btn.dataset.sheetCity ?? ''
      state.city = state.city === c ? '' : c
      renderApp()
    })
  })
  document.querySelectorAll<HTMLButtonElement>('[data-sheet-sort]').forEach((btn) => {
    btn.addEventListener('click', () => {
      state.sort = (btn.dataset.sheetSort as SortKey) || 'recommend'
      renderApp()
    })
  })
  document.getElementById('btn-sheet-reset')?.addEventListener('click', () => {
    state.preset = 'all'
    state.shopScope = 'all'
    state.city = ''
    state.q = ''
    state.priceMax = ''
    state.sort = 'recommend'
    renderApp()
  })
  document.getElementById('btn-sheet-apply')?.addEventListener('click', () => {
    state.drawerMode = null
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
  todayData = reconcileToday(next, nationalListings, [])
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
  app.innerHTML = `<div class="loading-screen">正在加载武汉榜 &amp; 全国榜 Top 30 严选展厅…</div>`
  try {
    const params = new URLSearchParams(location.search)
    state.board = boardFromSearch(location.search)
    const tabParam = params.get('tab')
    if (tabParam === 'today') state.drawerMode = 'today'
    const todayPromise = pullToday()
    const [nationalRes, wuhanRes, metaRes] = await Promise.all([
      fetch('/data/listings-ranked.json'),
      fetch('/data/listings-ranked-wuhan.json'),
      fetch('/data/meta.json'),
    ])
    if (!nationalRes.ok) throw new Error(`listings-ranked.json HTTP ${nationalRes.status}`)
    if (!metaRes.ok) throw new Error(`meta.json HTTP ${metaRes.status}`)
    nationalListings = (await nationalRes.json()).slice(0, 30)
    if (wuhanRes.ok) {
      wuhanListings = (await wuhanRes.json()).slice(0, 30)
    } else {
      wuhanListings = nationalListings
        .filter(isLocalWuhan)
        .map((item, idx) => ({ ...item, national_rank: item.rank, rank: idx + 1, board_scope: 'wuhan' }))
    }
    meta = await metaRes.json()
    applyToday(await todayPromise)
    renderApp()
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    app.innerHTML = `<div class="error-screen">数据加载失败：${esc(msg)}</div>`
  }
}

boot()
