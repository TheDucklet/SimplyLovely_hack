import type {
  AddressMatch,
  CityInfo,
  Competitor,
  HealthResponse,
  HexesResponse,
  LocationReport,
  NicheInfo,
  ReportRequest,
} from './types';
import { createRequestQueue } from './requestQueue';

export const useMocks = import.meta.env.VITE_USE_MOCKS === 'true';
const apiUrl = (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
const fixtures = import.meta.glob('../mocks/*.json', { import: 'default' });
const queueReport = createRequestQueue<LocationReport>();

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

function errorDetail(value: unknown): string {
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) {
    return value
      .map((item: unknown) => {
        if (typeof item === 'object' && item !== null && 'msg' in item) {
          const field = 'loc' in item && Array.isArray(item.loc) ? item.loc.slice(1).join('.') : '';
          return `${field ? `${field}: ` : ''}${String(item.msg)}`;
        }
        return 'Проверьте параметры запроса';
      })
      .join('. ');
  }
  return 'Не удалось выполнить запрос. Повторите попытку';
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${apiUrl}/api/v1${path}`, options);
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError('Нет связи с сервером. Проверьте подключение и запуск API', 0);
  }
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    throw new ApiError(
      errorDetail(
        typeof body === 'object' && body !== null && 'detail' in body ? body.detail : null,
      ),
      response.status,
    );
  }
  return response.json() as Promise<T>;
}

async function fixture<T>(name: string): Promise<T> {
  const load = fixtures[`../mocks/${name}.json`];
  if (!load) throw new ApiError('Не удалось загрузить данные демонстрации', 404);
  return (await load()) as T;
}

export const api = {
  health: (): Promise<HealthResponse> => (useMocks ? fixture('health') : request('/health')),
  cities: (): Promise<CityInfo[]> => (useMocks ? fixture('cities') : request('/cities')),
  niches: (): Promise<NicheInfo[]> => (useMocks ? fixture('niches') : request('/niches')),
  hexes: (city: string, niche: string, signal?: AbortSignal): Promise<HexesResponse> =>
    useMocks
      ? fixture('hexes')
      : request(`/hexes?${new URLSearchParams({ city, niche })}`, { signal }),
  competitors: (city: string, niche: string, signal?: AbortSignal): Promise<Competitor[]> =>
    useMocks
      ? fixture('competitors')
      : request(`/competitors?${new URLSearchParams({ city, niche })}`, { signal }),
  search: async (city: string, q: string, signal?: AbortSignal): Promise<AddressMatch[]> =>
    useMocks
      ? (await fixture<AddressMatch[]>('search')).filter((item) =>
          item.address.toLocaleLowerCase('ru').includes(q.toLocaleLowerCase('ru')),
        )
      : request(`/search?${new URLSearchParams({ city, q })}`, { signal }),
  report: (body: ReportRequest, signal?: AbortSignal): Promise<LocationReport> =>
    queueReport(() =>
      useMocks
        ? fixture('report')
        : request('/report', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
            signal,
          }),
    ),
};
