import type { HexScore } from './api/types';
import { months, rubles } from './format';

export type Metric = 'revenue' | 'payback';
export type Color = [number, number, number];
export const REVENUE_COLORS: Color[] = [
  [230, 189, 152],
  [211, 161, 113],
  [145, 175, 147],
  [83, 140, 122],
  [32, 105, 93],
];
export const NO_PAYBACK_COLOR: Color = [136, 141, 155];

export function metricValue(item: HexScore, metric: Metric): number | null {
  return metric === 'revenue' ? item.revenue_p50 : item.payback_months_p50;
}

export function metricScale(items: HexScore[], metric: Metric) {
  const values = items
    .map((item) => metricValue(item, metric))
    .filter((value): value is number => value !== null)
    .sort((a, b) => a - b);
  const thresholds = REVENUE_COLORS.slice(1).map(
    (_, index) =>
      values[Math.floor(((index + 1) * (values.length - 1)) / REVENUE_COLORS.length)] ?? 0,
  );
  const colors = metric === 'revenue' ? REVENUE_COLORS : [...REVENUE_COLORS].reverse();
  return {
    values,
    thresholds,
    colors,
    color: (item: HexScore): Color => {
      const value = metricValue(item, metric);
      return value === null
        ? NO_PAYBACK_COLOR
        : colors[thresholds.filter((threshold) => value >= threshold).length];
    },
    format: (value: number | null): string =>
      metric === 'revenue' && value !== null ? rubles(value) : months(value),
  };
}
