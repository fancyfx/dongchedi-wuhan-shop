export type DataIssue = {
  code: string
  message: string
  severity?: string
  field?: string
}

export type SortScores = {
  score_version?: string
  total_score?: number | null
  powertrain_score?: number
  config_score?: number | null
  value_price_score?: number
  condition_score?: number
  space_score?: number
  price_score?: number
  operating_cost_score?: number
  age_score?: number
  mileage_score?: number
  body_preference_score?: number
  data_quality_score?: number
  config_norm?: number | null
  space_norm?: number | null
  fuel_norm?: number | null
  config_proxy?: number | null
  is_suv?: boolean
  price?: number
  effective_price_wan?: number
  msrp_wan?: number | null
  discount_fold?: number | null
}

export type OwnerReviews = {
  summary?: string
  pros?: string[]
  cons?: string[]
  drawbacks?: string[]
  sources?: { title: string; url: string }[]
  found?: boolean
  cons_note?: string | null
}

export type Specs = {
  specs_found?: boolean
  verified?: boolean
  match_level?: string
  powertrain?: string
  powertrain_type?: string
  engine?: string
  engine_model?: string
  cylinders?: number | null
  intake?: string
  fuel_injection?: string
  horsepower_ps?: number | null
  torque_nm?: number | null
  transmission?: string
  transmission_type?: string
  transmission_short?: string
  rear_suspension?: string
  drive_type?: string
  fuel_grade?: string
  length_mm?: number | null
  width_mm?: number | null
  height_mm?: number | null
  wheelbase_mm?: number | null
  seats?: number | null
  body_type?: string
  msrp_wan?: number | null
  live_spec_id?: number | string
  airbags?: number | null
  screen_inch?: number | null
  features?: Record<string, unknown>
}

export type V3Profile = {
  archetype_badge: string
  msrp_wan: number | null
  discount_fold: number | null
  saved_wan: number | null
  powertrain_summary: string
  gearbox_tier: 'AT' | 'CVT' | 'WET_DCT' | 'MT' | 'OTHER' | string
  gearbox_label: string
  engine_summary: string
  intake: string
  fuel_injection: string
  rear_suspension: string
  rear_suspension_short: string
  drive_type: string
  drive_short: string
  fuel_grade: string
  feature_highlights: string[]
  recommend_reason: string
  inspection_checklist: string[]
  maintenance_estimate: string
  reliability_notes: string[]
}

export type Listing = {
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
  cover?: string
  detail_url: string
  shop_id?: string
  shop_name?: string
  shop_short_name?: string
  is_local_wuhan?: boolean
  logistics_fee_yuan?: number
  logistics_fee_source?: string
  plate_service_fee_yuan?: number
  plate_fee_diff_yuan?: number
  landed_extra_yuan?: number
  landed_extra_wan?: number
  landed_price_wan?: number
  delivery_eta?: string
  series?: string
  brand?: string
  manufacturer?: string
  sale_status?: string
  total_score?: number | null
  evaluation?: string
  rank?: number | null
  wuhan_rank?: number | null
  national_rank?: number | null
  board_scope?: BoardKey | string
  sort_scores?: SortScores
  owner_reviews?: OwnerReviews
  specs?: Specs
  detailed_config?: Specs
  v3_profile?: V3Profile | null
  score_version?: string
  cash_price_wan?: number
  effective_price_wan?: number
  needs_cash_quote?: boolean
  condition_gate?: string
  recommendation_gate?: string
  score_warnings?: string[]
  score_eligible?: boolean
  data_issues?: DataIssue[]
  config_coverage?: number
}

export type ShopSummary = {
  shop_id: string
  name: string
  short_name: string
  city: string
  kind?: string
  is_local?: boolean
  logistics_fee_yuan?: number
  inventory_count?: number
  top_count?: number
}

export type BoardKey = 'wuhan' | 'national'

export type BoardMeta = {
  key?: BoardKey
  label?: string
  subtitle?: string
  data_file?: string
  inventory_count?: number
  on_sale_count?: number
  reserved_count?: number
  vetoed_count?: number
  eligible_count?: number
  ranked_count?: number
  display_limit?: number
  display_score_floor?: number | null
}

export type Meta = {
  shop_name?: string
  shop_id?: string
  buyer_city?: string
  shop_scope?: string
  shops?: ShopSummary[]
  boards?: Partial<Record<BoardKey, BoardMeta>>
  wuhan_ranked_count?: number
  wuhan_eligible_count?: number
  wuhan_display_score_floor?: number | null
  pricing_policy?: string
  captured_at?: string
  ranked_at?: string
  ranked_count?: number
  library_scored_count?: number
  below_display_count?: number
  data_issue_count?: number
  filtered_count?: number
  on_sale_count?: number
  reserved_count?: number
  vetoed_count?: number
  veto_breakdown?: {
    ev_phev?: number
    three_cyl?: number
    dry_dct?: number
  }
  display_limit?: number
  score_version?: string
  sort_weights?: Record<string, number>
  sort_formula?: string
  notes?: string
  filter_pipeline?: string
}

export type ShopScopeKey = 'all' | 'wuhan' | 'low_freight'
export type PresetKey = 'all' | 'wuhan' | 'at' | 'under5' | 'lowmile' | 'suv' | 'sedan_b' | 'l2'
export type SortKey = 'recommend' | 'price' | 'discount' | 'mileage' | 'config' | 'powertrain'
