import { useEffect, useMemo, useState } from 'react';
import { ApiError, useMocks } from '../api/client';
import { financeApi } from '../api/economics';
import type { Financing } from '../api/economicsTypes';
import type { ReportRequest } from '../api/types';
import { message } from '../format';
import { economicsRequest } from '../api/economicsRequest';

export function useResource<T>(load: ((signal: AbortSignal) => Promise<T>) | null, delay = 0) {
  const [result, setResult] = useState<{ load: typeof load; value?: T; error?: ApiError }>();
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!load) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void load(controller.signal)
        .then((value) => {
          if (!controller.signal.aborted) setResult({ load, value });
        })
        .catch((cause: unknown) => {
          if (!controller.signal.aborted)
            setResult({
              load,
              error: cause instanceof ApiError ? cause : new ApiError(message(cause), 0),
            });
        });
    }, delay);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [load, attempt, delay]);
  const current = result?.load === load ? result : undefined;
  return {
    value: current?.value,
    error: current?.error,
    pending: !!load && !current,
    retry: () => {
      setResult(undefined);
      setAttempt((value) => value + 1);
    },
  };
}

export function useEconomics(point: ReportRequest | null) {
  const [financing, setFinancing] = useState<Financing | null>(null);
  const body = useMemo(
    () => (point && !useMocks ? economicsRequest(point, financing) : null),
    [point, financing],
  );
  const economics = useResource(
    useMemo(() => body && ((signal: AbortSignal) => financeApi.economics(body, signal)), [body]),
  );
  const sensitivity = useResource(
    useMemo(() => body && ((signal: AbortSignal) => financeApi.sensitivity(body, signal)), [body]),
  );
  const products = useResource(body ? financeApi.products : null);
  const fieldError = (name: string) =>
    economics.error?.errors
      .filter((issue) => issue.field === name)
      .map((issue) => issue.message)
      .join(' ');
  return { body, economics, sensitivity, products, setFinancing, financing, fieldError };
}
