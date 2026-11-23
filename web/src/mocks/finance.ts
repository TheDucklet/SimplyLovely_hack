import { ApiError, fixture } from '../api/client';
import type {
  BusinessPlan,
  CreditCheckReport,
  CreditCheckRequest,
  EconomicsReport,
  EconomicsRequest,
} from '../api/economicsTypes';
import { hasDemoFinance } from './location';

const examplePlan: Required<Omit<BusinessPlan, 'grace_months' | 'schedule'>> = {
  revenue_month_rub: 920000,
  capex_rub: 3200000,
  payback_months: 30,
  loan_amount_rub: 100000,
  rate_annual: 0.2,
  term_months: 36,
  product: 'vtb_express',
  business_age_months: 24,
};

export async function demoEconomics(body: EconomicsRequest): Promise<EconomicsReport> {
  if (body.financing) throw new ApiError('Автономный пример рассчитан без кредита.', 422);
  if (body.demand.source === 'geostart') return fixture('economics');
  const base = await fixture<EconomicsReport>('economics');
  const demand = body.demand;
  const matchesDemand =
    demand.source === 'revenue' &&
    (['p10', 'p50', 'p90'] as const).every(
      (key) =>
        Math.abs(demand.revenue_month[key] - base.demand.revenue_steady_month[key] * 1.1) < 0.01,
    );
  if (
    matchesDemand &&
    body.premises?.rent_rub_m2_month ===
      base.assumptions.find((a) => a.name.startsWith('Ставка аренды'))?.value &&
    body.operations?.staff_count == null &&
    body.investment?.capex_rub == null &&
    body.tax?.regime === 'auto'
  )
    return fixture('economics-plus-ten');
  throw new ApiError(
    'Для демонстрации увеличьте средний чек на 10% и оставьте остальные поля пустыми.',
    422,
  );
}

export function demoCreditCheck({
  economics,
  plan,
}: CreditCheckRequest): Promise<CreditCheckReport> {
  if (
    economics.demand.source !== 'geostart' ||
    !hasDemoFinance(economics.demand) ||
    !Object.entries(examplePlan).every(([key, value]) => plan[key as keyof BusinessPlan] === value)
  ) {
    throw new ApiError(
      'Для автономной проверки введите параметры демонстрационного плана из инструкции.',
      422,
    );
  }
  return fixture('credit-check');
}
