export type RiskLevel = 'low' | 'medium' | 'high';
export type DataSource = 'osm' | 'mos_ru';
export type ServiceMode = 'mocks' | 'data';

export interface HealthResponse {
  status: 'ok';
  mode: ServiceMode;
  data_version: string;
}

export interface CityInfo {
  code: string;
  name: string;
  center: [number, number];
  zoom: number;
}

export interface NicheInfo {
  code: string;
  name: string;
}

export interface HexScore {
  h3: string;
  revenue_p50: number;
  payback_months_p50: number | null;
  risk_level: RiskLevel;
  competitors_500m: number;
}

export interface HexesResponse {
  city: string;
  niche: string;
  data_version: string;
  items: HexScore[];
}

export interface Competitor {
  name: string;
  brand: string | null;
  lat: number;
  lon: number;
  source: DataSource;
}

export interface AddressMatch {
  address: string;
  lat: number;
  lon: number;
}

export interface ReportRequest {
  city: string;
  niche: string;
  lat: number;
  lon: number;
  area_m2?: number | null;
  rent_rub_m2_month?: number | null;
}

export interface ReportLocation {
  lat: number;
  lon: number;
  h3: string;
  address: string | null;
}

export interface MoneyRange {
  p10: number;
  p50: number;
  p90: number;
}

export interface MonthlyCosts {
  rent: number;
  payroll: number;
  cogs: number;
  taxes: number;
  other: number;
  total: number;
}

export interface Factor {
  code: string;
  name: string;
  value: number;
  unit: string;
  effect_rub: number;
}

export interface NearbyCompetitor {
  name: string;
  lat: number;
  lon: number;
  distance_m: number;
}

export interface Assumption {
  name: string;
  value: number | string;
  unit: string;
  source: string | null;
}

export interface LocationReport {
  city: string;
  niche: string;
  location: ReportLocation;
  revenue_month: MoneyRange;
  costs_month: MonthlyCosts;
  profit_month_p50: number;
  capex_rub_p50: number;
  payback_months_p50: number | null;
  risk_level: RiskLevel;
  factors: Factor[];
  competitors: NearbyCompetitor[];
  assumptions: Assumption[];
  data_version: string;
}
