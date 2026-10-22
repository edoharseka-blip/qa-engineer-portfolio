export interface Listing {
  id: number; source: string; url: string; title: string; brand: string | null; model: string | null;
  generation: string | null; year: number | null; engine_volume: number | null; power_hp: number | null;
  fuel: string | null; transmission: string | null; drive: string | null; body: string | null;
  mileage: number | null; price: number; price_initial: number; region: string | null; city: string | null;
  seller_type: string | null; photos: string[]; posted_at: string | null; first_seen_at: string;
  notified_at: string | null; market_price: number | null; market_low: number | null; market_high: number | null;
  deviation_pct: number | null; confidence: number | null; comps_count: number | null; score: number | null;
  score_label: string | null; score_label_ru: string | null; warnings: string[]; liquidity: number | null;
  favorite: boolean; hidden: boolean; repost_count: number; is_demo: boolean;
}
export interface Detail extends Listing {
  description: string; vin: string | null; days_on_market: number;
  valuation: { tier: string; explain: Record<string, any> } | null;
  score_parts: Record<string, { value: number; note: string | null }> | null;
  price_history: { price: number; at: string }[]; comparables: Listing[];
  duplicates: { id: number; source: string; url: string; price: number }[];
}
export interface Filter {
  brands?: string[]; models?: string[]; generations?: string[]; year_min?: number; year_max?: number;
  price_min?: number; price_max?: number; mileage_max?: number; transmissions?: string[]; drives?: string[];
  fuels?: string[]; regions?: string[]; seller_types?: string[]; sources?: string[]; deviation_min?: number;
  posted_after?: string; q?: string; only_favorites?: boolean; score_min?: number;
  engine_volume_min?: number; engine_volume_max?: number;
}
export interface Profile {
  id: number; name: string; filters: Filter; notify: boolean; notify_min_score: number;
  notify_min_deviation: number; active: boolean;
}
export interface Meta {
  brands: string[]; models: Record<string, string[]>; generations: Record<string, string[]>;
  regions: string[]; all_regions: string[]; demo_mode: boolean; sources: string[];
}
