import { request, useMocks } from './client';
import type {
  EconomicsReport,
  EconomicsRequest,
  CreditCheckRequest,
  CreditCheckReport,
  CreditProductInfo,
  SensitivityReport,
} from './economicsTypes';

export const mockSensitivity =
  useMocks || (import.meta.env.VITE_USE_MOCKS ?? 'sensitivity') === 'sensitivity';

function post<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  return request(
    path,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    },
    '/api/v2',
  );
}

export const financeApi = {
  economics: (body: EconomicsRequest, signal?: AbortSignal): Promise<EconomicsReport> =>
    post('/economics', body, signal),
  creditCheck: (body: CreditCheckRequest, signal?: AbortSignal): Promise<CreditCheckReport> =>
    post('/credit-check', body, signal),
  products: (signal?: AbortSignal): Promise<CreditProductInfo[]> =>
    request('/credit-products', { signal }, '/api/v2'),
  sensitivity: async (
    body: EconomicsRequest & { shift_share?: number },
    signal?: AbortSignal,
  ): Promise<SensitivityReport> =>
    mockSensitivity
      ? (await import('../mocks/sensitivity.json')).default
      : post('/sensitivity', body, signal),
};
