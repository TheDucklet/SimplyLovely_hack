import { useCallback, type ReactElement } from 'react';
import { economicsRequest } from '../src/api/economicsRequest';
import type { EconomicsReport } from '../src/api/economicsTypes';
import type { LocationReport } from '../src/api/types';
import { FinanceReport } from '../src/components/FinanceReport';
import { months, rubles, riskLabels } from '../src/format';
import { useResource } from '../src/hooks/useEconomics';
import { post, type WidgetSettings } from './api';

function Notice({ error, retry }: { error?: Error; retry: () => void }): ReactElement {
  if (!error) return <p role="status">Загружаем расчёт…</p>;
  return (
    <div role="alert">
      <p>{error.message}</p>
      <button type="button" onClick={retry}>
        Повторить запрос
      </button>
    </div>
  );
}

export function Report({ point, api }: WidgetSettings): ReactElement {
  const summary = useResource(
    useCallback(
      (signal: AbortSignal) => post<LocationReport>(api + '/api/v1/report', point, signal),
      [point, api],
    ),
  );
  const finance = useResource(
    useCallback(
      (signal: AbortSignal) =>
        post<EconomicsReport>(api + '/api/v2/economics', economicsRequest(point, null), signal),
      [point, api],
    ),
  );
  const place = summary.value;
  return (
    <article lang="ru">
      <h2>Отчёт по месту</h2>
      {place ? (
        <>
          <p>{place.location.address || `${point.lat}, ${point.lon}`}</p>
          <dl className="finance-values">
            <div>
              <dt>Выручка в месяц</dt>
              <dd>{rubles(place.revenue_month.p50)}</dd>
            </div>
            <div>
              <dt>Диапазон выручки p10-p90</dt>
              <dd>
                {rubles(place.revenue_month.p10)} – {rubles(place.revenue_month.p90)}
              </dd>
            </div>
            <div>
              <dt>Расходы в месяц</dt>
              <dd>{rubles(place.costs_month.total)}</dd>
            </div>
            <div>
              <dt>Прибыль в месяц</dt>
              <dd>{rubles(place.profit_month_p50)}</dd>
            </div>
            <div>
              <dt>Срок окупаемости</dt>
              <dd>{months(place.payback_months_p50)}</dd>
            </div>
            <div>
              <dt>Риск</dt>
              <dd>{riskLabels[place.risk_level]}</dd>
            </div>
          </dl>
        </>
      ) : (
        <Notice error={summary.error} retry={summary.retry} />
      )}
      <section className="finance-block" aria-label="Финансовая модель">
        <h3>Финансовая модель</h3>
        {finance.value ? (
          <FinanceReport report={finance.value} />
        ) : (
          <Notice error={finance.error} retry={finance.retry} />
        )}
      </section>
    </article>
  );
}
