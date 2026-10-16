import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import type { LocationReport, ReportRequest } from '../api/types';
import { message } from '../format';

const RECALCULATE_DELAY_MS = 500;
export interface SelectedLocation {
  lat: number;
  lon: number;
  address?: string;
}

export function useLocationReport(city: string, niche: string) {
  const [location, setLocation] = useState<SelectedLocation | null>(null);
  const [report, setReport] = useState<LocationReport | null>(null);
  const [calculatedAt, setCalculatedAt] = useState<string | null>(null);
  const [completedRequest, setCompletedRequest] = useState<ReportRequest | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [area, setArea] = useState('');
  const [rent, setRent] = useState('');
  const [planRevenue, setPlanRevenue] = useState('');
  const busy = useRef(false);
  const queued = useRef<ReportRequest | null>(null);
  const epoch = useRef(0);
  const mounted = useRef(true);
  const lastRequest = useRef('');
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      epoch.current += 1;
      queued.current = null;
    };
  }, []);
  const request = useCallback((body: ReportRequest, force = false) => {
    const key = `${epoch.current}:${JSON.stringify(body)}`;
    if (!force && key === lastRequest.current) return;
    lastRequest.current = key;
    queued.current = body;
    if (busy.current) return;
    busy.current = true;
    setPending(true);
    setError('');
    async function consume(): Promise<void> {
      while (queued.current && mounted.current) {
        const next = queued.current;
        queued.current = null;
        const context = epoch.current;
        try {
          const result = await api.report(next);
          if (mounted.current && context === epoch.current && !queued.current) {
            setReport(result);
            setCalculatedAt(new Date().toISOString());
            setCompletedRequest(next);
            setError('');
          }
        } catch (cause) {
          if (mounted.current && context === epoch.current && !queued.current)
            setError(message(cause));
        }
      }
      busy.current = false;
      if (mounted.current) setPending(false);
    }
    void consume();
  }, []);
  const close = useCallback(() => {
    epoch.current += 1;
    queued.current = null;
    lastRequest.current = '';
    setLocation(null);
    setReport(null);
    setCalculatedAt(null);
    setCompletedRequest(null);
    setError('');
    setArea('');
    setRent('');
    setPlanRevenue('');
  }, []);
  useEffect(() => {
    close();
  }, [city, niche, close]);
  const select = useCallback(
    (point: SelectedLocation) => {
      if (busy.current) return;
      epoch.current += 1;
      lastRequest.current = '';
      setLocation(point);
      setReport(null);
      setCalculatedAt(null);
      setCompletedRequest(null);
      setArea('');
      setRent('');
      setPlanRevenue('');
      request({
        city,
        niche,
        lat: point.lat,
        lon: point.lon,
        area_m2: null,
        rent_rub_m2_month: null,
      });
    },
    [city, niche, request],
  );
  const invalid =
    (area !== '' && (!Number.isFinite(Number(area)) || Number(area) <= 0)) ||
    (rent !== '' && (!Number.isFinite(Number(rent)) || Number(rent) <= 0));
  useEffect(() => {
    if (!location || invalid) return;
    const timer = window.setTimeout(
      () =>
        request({
          city,
          niche,
          lat: location.lat,
          lon: location.lon,
          area_m2: area === '' ? null : Number(area),
          rent_rub_m2_month: rent === '' ? null : Number(rent),
        }),
      RECALCULATE_DELAY_MS,
    );
    return () => window.clearTimeout(timer);
  }, [city, niche, location, area, rent, invalid, request]);
  const retry = () => {
    if (location && !invalid)
      request(
        {
          city,
          niche,
          lat: location.lat,
          lon: location.lon,
          area_m2: area === '' ? null : Number(area),
          rent_rub_m2_month: rent === '' ? null : Number(rent),
        },
        true,
      );
  };
  const reportIsCurrent =
    !!completedRequest &&
    !!location &&
    completedRequest.city === city &&
    completedRequest.niche === niche &&
    completedRequest.lat === location.lat &&
    completedRequest.lon === location.lon &&
    completedRequest.area_m2 === (area === '' ? null : Number(area)) &&
    completedRequest.rent_rub_m2_month === (rent === '' ? null : Number(rent));
  return {
    location,
    report,
    calculatedAt,
    reportIsCurrent,
    pending,
    error,
    area,
    rent,
    setArea,
    setRent,
    planRevenue,
    setPlanRevenue,
    invalid,
    select,
    close,
    retry,
  };
}
