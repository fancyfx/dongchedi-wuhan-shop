import type { Listing } from './types'

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
  if (tier === 'AT') return 'gb-at'
  if (tier === 'CVT') return 'gb-cvt'
  if (tier === 'WET_DCT') return 'gb-dct'
  return 'gb-other'
}

export function scoreBarsHtml(item: Listing, compact = false): string {
  const ss = item.sort_scores
  const dims: { label: string; val: number | null | undefined; cls: string }[] = [
    { label: '三大件', val: ss?.powertrain_score, cls: 'dim-pt' },
    { label: '配置', val: ss?.config_score, cls: 'dim-cfg' },
    { label: '性价比', val: ss?.value_price_score ?? ss?.price_score, cls: 'dim-val' },
    { label: '车况', val: ss?.condition_score, cls: 'dim-cond' },
    { label: '空间', val: ss?.space_score, cls: 'dim-sp' },
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
    ['主被动气囊', (sp.airbags ?? feat.airbags) != null ? `${sp.airbags ?? feat.airbags} 气囊` : '未明示', (Number(sp.airbags ?? feat.airbags ?? 0) >= 6 ? 'yes' : 'no')],
    ['AEB 主动刹车', boolMark(feat.aeb), boolCls(feat.aeb)],
    ['自适应巡航', feat.cruise ? String(feat.cruise) : boolMark(feat.acc), feat.acc ? 'yes' : 'no'],
    ['车道保持/居中', boolMark(Boolean(feat.lka || feat.lane_centering)), boolCls(Boolean(feat.lka || feat.lane_centering))],
    ['并线/开门预警', boolMark(Boolean(feat.bsd || feat.dow)), boolCls(Boolean(feat.bsd || feat.dow))],
    ['360 全景影像', boolMark(feat.camera_360), boolCls(feat.camera_360)],
    ['前排座椅加热', boolMark(feat.seat_heating), boolCls(feat.seat_heating)],
    ['前排座椅通风', boolMark(feat.seat_ventilation), boolCls(feat.seat_ventilation)],
    ['电动座椅调节', feat.power_driver_seat ? (feat.power_passenger_seat ? '主/副驾双电调' : '主驾电调') : '手动调节', feat.power_driver_seat ? 'yes' : 'no'],
    ['CarPlay/互联', feat.carplay ? '● CarPlay' : boolMark(feat.phone_link), feat.carplay || feat.phone_link ? 'yes' : 'no'],
    ['全景天窗', boolMark(feat.panoramic_sunroof), boolCls(feat.panoramic_sunroof)],
    ['电动尾门', boolMark(feat.power_tailgate), boolCls(feat.power_tailgate)],
  ]

  const yearStr = item.plate_year ? `${item.plate_year}年上牌` : item.year || ''
  const mileStr = item.mileage_wan != null ? `${item.mileage_wan.toFixed(2)}万公里` : ''

  return `
    <div class="drawer-hero">
      <div class="drawer-cover">${coverImgHtml(item)}</div>
      <div class="drawer-head-info">
        <div class="drawer-badges">
          <span class="rank-pill">严选 #${String(item.rank ?? '—').padStart(2, '0')}</span>
          ${p?.archetype_badge ? `<span class="arch-pill">${esc(p.archetype_badge)}</span>` : ''}
          ${p?.gearbox_label ? `<span class="gb-pill ${gearboxClass(p.gearbox_tier)}">${esc(p.gearbox_label)}</span>` : ''}
        </div>
        <h2>${esc(item.title)}</h2>
        <div class="drawer-sub">${esc([item.manufacturer, yearStr, mileStr, item.city || '武汉'].filter(Boolean).join(' · '))} · SKU ${esc(item.sku)}</div>
        <div class="drawer-price-strip">
          <div class="dp-main">
            <span class="dp-label">全款现金价</span>
            <span class="dp-num">${Number(item.price).toFixed(2)}<small>万</small></span>
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
      label: '全款现金价',
      render: (x) => `<strong class="cmp-price">${Number(x.price).toFixed(2)}万</strong>${x.v3_profile?.discount_fold ? ` <small>(${x.v3_profile.discount_fold}折 / 原${x.v3_profile.msrp_wan}万)</small>` : ''}`,
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
            <th>对比维度</th>
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
              <th>${esc(r.label)}</th>
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
        专为<strong>“平时不开、仅节假日偶尔开、追求高配低价且好维护”</strong>的买手需求重写。彻底剔除旧版 15% 油耗权重与 5% SUV 偏见，确保每台入选车都经得起久停和长途考验。
      </div>
      <div class="method-grid">
        <div class="method-card veto">
          <h4>一、四大铁律一票否决</h4>
          <ul>
            <li><strong>否决纯电/插混（BEV/PHEV）</strong>：长停易小电瓶馈电，过户无三电质保，商险更贵，低频开省不下油钱。</li>
            <li><strong>否决三缸发动机</strong>：剔除 1.0T/1.2T/1.5T 三缸机型及湿式正时皮带通病车，锁死四缸机。</li>
            <li><strong>否决干式双离合</strong>：剔除 DQ200 等干式双离合，防久停粘连生锈及高速堵车过热顿挫。</li>
            <li><strong>实时清理已售与隐藏锁单</strong>：每日对账接口 <code>product_status</code>，已售清出、锁单隐藏不出榜。</li>
          </ul>
        </div>
        <div class="method-card weights">
          <h4>二、V3 五维评分权重（满分 100）</h4>
          <ul>
            <li><strong>三大件与维保友好度（30%）</strong>：爱信/通用 AT & 丰田带起步齿轮 CVT 优先；自吸多点电喷耐静置加分；豪华高零整比与退市品牌降权。</li>
            <li><strong>节假日刚需配置（24%）</strong>：重点权重给 6 气囊、AEB、全速 ACC、车道保持、360 全景、座椅加热、电动座椅、CarPlay。</li>
            <li><strong>高折旧性价比（22%）</strong>：55% 看残值折扣率（现价÷指导价），45% 看绝对全款现金价。</li>
            <li><strong>车况与里程车龄（18%）</strong>：实表里程权重高于上牌年，优先准新低里程车源。</li>
            <li><strong>空间实用性（6%）</strong>：按轴距稳健计分，保留紧凑高配与两厢精品车的竞争力。</li>
          </ul>
        </div>
      </div>
      <div class="method-tips">
        <h4>三、低频用车·到店提车必做三步</h4>
        <ol>
          <li><strong>现场测 12V 电瓶 SOH</strong>：要求门店实测蓄电池寿命，低于 60% 直接谈免费换新电瓶。</li>
          <li><strong>排查外接常电设备</strong>：拆掉前车主私接的 24 小时停车监控记录仪（改接 ACC 熄火断电），随车备一个百元级锂电搭电宝。</li>
          <li><strong>保养与胎压策略</strong>：冷胎气压打到 2.5–2.6 bar 防久停平点；用全合成机油按 1 年或 1 万公里一保即可。</li>
        </ol>
      </div>
    </div>
  `
}
