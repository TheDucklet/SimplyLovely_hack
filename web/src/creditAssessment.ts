import type { MoneyRange } from './api/types';
import { decimal } from './format';

export type RevenueInput = { kind: 'empty' | 'invalid' } | { kind: 'valid'; value: number };
export type RevenuePosition = 'below' | 'within' | 'above';
export interface RevenueAssessment {
  kind: RevenuePosition;
  differenceRub: number;
  differencePercent: number | null;
  message: string;
}

const PERCENT_SCALE = 100;
const PERCENT_PRECISION = 10;
const MONEY_PRECISION = 100;
const revenueFormatter = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 });

export function formatRevenue(value: number): string {
  return `${revenueFormatter.format(value).replace(/\u00a0|\u202f/g, ' ')} ₽`;
}

export function parsePlanRevenue(text: string): RevenueInput {
  const normalized = text.replace(/\s/g, '').replace(',', '.');
  if (!normalized) return { kind: 'empty' };
  if (!/^\d+(?:\.\d{1,2})?$/.test(normalized)) return { kind: 'invalid' };
  const value = Number(normalized);
  return Number.isFinite(value) && Number.isSafeInteger(Math.round(value * MONEY_PRECISION))
    ? { kind: 'valid', value }
    : { kind: 'invalid' };
}

function percentageText(value: number): string {
  return `${decimal(Math.round(value * PERCENT_PRECISION) / PERCENT_PRECISION)}%`;
}

export function assessPlanRevenue(range: MoneyRange, planned: number): RevenueAssessment | null {
  if (
    ![range.p10, range.p50, range.p90, planned].every(Number.isFinite) ||
    range.p10 < 0 ||
    planned < 0 ||
    range.p10 > range.p50 ||
    range.p50 > range.p90
  )
    return null;
  const [lowerCents, upperCents, plannedCents] = [range.p10, range.p90, planned].map((value) =>
    Math.round(value * MONEY_PRECISION),
  );
  if (![lowerCents, upperCents, plannedCents].every(Number.isSafeInteger)) return null;
  if (plannedCents >= lowerCents && plannedCents <= upperCents)
    return {
      kind: 'within',
      differenceRub: 0,
      differencePercent: 0,
      message: 'Выручка в плане входит в диапазон p10-p90 модели',
    };
  const kind: RevenuePosition = plannedCents > upperCents ? 'above' : 'below';
  const boundaryCents = kind === 'above' ? upperCents : lowerCents;
  const differenceCents = Math.abs(plannedCents - boundaryCents);
  const differenceRub = differenceCents / MONEY_PRECISION;
  const differencePercent =
    boundaryCents === 0 ? null : (differenceCents / boundaryCents) * PERCENT_SCALE;
  const prefix = `Выручка в плане ${kind === 'above' ? 'выше p90' : 'ниже p10'} модели`;
  return {
    kind,
    differenceRub,
    differencePercent,
    message:
      differencePercent === null
        ? `${prefix} на ${formatRevenue(differenceRub)}. Процент не рассчитывается при нулевой границе`
        : differencePercent < 1 / PERCENT_PRECISION
          ? `${prefix} менее чем на 0,1%`
          : `${prefix} на ${percentageText(differencePercent)}`,
  };
}
