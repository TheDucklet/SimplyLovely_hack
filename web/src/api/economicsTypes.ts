import type { MoneyRange, Assumption } from './types';

export interface BusinessPlan {
  business_age_months?: number;
  capex_rub?: number | null;
  grace_months?: number | null;
  loan_amount_rub: number;
  payback_months?: number | null;
  product?: string | null;
  rate_annual?: number | null;
  revenue_month_rub: number;
  schedule?: 'annuity' | 'differentiated' | null;
  term_months?: number | null;
}

export interface CashBand {
  month: number;
  p10: number;
  p50: number;
  p90: number;
}

export interface CreditCheckReport {
  checks: Array<PlanCheck>;
  economics: EconomicsReport;
  loan_amount_rub: number;
  max_loan_rub: MoneyRange;
  probability_dscr_ok: number;
  summary: Array<string>;
  verdict: 'confirmed' | 'needs_review' | 'not_confirmed';
}

export interface CreditCheckRequest {
  economics: EconomicsRequest;
  plan: BusinessPlan;
}

export interface CreditProductInfo {
  code: string;
  grace_months: ProductCondition;
  max_amount_rub: ProductCondition;
  max_term_months: ProductCondition;
  min_business_age_months: ProductCondition;
  name: string;
  rate_annual: ProductCondition;
  schedule: 'annuity' | 'differentiated';
}

export interface CreditSummary {
  amount: number;
  dscr_first_year: OptionalRange;
  dscr_min: OptionalRange;
  dscr_monthly_min: OptionalRange;
  dscr_threshold: number;
  first_payment: number;
  grace_months: number;
  max_loan_rub: MoneyRange;
  months_below_threshold_p50: number;
  probability_dscr_below_threshold: number;
  product: string | null;
  product_name: string | null;
  rate_annual: number;
  schedule: 'annuity' | 'differentiated';
  term_months: number;
  total_interest: number;
}

export interface DemandSummary {
  district: string | null;
  h3: string | null;
  provider: string | null;
  revenue_steady_month: MoneyRange;
  source: 'geostart' | 'revenue' | 'traffic' | 'geoplatform';
}

export interface EconomicsMetrics {
  break_even_revenue_month: OptionalRange;
  break_even_units_per_day: OptionalRange;
  contribution_margin_per_unit: number;
  discounted_payback_months: OptionalRange;
  ebitda_margin_p50: number | null;
  first_profit_month: OptionalRange;
  irr_annual: OptionalRange;
  npv: MoneyRange;
  payback_months: OptionalRange;
  probability_loss: number;
  probability_no_payback: number;
  profit_steady_month: MoneyRange;
  risk_level: 'low' | 'medium' | 'high';
  safety_margin: OptionalRange;
  unit_name: string;
  unit_value_rub: number;
}

export interface EconomicsReport {
  assumptions: Array<Assumption>;
  cash_band: Array<CashBand>;
  city: string;
  credit: CreditSummary;
  demand: DemandSummary;
  discount_rate_annual: number;
  horizon_months: number;
  investment: InvestmentSummary;
  metrics: EconomicsMetrics;
  monthly: Array<MonthRow>;
  niche: string;
  scenarios: number;
  start_month: number;
  start_year: number;
  steady_month: SteadyMonth;
  tax: TaxSummary;
  versions: Versions;
  warnings: Array<string>;
  years: Array<YearRow>;
}

export interface EconomicsRequest {
  city: string;
  demand: GeoDemand | RevenueDemand | TrafficDemand | GeoPlatformDemand;
  discount_rate_annual?: number | null;
  financing?: Financing | null;
  horizon_months?: number;
  investment?: Investment;
  niche: string;
  operations?: Operations;
  premises?: Premises;
  start_month?: number | null;
  start_year?: number | null;
  tax?: TaxSettings;
}

export interface Estimate {
  p10: number;
  p50: number;
  p90: number;
}

export interface Financing {
  business_age_months?: number;
  grace_months?: number | null;
  loan_amount_rub?: number | null;
  loan_share?: number | null;
  product?: string | null;
  rate_annual?: number | null;
  schedule?: 'annuity' | 'differentiated' | null;
  term_months?: number | null;
}

export interface GeoDemand {
  lat: number;
  lon: number;
  source: 'geostart';
}

export interface GeoPlatformDemand {
  lat: number;
  lon: number;
  provider?: string | null;
  source: 'geoplatform';
  squares?: Array<GeoSquare> | null;
}

export interface GeoSquare {
  east: number;
  footfall_day?: Estimate | null;
  north: number;
  south: number;
  spend_rub_month: Estimate;
  square_id: string;
  west: number;
}

export interface Investment {
  capex_rub?: number | null;
  franchise_fee_rub?: number;
  working_capital_rub?: number | null;
}

export interface InvestmentItem {
  amount: number;
  code: string;
  life_months: number | null;
  name: string;
}

export interface InvestmentSummary {
  capex: number;
  franchise_fee: number;
  items: Array<InvestmentItem>;
  loan: number;
  own_funds: number;
  security_deposit: number;
  total: MoneyRange;
  working_capital: number;
}

export interface MonthRow {
  calendar_month: number;
  cogs: number;
  cumulative_project_cash: number;
  depreciation: number;
  dscr: number | null;
  ebitda: number;
  interest: number;
  month: number;
  net_profit: number;
  other: number;
  owner_cash_flow: number;
  payroll: number;
  principal: number;
  rent: number;
  revenue: number;
  taxes: number;
}

export interface NormValue {
  code: string;
  name: string;
  note: string;
  source: string | null;
  unit: string;
  value: number | Array<number>;
}

export interface NormsResponse {
  city: string;
  common: Array<NormValue>;
  discount_rate_annual: number;
  niche: string;
  niche_norms: Array<NormValue>;
  parameters: Array<ParameterValue>;
  unit_name: string;
  version: string;
}

export interface Operations {
  cogs_share?: number | null;
  other_opex_rub_month?: number | null;
  salary_rub_month?: number | null;
  staff_count?: number | null;
}

export interface OptionalRange {
  p10: number | null;
  p50: number | null;
  p90: number | null;
}

export interface ParameterValue {
  code: string;
  name: string;
  p10: number;
  p50: number;
  p90: number;
  source: string | null;
  unit: string;
}

export interface PlanCheck {
  code: 'revenue_month' | 'capex' | 'payback_months';
  comment: string;
  model: OptionalRange;
  name: string;
  percentile: number | null;
  plan_value: number;
  risk_flag: boolean;
  status: 'below' | 'within' | 'above';
}

export interface Premises {
  area_m2?: number | null;
  central_district?: boolean | null;
  rent_rub_m2_month?: number | null;
  security_deposit_months?: number | null;
}

export interface ProductCondition {
  note: string;
  source: string | null;
  value: number;
}

export interface RegimeOption {
  burden_horizon_p50: number | null;
  contributions_horizon_p50: number | null;
  eligible: boolean;
  name: string;
  reason: string | null;
  regime:
    | 'usn_income_6'
    | 'usn_income_minus_expenses_15'
    | 'patent'
    | 'ausn_income_8'
    | 'ausn_income_minus_expenses_20';
  taxes_first_year_p50: number | null;
  taxes_horizon_p50: number | null;
}

export interface RevenueDemand {
  provider?: string | null;
  revenue_month: Estimate;
  source: 'revenue';
}

export interface ShareEstimate {
  p10: number;
  p50: number;
  p90: number;
}

export interface SteadyMonth {
  cogs: number;
  ebitda: number;
  other: number;
  owner_contributions: number;
  payroll_contributions: number;
  profit: number;
  rent: number;
  revenue: number;
  tax: number;
  vat: number;
  wages: number;
}

export interface TaxSettings {
  legal_form?: 'ip' | 'ooo';
  regime?:
    | 'auto'
    | 'usn_income_6'
    | 'usn_income_minus_expenses_15'
    | 'patent'
    | 'ausn_income_8'
    | 'ausn_income_minus_expenses_20';
}

export interface TaxSummary {
  chosen_automatically: boolean;
  explanation: string;
  legal_form: 'ip' | 'ooo';
  name: string;
  options: Array<RegimeOption>;
  regime:
    | 'usn_income_6'
    | 'usn_income_minus_expenses_15'
    | 'patent'
    | 'ausn_income_8'
    | 'ausn_income_minus_expenses_20';
}

export interface TrafficDemand {
  avg_check_rub?: Estimate | null;
  conversion: ShareEstimate;
  provider?: string | null;
  source: 'traffic';
  visitors_per_day: Estimate;
}

export interface Versions {
  data: string;
  model: string;
  norms: string;
  taxes: string;
}

export interface YearRow {
  depreciation: number;
  ebit: number;
  ebitda: number;
  interest: number;
  net_profit: number;
  operating_cash_flow: number;
  operating_costs: number;
  principal: number;
  revenue: number;
  taxes: number;
  year: number;
}

export interface SensitivityOutcome {
  profit_steady_month_p50: number;
  npv_p50: number;
  payback_months_p50: number | null;
}
export interface SensitivityCase extends SensitivityOutcome {
  dscr_min_p50: number | null;
  probability_dscr_below_threshold: number | null;
  probability_no_payback_24: number;
}
export interface SensitivityFactor {
  code: string;
  name: string;
  low: SensitivityOutcome & { change: number };
  high: SensitivityOutcome & { change: number };
}
export interface SensitivityReport {
  versions: Versions;
  shift_share: number;
  base: SensitivityCase;
  factors: SensitivityFactor[];
  stresses: Array<SensitivityCase & { code: string; name: string }>;
}
