import './config-inspector.css'

type DataIssue = {
  code?: string
  message?: string
  severity?: string
  field?: string
}

type Listing = {
  sku?: string | number
  title?: string
  config_coverage?: number
  score_eligible?: boolean
  data_issues?: DataIssue[]
  specs?: Record<string, unknown>
  detailed_config?: Record<string, unknown>
}

type Row = [key: string, label: string]

const CORE_ROWS: Row[] = [
  ['canonical_title', '核验车型'],
  ['trim_id', 'Trim ID'],
  ['powertrain_type', '动力类型'],
  ['powertrain', '动力类型(原始)'],
  ['engine', '发动机'],
  ['transmission', '变速箱'],
  ['body_type', '车身/级别'],
  ['seats', '座位数'],
  ['length_mm', '车长(mm)'],
  ['width_mm', '车宽(mm)'],
  ['height_mm', '车高(mm)'],
  ['wheelbase_mm', '轴距(mm)'],
]

const ENERGY_ROWS: Row[] = [
  ['fuel_grade', '燃油标号'],
  ['official_fuel_l_100km', '官方油耗(L/100km)'],
  ['official_standard', '油耗标准'],
  ['low_soc_fuel_l_100km', '亏电油耗(L/100km)'],
  ['real_world_fuel_l_100km', '实测油耗(L/100km)'],
  ['real_world_sample_n', '实测样本数'],
  ['electric_kwh_100km', '百公里电耗(kWh)'],
  ['ev_range_km', '纯电续航(km)'],
  ['ev_range_standard', '续航标准'],
]

const VERIFY_ROWS: Row[] = [
  ['specs_found', '找到配置数据'],
  ['verified', '已核验'],
  ['match_level', '匹配级别'],
  ['configuration_source', '配置数据源'],
  ['verification_schema', '核验版本'],
  ['core_confidence', '核心参数置信度'],
  ['feature_confidence', '配置置信度'],
]

const FEATURE_LABELS: Record<string, string> = {
  airbags: '安全气囊数',
  esp: 'ESP车身稳定',
  aeb: 'AEB主动刹车',
  fcw: '前碰撞预警',
  ldw: '车道偏离预警',
  lka: '车道保持辅助',
  lane_centering: '车道居中',
  bsd: '并线辅助/盲区监测',
  dow: '开门预警',
  acc: 'ACC自适应巡航',
  cruise: '巡航类型',
  camera_360: '360°全景影像',
  transparent_chassis: '透明底盘/540°影像',
  front_radar: '前驻车雷达',
  rear_radar: '后驻车雷达',
  auto_park: '自动泊车',
  remote_park: '遥控泊车',
  power_driver_seat: '主驾电动座椅',
  power_passenger_seat: '副驾电动座椅',
  seat_heating: '前排座椅加热',
  seat_ventilation: '前排座椅通风',
  panoramic_sunroof: '全景天窗',
  power_tailgate: '电动尾门',
  keyless_entry: '无钥匙进入',
  remote_start: '远程启动',
  rear_ac_vents: '后排出风口',
  dual_zone_climate: '双区/多区空调',
  leather_seats: '真皮座椅',
  full_lcd_cluster: '全液晶仪表',
  screen_inch: '中控屏尺寸(英寸)',
  carplay: 'Apple CarPlay',
  carlife: '百度 CarLife',
  hicar: 'Huawei HiCar',
  phone_link: '手机互联',
  android_auto: 'Android Auto',
  wireless_charge: '手机无线充电',
  voice_control: '语音控制',
  ota: 'OTA升级',
  hud: 'HUD抬头显示',
  chip_8155: '高通8155芯片',
}

const FEATURE_ORDER = Object.keys(FEATURE_LABELS)
const listingBySku = new Map<string, Listing>()
let decorateQueued = false

function esc(value: unknown): string {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

function present(value: unknown): boolean {
  return value !== undefined && value !== null && value !== ''
}

function valueClass(value: unknown): string {
  if (value === true) return 'yes'
  if (value === false) return 'no'
  if (!present(value)) return 'unknown'
  return ''
}

function displayValue(value: unknown): string {
  if (value === true) return '有'
  if (value === false) return '无'
  if (!present(value)) return '未知'
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : String(Math.round(value * 1000) / 1000)
  if (Array.isArray(value)) return value.length ? value.map(displayValue).join('；') : '无'
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
  return String(value)
}

function rowHtml(label: string, value: unknown): string {
  return `<div class="config-kv"><span class="config-k">${esc(label)}</span><span class="config-v ${valueClass(value)}">${esc(displayValue(value))}</span></div>`
}

function rowsHtml(specs: Record<string, unknown>, rows: Row[]): string {
  return rows.map(([key, label]) => rowHtml(label, specs[key])).join('')
}

function sectionHtml(title: string, body: string): string {
  return `<section class="config-inspector-section"><h4>${esc(title)}</h4><div class="config-kv-grid">${body}</div></section>`
}

function featureHtml(specs: Record<string, unknown>): string {
  const features = (specs.features && typeof specs.features === 'object' && !Array.isArray(specs.features))
    ? specs.features as Record<string, unknown>
    : {}

  const known = FEATURE_ORDER.map((key) => rowHtml(FEATURE_LABELS[key], features[key]))
  const extras = Object.entries(features)
    .filter(([key]) => !FEATURE_LABELS[key])
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, value]) => rowHtml(key, value))
  return [...known, ...extras].join('')
}

function verificationIssuesHtml(item: Listing, specs: Record<string, unknown>): string {
  const specIssues = Array.isArray(specs.verification_issues) ? specs.verification_issues : []
  const dataIssues = Array.isArray(item.data_issues) ? item.data_issues : []
  const all = [
    ...specIssues.map((x) => String(x)),
    ...dataIssues.map((x) => String(x.message || x.code || '数据异常')),
  ].filter(Boolean)
  const unique = [...new Set(all)]
  if (!unique.length) return ''
  return `<section class="config-inspector-section config-problems"><h4>待核对 / 已知问题</h4><ul>${unique.map((x) => `<li>${esc(x)}</li>`).join('')}</ul></section>`
}

function sourceUrl(value: unknown): string | null {
  if (typeof value !== 'string') return null
  try {
    const u = new URL(value)
    if (u.protocol === 'http:' || u.protocol === 'https:') return u.href
  } catch {}
  return null
}

function sourcesHtml(specs: Record<string, unknown>): string {
  const links: { url: string; label: string }[] = []
  const seen = new Set<string>()
  const add = (urlValue: unknown, label: string) => {
    const url = sourceUrl(urlValue)
    if (!url || seen.has(url)) return
    seen.add(url)
    links.push({ url, label })
  }

  add(specs.source_url, '配置来源')
  const sources = Array.isArray(specs.verification_sources) ? specs.verification_sources : []
  for (const source of sources) {
    if (!source || typeof source !== 'object') continue
    const s = source as Record<string, unknown>
    const label = String(s.source_type || s.title || s.name || `核验来源 ${links.length + 1}`)
    add(s.url, label)
  }
  if (!links.length) return ''
  return `<section class="config-inspector-section"><h4>核验来源</h4><div class="config-source-list">${links.map((x) => `<a href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">${esc(x.label)} ↗</a>`).join('')}</div></section>`
}

function rawHtml(specs: Record<string, unknown>): string {
  return `<details class="config-raw"><summary>查看原始配置 JSON</summary><pre>${esc(JSON.stringify(specs, null, 2))}</pre></details>`
}

function inspectorHtml(item: Listing): string {
  const specs = (item.specs || item.detailed_config || {}) as Record<string, unknown>
  const coverage = typeof item.config_coverage === 'number' ? item.config_coverage : null
  const verified = specs.verified === true && specs.match_level === 'exact_trim'
  const summarySuffix = verified
    ? ` · ${coverage != null ? `覆盖率 ${Math.round(coverage * 100)}%` : '精确核验'}`
    : ' · 查看已有字段与缺失项'

  const verifyBody = [
    rowsHtml(specs, VERIFY_ROWS),
    rowHtml('评分资格', item.score_eligible === true ? true : item.score_eligible === false ? false : null),
    rowHtml('配置覆盖率', coverage == null ? null : `${Math.round(coverage * 100)}%`),
  ].join('')

  return `
    <details class="config-inspector" data-config-inspector="1">
      <summary>查看配置详情${esc(summarySuffix)}</summary>
      <div class="config-inspector-body">
        ${sectionHtml('基础参数 / 空间', rowsHtml(specs, CORE_ROWS))}
        ${sectionHtml('动力 / 能耗', rowsHtml(specs, ENERGY_ROWS))}
        ${sectionHtml('配置项（有 / 无 / 未知）', featureHtml(specs))}
        ${sectionHtml('核验状态', verifyBody)}
        ${verificationIssuesHtml(item, specs)}
        ${sourcesHtml(specs)}
        ${rawHtml(specs)}
      </div>
    </details>`
}

function skuFromCard(card: Element): string | null {
  const img = card.querySelector<HTMLImageElement>('.cover img')
  const imgMatch = img?.getAttribute('src')?.match(/\/images\/(\d+)\.jpg/i)
  if (imgMatch?.[1]) return imgMatch[1]

  const detail = card.querySelector<HTMLAnchorElement>('a.btn-link[href*="sku_id="]')
  if (detail?.href) {
    try {
      return new URL(detail.href).searchParams.get('sku_id')
    } catch {}
  }
  return null
}

function decorateCards(): void {
  document.querySelectorAll<HTMLElement>('.card').forEach((card) => {
    if (card.querySelector('[data-config-inspector="1"]')) return
    const sku = skuFromCard(card)
    if (!sku) return
    const item = listingBySku.get(sku)
    if (!item) return
    const specsBox = card.querySelector<HTMLElement>('.specs')
    if (!specsBox) return
    specsBox.insertAdjacentHTML('beforeend', inspectorHtml(item))
  })
}

function queueDecorate(): void {
  if (decorateQueued) return
  decorateQueued = true
  requestAnimationFrame(() => {
    decorateQueued = false
    decorateCards()
  })
}

async function loadListings(): Promise<void> {
  try {
    const [rankedRes, issuesRes] = await Promise.all([
      fetch('/data/listings-ranked.json'),
      fetch('/data/data-issues.json'),
    ])
    const ranked: Listing[] = rankedRes.ok ? await rankedRes.json() : []
    const issues: Listing[] = issuesRes.ok ? await issuesRes.json() : []
    for (const item of [...ranked, ...issues]) {
      if (item.sku != null) listingBySku.set(String(item.sku), item)
    }
    queueDecorate()
  } catch (error) {
    console.warn('[config-inspector] failed to load listing data', error)
  }
}

const observer = new MutationObserver(queueDecorate)
observer.observe(document.documentElement, { childList: true, subtree: true })
void loadListings()
