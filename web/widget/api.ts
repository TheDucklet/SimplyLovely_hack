import type { ReportRequest } from '../src/api/types';

export type WidgetSettings = { api: string; point: ReportRequest };

function required(element: Element, name: string): string {
  const value = element.getAttribute(name)?.trim();
  if (!value) throw new Error('Укажите атрибут ' + name + ' у элемента geostart-report.');
  return value;
}

function coordinate(element: Element, name: string, limit: number): number {
  const value = Number(required(element, name));
  if (!Number.isFinite(value) || Math.abs(value) > limit)
    throw new Error(`Введите ${name} числом от ${-limit} до ${limit}.`);
  return value;
}

export function settings(element: Element): WidgetSettings {
  const point = {
    city: required(element, 'city'),
    niche: required(element, 'niche'),
    lat: coordinate(element, 'lat', 90),
    lon: coordinate(element, 'lon', 180),
  };
  const raw = required(element, 'api');
  const invalid = 'Укажите в api адрес HTTP или HTTPS либо путь от корня сайта.';
  if (!/^https?:\/\//i.test(raw) && !/^\/(?!\/)/.test(raw)) throw new Error(invalid);
  let url: URL;
  try {
    url = new URL(raw, element.ownerDocument.URL);
  } catch {
    throw new Error(invalid);
  }
  if (
    !['http:', 'https:'].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.search ||
    url.hash
  )
    throw new Error(invalid);
  return { point, api: url.href.replace(/\/+$/, '') };
}

export async function post<T>(url: string, body: unknown, signal: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    });
  } catch {
    throw new Error('Нет связи с ГеоСтартом. Проверьте адрес API и доступ к серверу.');
  }
  if (response.status === 401) throw new Error('Войдите в кабинет и повторите запрос.');
  if (response.status === 403) throw new Error('Недостаточно прав для просмотра отчёта.');
  if (!response.ok) {
    const problem = await response.json().catch(() => null);
    throw new Error(
      typeof problem?.detail === 'string'
        ? problem.detail
        : `Сервер вернул ошибку ${response.status}.`,
    );
  }
  try {
    return await response.json();
  } catch {
    throw new Error('Сервер вернул нечитаемый ответ. Проверьте адрес API.');
  }
}
