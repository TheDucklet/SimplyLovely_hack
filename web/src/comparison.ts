import type { LocationReport } from './api/types';
import { decimal, months, rubles } from './format';

export type ReportSlot = 'first' | 'second';
type DifferenceTone = 'positive' | 'negative' | 'neutral';

export interface ComparisonMetric {
  label: string;
  first: string;
  second: string;
  difference: string;
  direction: string;
  tone: DifferenceTone;
}

const MONTH_PRECISION = 10;

function toneFor(difference: number, lowerIsBetter: boolean): DifferenceTone {
  if (difference === 0) return 'neutral';
  return difference > 0 !== lowerIsBetter ? 'positive' : 'negative';
}

function moneyMetric(
  label: string,
  first: number,
  second: number,
  lowerIsBetter = false,
): ComparisonMetric {
  const difference = Math.round(second) - Math.round(first);
  return {
    label,
    first: rubles(first),
    second: rubles(second),
    difference: `${difference > 0 ? '+' : difference < 0 ? '−' : ''}${rubles(Math.abs(difference))}`,
    direction: difference > 0 ? 'Больше' : difference < 0 ? 'Меньше' : 'Без разницы',
    tone: toneFor(difference, lowerIsBetter),
  };
}

function paybackMetric(first: number | null, second: number | null): ComparisonMetric {
  const metric: ComparisonMetric = {
    label: 'Окупаемость',
    first: months(first),
    second: months(second),
    difference: '',
    direction: '',
    tone: 'neutral',
  };
  if (first === null || second === null) {
    metric.difference =
      first === null && second === null
        ? 'Оба не окупаются'
        : `Адрес ${first === null ? '1' : '2'} не окупается`;
    return metric;
  }
  const difference =
    (Math.round(second * MONTH_PRECISION) - Math.round(first * MONTH_PRECISION)) / MONTH_PRECISION;
  return {
    ...metric,
    difference: `${difference > 0 ? '+' : difference < 0 ? '−' : ''}${decimal(Math.abs(difference))} мес.`,
    direction: difference > 0 ? 'Дольше' : difference < 0 ? 'Быстрее' : 'Без разницы',
    tone: toneFor(difference, true),
  };
}

export function compareReports(first: LocationReport, second: LocationReport): ComparisonMetric[] {
  return [
    moneyMetric('Выручка в месяц, p50', first.revenue_month.p50, second.revenue_month.p50),
    moneyMetric('Расходы в месяц', first.costs_month.total, second.costs_month.total, true),
    moneyMetric('Прибыль в месяц, p50', first.profit_month_p50, second.profit_month_p50),
    paybackMetric(first.payback_months_p50, second.payback_months_p50),
  ];
}
