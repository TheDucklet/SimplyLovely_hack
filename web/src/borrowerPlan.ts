import type { BusinessPlan, CreditCheckReport, PlanCheck } from './api/economicsTypes';
import { decimal, rubles } from './format';

export const planFields = [
  {
    key: 'revenue_month_rub',
    label: 'Выручка в месяц, ₽',
    min: 0.01,
    max: 1e10,
    step: '0.01',
    required: true,
  },
  { key: 'capex_rub', label: 'Вложения, ₽', min: 0.01, max: 1e10, step: '0.01' },
  { key: 'payback_months', label: 'Срок окупаемости, мес.', min: 0.01, max: 600, step: '0.01' },
  {
    key: 'loan_amount_rub',
    label: 'Сумма кредита, ₽',
    min: 0,
    max: 1e10,
    step: '0.01',
    required: true,
  },
  { key: 'rate_annual', label: 'Ставка, % годовых', min: 0, max: 100, step: 'any' },
  { key: 'term_months', label: 'Срок кредита, мес.', min: 1, max: 360, step: '1' },
  { key: 'business_age_months', label: 'Возраст бизнеса, мес.', min: 0, max: 1200, step: '1' },
] as const;
export type PlanDraft = Record<(typeof planFields)[number]['key'] | 'product', string>;
export const emptyPlan: PlanDraft = {
  revenue_month_rub: '',
  capex_rub: '',
  payback_months: '',
  loan_amount_rub: '',
  rate_annual: '',
  term_months: '',
  product: '',
  business_age_months: '',
};

export function borrowerPlan(values: PlanDraft): BusinessPlan {
  const optional = (raw: string) => (raw === '' ? undefined : Number(raw));
  return {
    revenue_month_rub: Number(values.revenue_month_rub),
    loan_amount_rub: Number(values.loan_amount_rub),
    capex_rub: optional(values.capex_rub),
    payback_months: optional(values.payback_months),
    rate_annual: values.rate_annual === '' ? undefined : Number(values.rate_annual) / 100,
    term_months: optional(values.term_months),
    business_age_months: optional(values.business_age_months),
    product: values.product || undefined,
  };
}
export const verdictLabels: Record<CreditCheckReport['verdict'], string> = {
  confirmed: 'Подтверждён',
  needs_review: 'Нужна проверка',
  not_confirmed: 'Не подтверждён',
};
export const checkHeaders = ['Статья', 'План', 'Модель p10-p90', 'Перцентиль', 'Статус', 'Риск'];
const statuses: Record<PlanCheck['status'], string> = {
  below: 'ниже',
  within: 'в диапазоне',
  above: 'выше',
};
export function checkCells(check: PlanCheck): string[] {
  const format = (value: number | null) =>
    value === null
      ? 'не достигнут'
      : check.code === 'payback_months'
        ? decimal(value) + ' мес.'
        : rubles(value);
  return [
    check.name,
    format(check.plan_value),
    format(check.model.p10) + ' / ' + format(check.model.p90),
    check.percentile === null ? 'Нет оценки' : decimal(check.percentile),
    statuses[check.status],
    check.risk_flag ? 'Есть' : 'Нет',
  ];
}
export function coverageLabel(report: CreditCheckReport): string {
  return 'Доля сценариев с DSCR не ниже ' + decimal(report.economics.credit.dscr_threshold);
}
export function coverageValue(report: CreditCheckReport): string {
  return decimal(report.probability_dscr_ok * 100) + '%';
}
