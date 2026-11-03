// 重点推荐只认两件事同时成立：change_type 为 added，且全场 total_score 排名在 1–10。
export const HIGHLIGHT_MAX_RANK = 10

export type TodayMode = 'live' | 'fixture' | 'missing' | 'blank'
export type TodayFilter = 'all' | 'added' | 'info' | 'other'
export type TodaySource = 'snapshot' | 'fixture' | 'missing'

export type TodayItem = {
  sku: string
  title: string
  change_type: string
  old_price: number | null
  new_price: number | null
  old_score: number | null
  new_score: number | null
  rank: number | null
  reason: string | null
  at: string | null
  highlight: boolean
}

export type TodayCounts = {
  added: number
  updated: number
  updated_price: number
  info_updated: number
  highlights: number
  display_dropped: number
  rejected_hard_filter: number
  rejected_below_top100: number
  removed_hard_filter: number
  detail_failed: number
  not_admitted: number
  other: number
  total: number
}

export type TodaySummary = {
  started_at?: string | null
  dry_run?: boolean | null
  threshold?: number | null
  display_count?: number | null
  below_display_count?: number | null
  issue_count?: number | null
  inventory_count?: number | null
  catalog_written?: boolean | null
}

export type TodayUpdates = {
  schema: string
  date: string | null
  generated_at: string | null
  source: TodaySource
  has_snapshot: boolean
  changelog_empty: boolean
  snapshot_dir: string | null
  note: string | null
  summary: TodaySummary
  counts: TodayCounts
  highlights: TodayItem[]
  items: TodayItem[]
}

type RankedRef = { sku: string; rank?: number | null }
type IssueRef = { sku: string }

const CHANGE_LABEL: Record<string, string> = {
  added: '新入库',
  updated: '信息更新',
  updated_price: '价格更新',
  display_dropped: '跌出展示',
  rejected_hard_filter: '硬筛未过',
  rejected_below_top100: '未进前100',
  removed_hard_filter: '移出库存',
  detail_failed: '详情失败',
}

const REASON_LABEL: Record<string, string> = {
  outside_top100_display: '排到展示名额之外',
  no_score: '算不出分数，未入库',
  score_below_threshold: '低于展示门槛，未入库',
  not_in_display_top100: '同分未进展示名额，未入库',
  fixture_price_change: '演示用的价格变动',
  fixture_info_change: '演示用的信息变动',
}

export function todayModeFromSearch(search: string): TodayMode {
  const value = new URLSearchParams(search).get('today')
  if (value === 'fixture' || value === 'missing' || value === 'blank') return value
  return 'live'
}

export function isHighlight(changeType: string, rank: number | null): boolean {
  return changeType === 'added' && rank != null && rank >= 1 && rank <= HIGHLIGHT_MAX_RANK
}

export function emptyCounts(): TodayCounts {
  return {
    added: 0,
    updated: 0,
    updated_price: 0,
    info_updated: 0,
    highlights: 0,
    display_dropped: 0,
    rejected_hard_filter: 0,
    rejected_below_top100: 0,
    removed_hard_filter: 0,
    detail_failed: 0,
    not_admitted: 0,
    other: 0,
    total: 0,
  }
}

export function countItems(items: TodayItem[]): TodayCounts {
  const counts = emptyCounts()
  for (const item of items) {
    counts.total += 1
    if (item.highlight) counts.highlights += 1
    switch (item.change_type) {
      case 'added':
        counts.added += 1
        break
      case 'updated':
        counts.updated += 1
        counts.info_updated += 1
        break
      case 'updated_price':
        counts.updated_price += 1
        counts.info_updated += 1
        break
      case 'display_dropped':
        counts.display_dropped += 1
        break
      case 'rejected_hard_filter':
        counts.rejected_hard_filter += 1
        break
      case 'rejected_below_top100':
        counts.rejected_below_top100 += 1
        break
      case 'removed_hard_filter':
        counts.removed_hard_filter += 1
        break
      case 'detail_failed':
        counts.detail_failed += 1
        break
      default:
        counts.other += 1
    }
  }
  counts.not_admitted =
    counts.rejected_hard_filter + counts.rejected_below_top100 + counts.removed_hard_filter + counts.detail_failed
  return counts
}

function asNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim() && Number.isFinite(Number(value))) return Number(value)
  return null
}

function asRank(value: unknown): number | null {
  const number = asNumber(value)
  if (number == null || !Number.isInteger(number) || number < 1) return null
  return number
}

function normalizeItem(raw: unknown): TodayItem | null {
  if (!raw || typeof raw !== 'object') return null
  const obj = raw as Record<string, unknown>
  const sku = String(obj.sku ?? '').trim()
  if (!sku) return null
  const changeType = String(obj.change_type ?? '').trim() || 'updated'
  const rank = asRank(obj.rank)
  return {
    sku,
    title: String(obj.title ?? '').trim() || sku,
    change_type: changeType,
    old_price: asNumber(obj.old_price),
    new_price: asNumber(obj.new_price),
    old_score: asNumber(obj.old_score),
    new_score: asNumber(obj.new_score),
    rank,
    reason: obj.reason == null || obj.reason === '' ? null : String(obj.reason),
    at: obj.at == null || obj.at === '' ? null : String(obj.at),
    highlight: isHighlight(changeType, rank),
  }
}

function normalizeSummary(raw: unknown): TodaySummary {
  if (!raw || typeof raw !== 'object') return {}
  const obj = raw as Record<string, unknown>
  const summary: TodaySummary = {}
  if (typeof obj.started_at === 'string') summary.started_at = obj.started_at
  if (typeof obj.dry_run === 'boolean') summary.dry_run = obj.dry_run
  if (typeof obj.catalog_written === 'boolean') summary.catalog_written = obj.catalog_written
  const threshold = asNumber(obj.threshold)
  const displayCount = asNumber(obj.display_count)
  const below = asNumber(obj.below_display_count)
  const issues = asNumber(obj.issue_count)
  const inventory = asNumber(obj.inventory_count)
  if (threshold != null) summary.threshold = threshold
  if (displayCount != null) summary.display_count = displayCount
  if (below != null) summary.below_display_count = below
  if (issues != null) summary.issue_count = issues
  if (inventory != null) summary.inventory_count = inventory
  return summary
}

function withDerived(data: TodayUpdates): TodayUpdates {
  const highlights = data.items
    .filter((item) => item.highlight)
    .sort((a, b) => (a.rank ?? 9999) - (b.rank ?? 9999) || a.sku.localeCompare(b.sku))
  return {
    ...data,
    highlights,
    counts: countItems(data.items),
    changelog_empty: data.items.length === 0,
  }
}

export function missingToday(note: string): TodayUpdates {
  return withDerived({
    schema: 'today-updates/v1',
    date: null,
    generated_at: null,
    source: 'missing',
    has_snapshot: false,
    changelog_empty: true,
    snapshot_dir: null,
    note,
    summary: {},
    counts: emptyCounts(),
    highlights: [],
    items: [],
  })
}

export function blankToday(): TodayUpdates {
  return normalizeToday({
    schema: 'today-updates/v1',
    date: null,
    source: 'snapshot',
    has_snapshot: true,
    snapshot_dir: null,
    note: '这份快照的 changelog 是空的。',
    summary: {},
    items: [],
  })
}

export function normalizeToday(raw: unknown): TodayUpdates {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    return missingToday('今日更新数据格式不正确。')
  }
  const obj = raw as Record<string, unknown>
  const items = Array.isArray(obj.items) ? obj.items.map(normalizeItem).filter((item): item is TodayItem => item != null) : []
  const source: TodaySource =
    obj.source === 'fixture' || obj.source === 'snapshot' || obj.source === 'missing' ? obj.source : 'snapshot'
  const hasSnapshot = obj.has_snapshot === false || source === 'missing' ? false : true
  return withDerived({
    schema: typeof obj.schema === 'string' ? obj.schema : 'today-updates/v1',
    date: typeof obj.date === 'string' ? obj.date : null,
    generated_at: typeof obj.generated_at === 'string' ? obj.generated_at : null,
    source: hasSnapshot ? source : 'missing',
    has_snapshot: hasSnapshot,
    changelog_empty: items.length === 0,
    snapshot_dir: typeof obj.snapshot_dir === 'string' ? obj.snapshot_dir : null,
    note: typeof obj.note === 'string' ? obj.note : null,
    summary: normalizeSummary(obj.summary),
    counts: emptyCounts(),
    highlights: [],
    items,
  })
}

export function reconcileToday(data: TodayUpdates, ranked: RankedRef[], issues: IssueRef[]): TodayUpdates {
  const board = new Map<string, number | null>()
  for (const item of ranked) {
    const rank = item.rank
    board.set(item.sku, typeof rank === 'number' && Number.isInteger(rank) && rank >= 1 ? rank : null)
  }
  const issueSkus = new Set(issues.map((item) => item.sku))
  const items = data.items.map((item) => {
    let rank: number | null
    if (board.has(item.sku)) rank = board.get(item.sku) ?? null
    else if (issueSkus.has(item.sku)) rank = null
    else rank = item.rank
    return { ...item, rank, highlight: isHighlight(item.change_type, rank) }
  })
  return withDerived({ ...data, items })
}

function esc(value: unknown): string {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
}

function formatShanghai(iso?: string | null): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString('zh-CN', { hour12: false, timeZone: 'Asia/Shanghai' })
}

export function alertTagsHtml(): string {
  return `<div class="alert-tags"><span class="alert-tag">重点推荐</span><span class="alert-tag alt">新进前10</span></div>`
}

function changeLabel(changeType: string): string {
  return CHANGE_LABEL[changeType] || '其他变更'
}

function pillClass(changeType: string): string {
  return /^[a-z0-9_]+$/.test(changeType) ? changeType : 'other'
}

function reasonText(reason: string | null): string {
  if (!reason) return ''
  if (reason.startsWith('missing_cash_price')) return '缺少现金价，未入库'
  if (REASON_LABEL[reason]) return REASON_LABEL[reason]
  return reason.length > 80 ? `${reason.slice(0, 80)}…` : reason
}

function formatMoney(value: number): string {
  return `${value.toFixed(2)}万`
}

function formatScore(value: number): string {
  return value.toFixed(1)
}

function spanChange(oldValue: number | null, newValue: number | null, format: (value: number) => string): string {
  if (oldValue == null && newValue == null) return '—'
  if (oldValue == null) return format(newValue as number)
  if (newValue == null) return `${format(oldValue)} → —`
  if (oldValue === newValue) return format(newValue)
  return `${format(oldValue)} → ${format(newValue)}`
}

function rankText(rank: number | null): string {
  return rank == null ? '未进展示榜' : `全场 #${rank}`
}

function qty(data: TodayUpdates, value: number): string {
  return data.has_snapshot ? String(value) : '—'
}

function metaLine(data: TodayUpdates): string {
  if (!data.has_snapshot) return data.note || '还没有今日入库快照。'
  const bits: string[] = []
  if (data.source === 'fixture') bits.push('演示数据')
  else if (data.date) bits.push(data.date)
  const when = data.summary.started_at || data.generated_at
  if (when) bits.push(formatShanghai(when))
  if (data.summary.dry_run === true) bits.push('dry-run')
  if (data.summary.dry_run === false) bits.push('正式入库')
  if (typeof data.summary.threshold === 'number') bits.push(`展示门槛 ${data.summary.threshold} 分`)
  if (typeof data.summary.display_count === 'number') bits.push(`展示 ${data.summary.display_count} 辆`)
  if (data.summary.catalog_written === true) bits.push('已写入库存')
  if (data.summary.catalog_written === false) bits.push('未写入库存')
  if (data.snapshot_dir) bits.push(data.snapshot_dir)
  return bits.join(' · ')
}

function highlightEmptyMessage(data: TodayUpdates): string {
  if (!data.has_snapshot) return '还没有今日快照，暂时不能判断重点推荐。'
  if (data.counts.total === 0) return '今天没有变更记录，也没有重点推荐。'
  if (data.counts.added === 0) return '今天没有新入库的车，所以没有重点推荐。'
  return '今天的新入库没有进入全场前 10 名。'
}

function listEmptyMessage(data: TodayUpdates, filter: TodayFilter): string {
  if (!data.has_snapshot) {
    return '没有可展示的今日变更。完成每日入库后，在仓库根目录运行 python3 scripts/export_today_updates.py。'
  }
  if (data.counts.total === 0) return '今天的 changelog 是空的，没有新入库或信息更新。'
  if (filter === 'added') return '今天没有新入库。'
  if (filter === 'info') return '今天没有价格、标题或里程方面的信息更新。'
  if (filter === 'other') return '今天没有跌出展示、未入库或其他记录。'
  return '今天没有变更记录。'
}

function matchesFilter(item: TodayItem, filter: TodayFilter): boolean {
  if (filter === 'all') return true
  if (filter === 'added') return item.change_type === 'added'
  if (filter === 'info') return item.change_type === 'updated' || item.change_type === 'updated_price'
  return item.change_type !== 'added' && item.change_type !== 'updated' && item.change_type !== 'updated_price'
}

export function fallbackHighlightHtml(item: TodayItem): string {
  return `
  <article class="card highlight-card" data-sku="${esc(item.sku)}" data-highlight="true">
    <div class="body">
      ${alertTagsHtml()}
      <div class="title">${esc(item.title)}</div>
      <div class="meta-row">${esc(rankText(item.rank))} · 得分 ${esc(spanChange(item.old_score, item.new_score, formatScore))}</div>
      <div class="price-row"><div class="price">${item.new_price == null ? '—' : `${Number(item.new_price).toFixed(2)}<small>万</small>`}</div><div class="price-type">新入库</div></div>
      <div class="footer-row"><span class="score">榜单 JSON 里还没有这辆车的完整卡片</span></div>
    </div>
  </article>`
}

function updateRowHtml(item: TodayItem, onBoard: Set<string>): string {
  const reason = reasonText(item.reason)
  return `
  <article class="update-row${item.highlight ? ' highlight' : ''}" data-sku="${esc(item.sku)}" data-change-type="${esc(item.change_type)}" data-highlight="${item.highlight ? 'true' : 'false'}" data-rank="${item.rank ?? ''}">
    <div class="update-pills">
      <span class="change-pill ${pillClass(item.change_type)}">${esc(changeLabel(item.change_type))}</span>
      ${item.highlight ? alertTagsHtml() : ''}
    </div>
    <div class="update-main">
      <div class="update-title">${esc(item.title)}</div>
      <div class="update-meta">价格 ${esc(spanChange(item.old_price, item.new_price, formatMoney))} · 得分 ${esc(spanChange(item.old_score, item.new_score, formatScore))} · ${esc(rankText(item.rank))}</div>
      ${reason ? `<div class="update-reason">${esc(reason)}</div>` : ''}
    </div>
    <div class="update-side">
      ${onBoard.has(item.sku) ? `<button type="button" class="btn-link" data-jump-sku="${esc(item.sku)}">在榜单中看</button>` : ''}
      <span class="update-sku">${esc(item.sku)}</span>
    </div>
  </article>`
}

function chip(filter: TodayFilter, current: TodayFilter, label: string): string {
  const active = filter === current
  return `<button type="button" class="filter-chip${active ? ' active' : ''}" data-today-filter="${filter}" aria-pressed="${active ? 'true' : 'false'}">${label}</button>`
}

export function fixtureBannerHtml(): string {
  return `<div class="today-banner fixture" id="today-mode-banner"><span>正在查看<strong>重点推荐演示数据</strong>，不是今日真实入库。榜单上的「重点推荐 / 新进前10」只标演示里新入库且全场排名 ≤ 10 的车。</span><button type="button" id="today-use-live">返回今日数据</button></div>`
}

export function renderTodayPanel(args: {
  data: TodayUpdates
  filter: TodayFilter
  fixtureMode: boolean
  onBoard: Set<string>
  highlightCardsHtml: string
}): string {
  const { data, filter, fixtureMode, onBoard } = args
  const counts = data.counts
  const rows = data.items.filter((item) => matchesFilter(item, filter))
  const otherCount = counts.total - counts.added - counts.info_updated
  const highlightBody = data.highlights.length
    ? args.highlightCardsHtml || `<div class="grid today-highlight-grid">${data.highlights.map(fallbackHighlightHtml).join('')}</div>`
    : `<div class="today-empty" id="today-highlight-empty">${esc(highlightEmptyMessage(data))}</div>`
  const listBody = rows.length
    ? `<div class="update-list" id="today-update-list">${rows.map((item) => updateRowHtml(item, onBoard)).join('')}</div>`
    : `<div class="today-empty" id="today-list-empty">${esc(listEmptyMessage(data, filter))}</div>`
  const infoHint = data.has_snapshot ? `价格 ${counts.updated_price} · 其他 ${counts.updated}` : '价格、标题或里程'

  return `
  <section class="today-panel" id="today-panel">
    <p class="today-meta">${esc(metaLine(data))}</p>
    ${data.note && data.has_snapshot ? `<p class="today-note">${esc(data.note)}</p>` : ''}
    <div class="today-actions">
      ${fixtureMode ? '' : '<button type="button" class="text-btn" id="today-use-fixture">查看重点推荐演示</button>'}
    </div>
    <section class="stats" id="today-summary">
      <div class="stat"><div class="label">新入库</div><div class="value" id="stat-added">${qty(data, counts.added)}</div><div class="hint">今天第一次写入库存</div></div>
      <div class="stat"><div class="label">信息更新</div><div class="value" id="stat-info">${qty(data, counts.info_updated)}</div><div class="hint">${esc(infoHint)}</div></div>
      <div class="stat highlight-stat"><div class="label">重点推荐</div><div class="value" id="stat-highlights">${qty(data, counts.highlights)}</div><div class="hint">新入库且全场前 10</div></div>
      <div class="stat"><div class="label">跌出展示</div><div class="value" id="stat-dropped">${qty(data, counts.display_dropped)}</div><div class="hint">排到展示名额之外</div></div>
      <div class="stat"><div class="label">未入库</div><div class="value" id="stat-rejected">${qty(data, counts.not_admitted)}</div><div class="hint">硬筛、门槛或详情失败</div></div>
      <div class="stat"><div class="label">变更条数</div><div class="value" id="stat-total">${qty(data, counts.total)}</div><div class="hint">含跌出和未入库</div></div>
    </section>
    <section class="today-block" id="today-highlights">
      <h2 class="today-heading">今日重点推荐</h2>
      <p class="today-rule">只有今天新入库、并且全场得分排名在前 10 名的车会出现在这里。前 10 里的旧车，或排名在 10 名之外的新车，都不是重点推荐。</p>
      ${highlightBody}
    </section>
    <section class="today-block" id="today-list">
      <h2 class="today-heading">今日变更</h2>
      <div class="filter-chips">
        ${chip('all', filter, `全部 ${data.has_snapshot ? counts.total : 0}`)}
        ${chip('added', filter, `新入库 ${data.has_snapshot ? counts.added : 0}`)}
        ${chip('info', filter, `信息更新 ${data.has_snapshot ? counts.info_updated : 0}`)}
        ${chip('other', filter, `其他 ${data.has_snapshot ? otherCount : 0}`)}
      </div>
      ${listBody}
    </section>
  </section>`
}
