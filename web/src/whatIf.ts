import type { EconomicsReport, EconomicsRequest, TaxSettings } from './api/economicsTypes';
import { decimal, rubles } from './format';

export const scenarioFields = [
  { key: 'check', label: 'Изменение среднего чека, %', min: -50, max: 50 },
  { key: 'flow', label: 'Изменение потока покупателей, %', min: -50, max: 50 },
  { key: 'rent', label: 'Аренда, ₽/м² в месяц', min: 0.01, max: 100000 },
  { key: 'staff', label: 'Штат, чел.', min: 0, max: 500 },
  { key: 'capex', label: 'Вложения в открытие, ₽', min: 0, max: 10000000000 },
  { key: 'share', label: 'Доля кредита, %', min: 0, max: 100 },
  { key: 'rate', label: 'Ставка кредита, % годовых', min: 0, max: 100 },
  { key: 'term', label: 'Срок кредита, мес.', min: 1, max: 360 },
  { key: 'grace', label: 'Льготный период, мес.', min: 0, max: 60 },
] as const;

export type ScenarioKey = (typeof scenarioFields)[number]['key'];
export type ScenarioValues = Partial<Record<ScenarioKey, string>> & {
  regime?: TaxSettings['regime'];
};
export function initialNumbers(
  report: EconomicsReport,
  body: EconomicsRequest,
): Partial<Record<ScenarioKey, number>> {
  const numeric = (name: string) => {
    const value = report.assumptions.find((a) => a.name.startsWith(name))?.value;
    return typeof value === 'number' ? value : undefined;
  };
  return {
    check: 0,
    flow: 0,
    rent: body.premises?.rent_rub_m2_month ?? numeric('Ставка аренды'),
    staff: body.operations?.staff_count ?? numeric('Число сотрудников'),
    capex: report.investment.capex,
    share: 100 * (body.financing?.loan_share ?? 0),
    rate: 100 * report.credit.rate_annual,
    term: report.credit.term_months,
    grace: report.credit.grace_months,
  };
}

export function scenarioRequest(
  body: EconomicsRequest,
  report: EconomicsReport,
  values: ScenarioValues,
): EconomicsRequest {
  const num = (key: ScenarioKey) => (values[key] === undefined ? undefined : Number(values[key]));
  const factor = (1 + (num('check') ?? 0) / 100) * (1 + (num('flow') ?? 0) / 100);
  const { p10, p50, p90 } = report.demand.revenue_steady_month;
  const share = num('share');
  const rate = num('rate');
  const baseRent = initialNumbers(report, body).rent;
  return {
    ...body,
    demand: {
      source: 'revenue',
      provider: 'что если',
      revenue_month: { p10: p10 * factor, p50: p50 * factor, p90: p90 * factor },
    },
    premises: { ...body.premises, rent_rub_m2_month: num('rent') ?? baseRent },
    operations: { ...body.operations, staff_count: num('staff') ?? body.operations?.staff_count },
    investment: { ...body.investment, capex_rub: num('capex') ?? body.investment?.capex_rub },
    financing:
      share === 0
        ? null
        : body.financing || (share ?? 0) > 0
          ? {
              ...body.financing,
              loan_share: share === undefined ? body.financing?.loan_share : share / 100,
              rate_annual: rate === undefined ? body.financing?.rate_annual : rate / 100,
              term_months: num('term') ?? body.financing?.term_months,
              grace_months: num('grace') ?? body.financing?.grace_months,
            }
          : null,
    tax: { ...body.tax, regime: values.regime ?? body.tax?.regime ?? 'auto' },
  };
}

const indicators = [
  {
    label: 'Выручка в месяц',
    value: (r: EconomicsReport) => r.demand.revenue_steady_month.p50,
    money: true,
    direction: 1,
  },
  {
    label: 'Прибыль типового месяца',
    value: (r: EconomicsReport) => r.metrics.profit_steady_month.p50,
    money: true,
    direction: 1,
  },
  { label: 'NPV', value: (r: EconomicsReport) => r.metrics.npv.p50, money: true, direction: 1 },
  {
    label: 'Окупаемость, мес.',
    value: (r: EconomicsReport) => r.metrics.payback_months.p50,
    money: false,
    direction: -1,
  },
  {
    label: 'Безубыточная выручка в месяц',
    value: (r: EconomicsReport) => r.metrics.break_even_revenue_month.p50,
    money: true,
    direction: -1,
  },
  {
    label: 'Первый платёж',
    value: (r: EconomicsReport) => r.credit.first_payment,
    money: true,
    direction: -1,
  },
  {
    label: 'Минимальный DSCR',
    value: (r: EconomicsReport) => r.credit.dscr_min.p50,
    money: false,
    direction: 1,
  },
];
export function compareScenarios(base: EconomicsReport, scenario: EconomicsReport) {
  return indicators.map(({ label, value, money, direction }) => {
    const before = value(base),
      after = value(scenario);
    const rounded = (v: number) => (money ? Math.round(v) : Math.round(v * 100) / 100);
    const display = (v: number | null) =>
      v === null ? 'Нет значения' : money ? rubles(rounded(v)) : decimal(rounded(v));
    let delta = 'Нет сопоставимых значений';
    if (before !== null && after !== null) {
      const change = rounded(rounded(after) - rounded(before));
      delta =
        change === 0
          ? '0 · без изменения'
          : (change > 0 ? '+' : '−') +
            display(Math.abs(change)) +
            ' · ' +
            (change * direction > 0 ? 'лучше' : 'хуже');
    } else if (label === 'Окупаемость, мес.' && before !== after) {
      delta = before === null ? 'Окупается · лучше' : 'Не окупается · хуже';
    }
    return { label, before: display(before), after: display(after), delta };
  });
}
