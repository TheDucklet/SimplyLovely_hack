import type { EconomicsRequest, Financing } from './economicsTypes';
import type { ReportRequest } from './types';

export function economicsRequest(
  point: ReportRequest,
  financing: Financing | null,
  today = new Date(),
): EconomicsRequest {
  const start = new Date(today.getFullYear(), today.getMonth() + 1, 1);
  return {
    city: point.city,
    niche: point.niche,
    demand: { source: 'geostart', lat: point.lat, lon: point.lon },
    premises: { area_m2: point.area_m2, rent_rub_m2_month: point.rent_rub_m2_month },
    financing,
    horizon_months: 36,
    start_year: start.getFullYear(),
    start_month: start.getMonth() + 1,
  };
}
