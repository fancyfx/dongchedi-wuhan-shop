import type { Listing, ShopScopeKey, SortKey } from './types'

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

function logisticsSourceLabel(src?: string): string {
  if (src === 'local_wuhan') return '本地直提免运费'
  if (src === 'api') return '懂车帝官方实时运费'
  if (src === 'city_cache') return '同城物流标准运费'
  if (src === 'default_1000') return '基准估价(+1000元)'
  return '官方/基准物流费'
}

export function esc(s: unknown): string {
  return String(s ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
}

export function coverUrl(item: Listing): string {
  return `/images/${encodeURIComponent(item.sku)}.jpg`
}

export function coverImgHtml(item: Listing, cls = ''): string {
  const local = coverUrl(item)
  const fallback = item.cover ? esc(item.cover) : ''
  const onErr = fallback
    ? `if(!this.dataset.fb){this.dataset.fb='1';this.src='${fallback}';}else{this.style.display='none';this.nextElementSibling.style.display='grid';}`
    : `this.style.display='none';this.nextElementSibling.style.display='grid';`
  return `
    <img class="${cls}" src="${local}" alt="${esc(item.title)}" loading="lazy" onerror="${onErr}" />
    <div class="cover-placeholder" style="display:none">
      <span>暂无实拍图</span>
      <small>SKU ${esc(item.sku)}</small>
    </div>`
}

export function gearboxClass(tier?: string): string {
  if (tier === 'E_CVT') return 'gb-ecvt'
  if (tier === 'AT') return 'gb-at'
  if (tier === 'CVT') return 'gb-cvt'
  if (tier === 'WET_DCT') return 'gb-dct'
  return 'gb-other'
}

export function miniMetersHtml(item: Listing): string {
  const ss = item.sort_scores
  const dims: { label: string; val: number | null | undefined; cls: string }[] = [
    { label: '配置', val: ss?.config_score, cls: 'dim-cfg' },
    { label: '空间', val: ss?.space_score, cls: 'dim-sp' },
    { label: '三大件', val: ss?.powertrain_score, cls: 'dim-pt' },
    { label: '车况', val: ss?.condition_score, cls: 'dim-cond' },
    { label: '价格值', val: ss?.value_price_score ?? ss?.price_score, cls: 'dim-val' },
  ]
  return `
    <div class="mini-meters">
      ${dims
        .map((d) => {
          const v = typeof d.val === 'number' && Number.isFinite(d.val) ? Math.max(0, Math.min(100, d.val)) : 0
          return `
            <div class="mm-cell">
              <span class="mm-lbl">${d.label}</span>
              <strong class="mm-num">${typeof d.val === 'number' ? d.val.toFixed(0) : '—'}</strong>
              <span class="mm-track"><span class="mm-fill ${d.cls}" style="width:${v.toFixed(0)}%"></span></span>
            </div>`
        })
        .join('')}
    </div>`
}

export function scoreBarsHtml(item: Listing, compact = false): string {
  const ss = item.sort_scores
  const dims: { label: string; val: number | null | undefined; cls: string }[] = [
    { label: '现代配置', val: ss?.config_score, cls: 'dim-cfg' },
    { label: 'SUV空间', val: ss?.space_score, cls: 'dim-sp' },
    { label: '三大件', val: ss?.powertrain_score, cls: 'dim-pt' },
    { label: '里程车况', val: ss?.condition_score, cls: 'dim-cond' },
    { label: '到汉价格', val: ss?.value_price_score ?? ss?.price_score, cls: 'dim-val' },
  ]
  return `
    <div class="dim-bars ${compact ? 'compact' : ''}">
      ${dims
        .map((d) => {
          const v = typeof d.val === 'number' && Number.isFinite(d.val) ? Math.max(0, Math.min(100, d.val)) : 0
          return `
            <div class="dim-row">
              <span class="dim-lbl">${d.label}</span>
              <span class="dim-track"><span class="dim-fill ${d.cls}" style="width:${v.toFixed(0)}%"></span></span>
              <span class="dim-num">${typeof d.val === 'number' ? d.val.toFixed(0) : '—'}</span>
            </div>`
        })
        .join('')}
    </div>`
}

export function renderFilterSheetBody(opts: {
  q: string
  priceMax: string
  sort: SortKey
  shopScope: ShopScopeKey
  city: string
  cityCounts: [string, number][]
  shownCount: number
  totalCount: number
}): string {
  const hotKeywords = ['领克03', '探界者', '君威', '迈锐宝XL', '奕泽', '伊兰特', '传祺GS4', '宝马']
  const scopeOptions: [ShopScopeKey, string][] = [
    ['all', '全部7城直营'],
    ['wuhan', '仅看武汉本地'],
    ['low_freight', '低运费≤1000元(汉·长·合)'],
  ]
  const budgetOptions: [string, string][] = [
    ['', '不限预算'],
    ['4', '≤ 4万'],
    ['4.5', '≤ 4.5万'],
    ['5', '≤ 5万'],
    ['5.5', '≤ 5.5万'],
  ]
  const sortOptions: [SortKey, string][] = [
    ['recommend', 'V3 综合严选'],
    ['powertrain', '三大件最稳'],
    ['config', '配置最丰富'],
    ['discount', '折旧最狠(折数)'],
    ['price', '到汉总价最低'],
    ['mileage', '最低表显里程'],
  ]

  return `
    <div class="filter-sheet-body">
      <div class="fs-group">
        <div class="fs-label">直营门店范围（含到汉运费口径）</div>
        <div class="fs-scope-row">
          ${scopeOptions
            .map(
              ([val, lbl]) =>
                `<button type="button" class="fs-sort-btn ${opts.shopScope === val ? 'active' : ''}" data-sheet-scope="${val}">${esc(lbl)}</button>`,
            )
            .join('')}
        </div>
        ${
          opts.cityCounts.length > 1
            ? `<div class="fs-chips">
          <button type="button" class="fs-chip ${opts.city === '' ? 'active' : ''}" data-sheet-city="">全部城市</button>
          ${opts.cityCounts
            .map(
              ([c, cnt]) =>
                `<button type="button" class="fs-chip ${opts.city === c ? 'active' : ''}" data-sheet-city="${esc(c)}">${esc(c)} (${cnt})</button>`,
            )
            .join('')}
        </div>`
            : ''
        }
      </div>

      <div class="fs-group">
        <label class="fs-label" for="sheet-q">搜索车型 / 城市 / 品牌 / SKU</label>
        <input id="sheet-q" class="fs-input" type="search" placeholder="输入关键词，如 君威、合肥、探界者…" value="${esc(opts.q)}" />
        <div class="fs-chips">
          ${hotKeywords
            .map(
              (kw) =>
                `<button type="button" class="fs-chip ${opts.q.trim() === kw ? 'active' : ''}" data-sheet-kw="${esc(kw)}">${esc(kw)}</button>`,
            )
            .join('')}
        </div>
      </div>

      <div class="fs-group">
        <label class="fs-label" for="sheet-pmax">到汉可比总价上限（含物流+上牌差，万）</label>
        <div class="fs-chips">
          ${budgetOptions
            .map(
              ([val, lbl]) =>
                `<button type="button" class="fs-chip ${opts.priceMax === val ? 'active' : ''}" data-sheet-pmax="${esc(val)}">${esc(lbl)}</button>`,
            )
            .join('')}
        </div>
        <input id="sheet-pmax" class="fs-input fs-input-num" type="number" inputmode="decimal" min="0" max="6" step="0.1" placeholder="自定义上限，例如 4.8" value="${esc(opts.priceMax)}" />
      </div>

      <div class="fs-group">
        <div class="fs-label">排序方式</div>
        <div class="fs-sort-grid">
          ${sortOptions
            .map(
              ([val, lbl]) =>
                `<button type="button" class="fs-sort-btn ${opts.sort === val ? 'active' : ''}" data-sheet-sort="${val}">${esc(lbl)}</button>`,
            )
            .join('')}
        </div>
      </div>

      <div class="fs-footer">
        <button type="button" class="btn-secondary" id="btn-sheet-reset">重置条件</button>
        <button type="button" class="btn-primary" id="btn-sheet-apply">查看 ${opts.shownCount} / ${opts.totalCount} 台严选</button>
      </div>
    </div>`
}

export function renderDetailDrawerBody(item: Listing): string {
  const p = item.v3_profile
  const sp = item.specs || item.detailed_config || {}
  const feat = (sp.features || {}) as Record<string, unknown>
  const or = item.owner_reviews
  const total = item.total_score ?? item.sort_scores?.total_score
  const cons = or?.cons || or?.drawbacks || []
  const pros = or?.pros || []
  const sources = or?.sources || []

  const boolMark = (v: unknown) => (v === true ? '● 标配' : v === false ? '— 无' : '未明示')
  const boolCls = (v: unknown) => (v === true ? 'yes' : 'no')

  const featMatrix: [string, string, string][] = [
    [
      '主被动气囊',
      (sp.airbags ?? feat.airbags) != null ? `${sp.airbags ?? feat.airbags} 气囊` : '未明示',
      Number(sp.airbags ?? feat.airbags ?? 0) >= 6 ? 'yes' : 'no',
    ],
    ['AEB 主动刹车', boolMark(feat.aeb), boolCls(feat.aeb)],
    ['自适应巡航', feat.cruise ? String(feat.cruise) : boolMark(feat.acc), feat.acc ? 'yes' : 'no'],
    ['车道保持/居中', boolMark(Boolean(feat.lka || feat.lane_centering)), boolCls(Boolean(feat.lka || feat.lane_centering))],
    ['并线/开门预警', boolMark(Boolean(feat.bsd || feat.dow)), boolCls(Boolean(feat.bsd || feat.dow))],
    ['360 全景影像', boolMark(feat.camera_360), boolCls(feat.camera_360)],
    ['前排座椅加热', boolMark(feat.seat_heating), boolCls(feat.seat_heating)],
    ['前排座椅通风', boolMark(feat.seat_ventilation), boolCls(feat.seat_ventilation)],
    [
      '电动座椅调节',
      feat.power_driver_seat ? (feat.power_passenger_seat ? '主/副驾双电调' : '主驾电调') : '手动调节',
      feat.power_driver_seat ? 'yes' : 'no',
    ],
    ['CarPlay/互联', feat.carplay ? '● CarPlay' : boolMark(feat.phone_link), feat.carplay || feat.phone_link ? 'yes' : 'no'],
    ['全景天窗', boolMark(feat.panoramic_sunroof), boolCls(feat.panoramic_sunroof)],
    ['电动尾门', boolMark(feat.power_tailgate), boolCls(feat.power_tailgate)],
  ]

  const yearStr = item.plate_year ? `${item.plate_year}年上牌` : item.year || ''
  const mileStr = item.mileage_wan != null ? `${item.mileage_wan.toFixed(2)}万公里` : ''
  const local = isLocalWuhan(item)
  const effWan = landedPrice(item)
  const bareWan = cashPrice(item)
  const logiYuan = Math.max(0, Math.round(item.logistics_fee_yuan ?? 0))
  const plateYuan = Math.round(item.plate_service_fee_yuan ?? (local ? 500 : 1000))
  const pdiffYuan = Math.max(0, Math.round(item.plate_fee_diff_yuan ?? 0))
  const shopDisplay = item.shop_name || item.shop_short_name || (local ? '懂车帝汽车商城•武汉店' : `${item.city || ''}直营店`)

  return `
    <div class="drawer-hero">
      <div class="drawer-cover">${coverImgHtml(item)}</div>
      <div class="drawer-head-info">
        <div class="drawer-badges">
          <span class="rank-pill">严选 #${String(item.rank ?? '—').padStart(2, '0')}</span>
          <span class="origin-badge ${local ? 'local' : 'remote'}">${esc(item.shop_short_name || item.city || '武汉店')}</span>
          ${p?.archetype_badge ? `<span class="arch-pill">${esc(p.archetype_badge)}</span>` : ''}
          ${p?.gearbox_label ? `<span class="gb-pill ${gearboxClass(p.gearbox_tier)}">${esc(p.gearbox_label)}</span>` : ''}
        </div>
        <h2>${esc(item.title)}</h2>
        <div class="drawer-sub">${esc([item.manufacturer, yearStr, mileStr, item.city || '武汉'].filter(Boolean).join(' · '))} · SKU ${esc(item.sku)}</div>
        <div class="drawer-price-strip">
          <div class="dp-main">
            <span class="dp-label">${local ? '全款现金价（本地直提）' : '到汉可比总价（含物流+上牌差）'}</span>
            <span class="dp-num">${effWan.toFixed(2)}<small>万</small></span>
          </div>
          ${p?.msrp_wan ? `
            <div class="dp-meta">
              <div>原指导价 <del>${p.msrp_wan.toFixed(2)}万</del></div>
              <div><b>${p.discount_fold}折</b> · 比新车省 <b>${p.saved_wan?.toFixed(2)}万</b></div>
            </div>` : ''}
          <div class="dp-score">
            <span>综合严选分</span>
            <strong>${total != null ? total.toFixed(1) : '—'}</strong>
          </div>
        </div>
      </div>
    </div>

    <div class="landed-cost-box">
      <div class="lc-item"><span>车源门店</span><strong>${esc(shopDisplay)}</strong></div>
      <div class="lc-item"><span>裸车全款价</span><strong>${bareWan.toFixed(2)} 万</strong></div>
      <div class="lc-item"><span>到汉物流费</span><strong>${local ? '0 元（免物流）' : `${logiYuan} 元`}${item.delivery_eta ? ` · ${esc(item.delivery_eta)}` : ''}</strong><small>${esc(logisticsSourceLabel(item.logistics_fee_source))}</small></div>
      <div class="lc-item"><span>上牌服务费</span><strong>${plateYuan} 元${pdiffYuan > 0 ? `（含异地差+${pdiffYuan}）` : '（本地标准）'}</strong></div>
    </div>

    ${p?.recommend_reason ? `<div class="drawer-callout"><strong>买手推荐理由：</strong>${esc(p.recommend_reason)}</div>` : ''}

    <section class="drawer-sec">
      <h3>五维严选评分拆解</h3>
      ${scoreBarsHtml(item)}
    </section>

    <section class="drawer-sec">
      <h3>三大件、底盘与年养车成本</h3>
      <div class="spec-kv-grid">
        <div><span>发动机</span><strong>${esc(p?.engine_summary || sp.engine || '—')} ${sp.engine_model ? `(${esc(sp.engine_model)})` : ''}</strong></div>
        <div><span>供油/进气</span><strong>${esc([p?.intake, p?.fuel_injection].filter(Boolean).join(' · ') || '—')}</strong></div>
        <div><span>变速箱</span><strong>${esc(sp.transmission_type || p?.gearbox_label || sp.transmission || '—')}</strong></div>
        <div><span>后悬架/驱动</span><strong>${esc([p?.rear_suspension, p?.drive_type].filter(Boolean).join(' · ') || '—')}</strong></div>
        <div><span>轴距/车身</span><strong>${esc([sp.wheelbase_mm ? `${sp.wheelbase_mm}mm` : '', sp.body_type || ''].filter(Boolean).join(' · ') || '—')}</strong></div>
        <div><span>油号/年保养</span><strong>${esc([p?.fuel_grade, p?.maintenance_estimate].filter(Boolean).join(' · ') || '—')}</strong></div>
      </div>
      ${p?.reliability_notes?.length ? `<ul class="note-list">${p.reliability_notes.map((n) => `<li>${esc(n)}</li>`).join('')}</ul>` : ''}
    </section>

    <section class="drawer-sec">
      <h3>节假日高配核验（来自汽车之家实测树）</h3>
      <div class="feat-matrix">
        ${featMatrix.map(([k, v, cls]) => `<div class="fm-cell ${cls}"><span>${esc(k)}</span><b>${esc(v)}</b></div>`).join('')}
      </div>
    </section>

    ${p?.inspection_checklist?.length ? `
    <section class="drawer-sec inspect-box">
      <h3>到店看车 & 提车必检清单</h3>
      <ul>${p.inspection_checklist.map((c) => `<li>${esc(c)}</li>`).join('')}</ul>
    </section>` : ''}

    ${or && (or.summary || pros.length || cons.length) ? `
    <section class="drawer-sec">
      <h3>真实车主口碑与通病排查</h3>
      ${or.summary ? `<p class="review-text">${esc(or.summary)}</p>` : ''}
      ${pros.length ? `<div class="review-pros"><strong>车主好评：</strong>${esc(pros.join('；'))}</div>` : ''}
      ${cons.length ? `<div class="review-cons"><strong>高频槽点 / 通病警示：</strong><ul>${cons.map((c) => `<li>${esc(c)}</li>`).join('')}</ul></div>` : ''}
      ${sources.length ? `<div class="review-links">参考来源：${sources.slice(0, 3).map((s) => `<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)}</a>`).join(' · ')}</div>` : ''}
    </section>` : ''}

    <div class="drawer-footer-actions">
      <a class="btn-secondary" href="?sku=${encodeURIComponent(item.sku)}">查看完整汽车之家参配</a>
      <a class="btn-primary" href="${esc(item.detail_url)}" target="_blank" rel="noopener noreferrer">打开懂车帝原车页 ↗</a>
    </div>
  `
}

export function renderCompareDrawerBody(items: Listing[]): string {
  if (!items.length) return '<div class="empty-state">请先在榜单卡片左下角勾选 2～3 台车进行对比。</div>'
  const cols = items.length
  const rows: { label: string; render: (x: Listing) => string }[] = [
    {
      label: '排名 / 定位',
      render: (x) => `<b>#${x.rank ?? '—'}</b> · ${esc(x.v3_profile?.archetype_badge || '严选')}`,
    },
    {
      label: '来源门店',
      render: (x) => {
        const local = isLocalWuhan(x)
        return `<span class="origin-badge ${local ? 'local' : 'remote'}">${esc(x.shop_short_name || x.city || '武汉店')}</span>`
      },
    },
    {
      label: '到汉可比价',
      render: (x) =>
        `<strong class="cmp-price">${landedPrice(x).toFixed(2)}万</strong>${x.v3_profile?.discount_fold ? ` <small>(${x.v3_profile.discount_fold}折 / 原${x.v3_profile.msrp_wan}万)</small>` : ''}`,
    },
    {
      label: '裸车+物流/上牌差',
      render: (x) => {
        const local = isLocalWuhan(x)
        if (local) return `${cashPrice(x).toFixed(2)}万（本地免物流）`
        const logi = Math.max(0, Math.round(x.logistics_fee_yuan ?? 0))
        const pdiff = Math.max(0, Math.round(x.plate_fee_diff_yuan ?? 0))
        return `裸车 ${cashPrice(x).toFixed(2)}万 + 物流${logi}元${pdiff > 0 ? ` + 上牌差${pdiff}元` : ''}`
      },
    },
    {
      label: '上牌 / 里程',
      render: (x) => `${x.plate_year || x.model_year || '—'}年 · ${x.mileage_wan != null ? `${x.mileage_wan.toFixed(2)}万km` : '—'}`,
    },
    {
      label: 'V3 综合分',
      render: (x) => `<strong class="cmp-score">${(x.total_score ?? 0).toFixed(1)}</strong>`,
    },
    {
      label: '分项得分',
      render: (x) => {
        const s = x.sort_scores
        return `三大件 ${s?.powertrain_score?.toFixed(0) ?? '—'} / 配置 ${s?.config_score?.toFixed(0) ?? '—'} / 性价比 ${s?.value_price_score?.toFixed(0) ?? '—'} / 车况 ${s?.condition_score?.toFixed(0) ?? '—'}`
      },
    },
    {
      label: '三大件总成',
      render: (x) => esc(x.v3_profile?.powertrain_summary || '—'),
    },
    {
      label: '预估年保养',
      render: (x) => esc(x.v3_profile?.maintenance_estimate || '—'),
    },
    {
      label: '核心高配',
      render: (x) => (x.v3_profile?.feature_highlights?.length ? esc(x.v3_profile.feature_highlights.join(' · ')) : '—'),
    },
    {
      label: '轴距 / 级别',
      render: (x) => {
        const sp = x.specs || {}
        return `${sp.wheelbase_mm ? `${sp.wheelbase_mm}mm` : '—'} · ${esc(sp.body_type || '—')}`
      },
    },
    {
      label: '验车首要关注',
      render: (x) => esc(x.v3_profile?.inspection_checklist?.[0] || '—'),
    },
  ]

  return `
    <div class="cmp-table-wrap">
      <table class="cmp-table" style="--cmp-cols:${cols}">
        <thead>
          <tr>
            <th class="sticky-col">对比维度</th>
            ${items
              .map(
                (x) => `
              <th>
                <div class="cmp-head">
                  <div class="cmp-thumb">${coverImgHtml(x)}</div>
                  <div class="cmp-title">${esc(x.title)}</div>
                  <button type="button" class="cmp-remove" data-cmp-remove="${esc(x.sku)}">移出</button>
                </div>
              </th>`,
              )
              .join('')}
          </tr>
        </thead>
        <tbody>
          ${rows
            .map(
              (r) => `
            <tr>
              <th class="sticky-col">${esc(r.label)}</th>
              ${items.map((x) => `<td>${r.render(x)}</td>`).join('')}
            </tr>`,
            )
            .join('')}
        </tbody>
      </table>
    </div>
  `
}

export function renderMethodologyModalBody(): string {
  return `
    <div class="method-body">
      <div class="method-lead">
        V3.2 针对<strong>“新世代高配大空间 SUV 主导 + 节假日低频省心开 + 轿车仅留极品备选”</strong>深度校准：重仓现代座舱与 360 视野，终结老合资靠虚高指导价折数刷榜，并对准新比亚迪 DM-i 等串并联电混开放有条件准入。
      </div>
      <div class="method-grid">
        <div class="method-card veto">
          <h4>一、风控铁律 &amp; 电混分层准入</h4>
          <ul>
            <li><strong>否决纯电（BEV）与老旧/准营运插混</strong>：无家充久停否决纯电及 2020 前双离合老插混；<strong>放行 2021+ 准新 E-CVT 串并联电混（如 DM-i）</strong>，但严卡车龄≤5.5年、里程≤7.5万km、年均≤3.2万km 防脱保与网约退役车。</li>
            <li><strong>否决三缸发动机</strong>：剔除 1.0T/1.2T/1.3T/1.5T 三缸机型，锁死四缸机。</li>
            <li><strong>否决干式双离合</strong>：剔除 DQ200 等干式双离合，防久停粘连与拥堵过热顿挫。</li>
            <li><strong>实时清理已售与隐藏锁单</strong>：每日对账接口 <code>product_status</code>，已售清出、锁单隐藏不出榜。</li>
          </ul>
        </div>
        <div class="method-card weights">
          <h4>二、V3.2 五维评分权重（满分 100）</h4>
          <ul>
            <li><strong>现代座舱与智驾配置（28%）</strong>：重仓 ≥12寸大屏+CarPlay、全液晶仪表、360全景、座椅加热/通风、双电调、L2 与 HUD，淘汰 8 寸小屏毛坯老车。</li>
            <li><strong>SUV 形态与立体空间（20%）</strong>：55% 看车身形态（紧凑/中型 SUV 满分，轿车降权作备选）+ 45% 看轴距/车宽/车高三维空间。</li>
            <li><strong>三大件可靠性（20%）</strong>：AT、丰田 CVT 与准新 E-CVT 电混第一梯队，一线成熟湿式双离合（长城/吉利/长安）客观缩小分差，冷门/老豪华重罚。</li>
            <li><strong>实表里程与代际车龄（18%）</strong>：严守 5–6 万km 大保养分水岭，陡峭化 6 年以上老车衰减，并对年均 >2.2万km 高频车扣分预警。</li>
            <li><strong>真实到汉价格值（14%）</strong>：80% 看全包到汉落地实价，封顶 3.2 折虚高指导价折扣加成。</li>
          </ul>
        </div>
      </div>
      <div class="method-tips">
        <h4>三、华中 7 城直营到汉比价口径 &amp; 提车必做</h4>
        <ol>
          <li><strong>统一到汉可比价</strong>：拉取武汉、长沙、合肥、南京、郑州、重庆、成都 7 家懂车帝官方直营店/仓，自动计入到汉物流费与异地上牌差额（500 元），严格卡死<strong>到汉总价 ≤ 6.0 万</strong>。</li>
          <li><strong>燃油车测 12V 电瓶 / 插混查三电与强制保电</strong>：油车现场测蓄电池 SOH（&lt;60% 要求换新）；DM-i 核查非营运与 8年/15万km 法定三电质保，久停前强制保电至 50%–60% SOC。</li>
          <li><strong>排查常电与大保养节点</strong>：拆掉私接 24 小时常电记录仪；接近 6 万公里车源重点检查变速箱油与四驱分动箱油状态。</li>
        </ol>
      </div>
    </div>
  `
}
