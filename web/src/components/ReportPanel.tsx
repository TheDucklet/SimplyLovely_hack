import { useRef, useEffect } from 'react';
import type { Assumption, MonthlyCosts, RiskLevel } from '../api/types';
import type { useLocationReport } from '../hooks/useLocationReport';
import { decimal, months, number, rubles } from '../format';
import { useMocks } from '../api/client';
import { BusinessPlanButton } from './BusinessPlanButton';
import { CreditAssessment } from './CreditAssessment';

const RISK_LABELS: Record<RiskLevel, string> = {
  low: 'Низкий риск',
  medium: 'Средний риск',
  high: 'Высокий риск',
};
const COST_LABELS: [keyof MonthlyCosts, string][] = [
  ['rent', 'Аренда'],
  ['payroll', 'Зарплаты'],
  ['cogs', 'Себестоимость'],
  ['taxes', 'Налоги'],
  ['other', 'Прочие'],
];
const BANK_ACTIONS = ['Открыть счёт', 'Подключить эквайринг', 'Кредит на открытие'];
function Source({ assumption }: { assumption: Assumption }) {
  if (!assumption.source) return <span className="unverified">без подтверждённого источника</span>;
  try {
    const url = new URL(assumption.source);
    if (['https:', 'http:'].includes(url.protocol))
      return (
        <a href={url.href} target="_blank" rel="noreferrer">
          {url.hostname}
        </a>
      );
  } catch {
    return <span>{assumption.source}</span>;
  }
  return <span>{assumption.source}</span>;
}
export function ReportPanel({
  state,
  onBankAction,
  cityName,
  nicheName,
  heading = 'Отчёт по адресу',
  titleId = 'report-title',
  onClose,
  onCompare,
  onMethodology,
  creditMode,
}: {
  state: ReturnType<typeof useLocationReport>;
  onBankAction: (action: string) => void;
  onMethodology?: () => void;
  cityName: string;
  nicheName: string;
  heading?: string;
  titleId?: string;
  onClose?: () => void;
  onCompare?: () => void;
  creditMode: boolean;
}) {
  const { location, report, pending, error, area, rent, setArea, setRent, invalid, close, retry } =
    state;
  const title = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    title.current?.focus({ preventScroll: true });
  }, [location]);
  if (!location) return null;
  const address =
    report?.location.address ||
    location.address ||
    `${location.lat.toFixed(5)}, ${location.lon.toFixed(5)}`;
  return (
    <aside className="report-panel" aria-labelledby={titleId}>
      <header className="report-heading">
        <div>
          <span className="eyebrow">ОЦЕНКА МЕСТА</span>
          <h2 id={titleId} ref={title} tabIndex={-1}>
            {heading}
          </h2>
        </div>
        <button
          className="icon-button"
          aria-label={
            titleId === 'report-title'
              ? 'Закрыть отчёт'
              : `Закрыть ${heading.toLocaleLowerCase('ru')}`
          }
          onClick={onClose || close}
        >
          ×
        </button>
      </header>
      <div className="report-content">
        <p className="report-address">{address}</p>
        {onCompare && report && (
          <button
            className="start-comparison"
            onClick={onCompare}
            disabled={pending || invalid || !!error || !state.reportIsCurrent || useMocks}
          >
            Сравнить с другим адресом
          </button>
        )}
        <div className="report-controls">
          <label>
            Площадь, м²
            <input
              type="number"
              min="0.01"
              step="any"
              placeholder="По модели"
              value={area}
              aria-invalid={area !== '' && Number(area) <= 0}
              onChange={(event) => setArea(event.target.value)}
              disabled={useMocks}
            />
          </label>
          <label>
            Аренда, ₽/м² в месяц
            <input
              type="number"
              min="0.01"
              step="any"
              placeholder="По модели"
              value={rent}
              aria-invalid={rent !== '' && Number(rent) <= 0}
              onChange={(event) => setRent(event.target.value)}
              disabled={useMocks}
            />
          </label>
        </div>
        {invalid && (
          <p className="inline-error" role="alert">
            Площадь и ставка аренды должны быть больше нуля
          </p>
        )}
        {useMocks && (
          <p className="footnote">В демонстрации показан фиксированный отчёт без пересчёта.</p>
        )}
        {pending && (
          <div className="report-loading" role="status">
            <span className="spinner" />
            {report ? 'Пересчитываем оценку' : 'Считаем выручку и расходы'}
          </div>
        )}
        {error && (
          <div className="report-error" role="alert">
            <p>{error}</p>
            <button onClick={retry} disabled={pending || invalid}>
              Повторить расчёт
            </button>
          </div>
        )}
        {report && (
          <div
            aria-busy={pending}
            className={pending ? 'report-results updating' : 'report-results'}
          >
            <div className="report-revenue">
              <span>Выручка в месяц</span>
              <strong>{rubles(report.revenue_month.p50)}</strong>
              <p>
                От {rubles(report.revenue_month.p10)} до {rubles(report.revenue_month.p90)},
                вероятнее всего {rubles(report.revenue_month.p50)}
              </p>
            </div>
            <span className={`risk-badge risk-${report.risk_level}`}>
              <i />
              {RISK_LABELS[report.risk_level]}
            </span>
            {creditMode && (
              <CreditAssessment
                range={report.revenue_month}
                value={state.planRevenue}
                onChange={state.setPlanRevenue}
                ready={state.reportIsCurrent && !pending && !invalid && !error}
              />
            )}
            <section className="report-section">
              <h3>Расходы в месяц</h3>
              <table className="costs-table">
                <tbody>
                  {COST_LABELS.map(([key, label]) => (
                    <tr key={key}>
                      <th scope="row">{label}</th>
                      <td>{rubles(report.costs_month[key])}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <th scope="row">Итого</th>
                    <td>{rubles(report.costs_month.total)}</td>
                  </tr>
                </tfoot>
              </table>
            </section>
            <dl className="finance-summary">
              <div>
                <dt>Прибыль в месяц</dt>
                <dd className={report.profit_month_p50 < 0 ? 'negative' : 'positive'}>
                  {rubles(report.profit_month_p50)}
                </dd>
              </div>
              <div>
                <dt>Капитальные затраты</dt>
                <dd>{rubles(report.capex_rub_p50)}</dd>
              </div>
              <div>
                <dt>Окупаемость</dt>
                <dd>
                  {report.payback_months_p50 === null
                    ? 'Не окупается при текущих допущениях'
                    : months(report.payback_months_p50)}
                </dd>
              </div>
            </dl>
            <p className="finance-note">
              Медиана прибыли рассчитана по сценариям и может отличаться от разницы показанных
              выручки и расходов.
            </p>
            <section className="report-section">
              <h3>Что влияет на выручку</h3>
              <p className="section-note">Эффект факторов в рублях в месяц по оценке модели</p>
              <ul className="factor-list">
                {[...report.factors]
                  .sort((a, b) => Math.abs(b.effect_rub) - Math.abs(a.effect_rub))
                  .slice(0, 5)
                  .map((factor) => (
                    <li key={factor.code}>
                      <div>
                        <span>{factor.name}</span>
                        <small>
                          {decimal(factor.value)} {factor.unit}
                        </small>
                      </div>
                      <strong
                        className={
                          factor.effect_rub === 0
                            ? 'neutral'
                            : factor.effect_rub > 0
                              ? 'positive'
                              : 'negative'
                        }
                      >
                        {factor.effect_rub === 0 ? '' : factor.effect_rub > 0 ? '+' : '−'}
                        {rubles(Math.abs(factor.effect_rub))}
                        <small>
                          {factor.effect_rub === 0
                            ? 'Без изменения'
                            : factor.effect_rub > 0
                              ? 'Повышает'
                              : 'Снижает'}
                        </small>
                      </strong>
                    </li>
                  ))}
              </ul>
              {!report.factors.length && (
                <p className="section-note">Факторы не предоставлены моделью</p>
              )}
            </section>
            <details className="assumptions">
              <summary>
                Допущения и источники <span>{report.assumptions.length}</span>
              </summary>
              <ul>
                {report.assumptions.map((assumption, index) => (
                  <li key={`${assumption.name}-${index}`}>
                    <strong>{assumption.name}</strong>
                    <span>
                      {typeof assumption.value === 'number'
                        ? decimal(assumption.value)
                        : assumption.value}{' '}
                      {({ share: 'доля', rub: '₽' } as Record<string, string>)[assumption.unit] ||
                        assumption.unit}
                    </span>
                    <Source assumption={assumption} />
                  </li>
                ))}
              </ul>
            </details>
            <section className="report-section">
              <h3>Конкуренты рядом</h3>
              <ul className="nearby-list">
                {report.competitors.map((competitor, index) => (
                  <li key={`${competitor.name}-${index}`}>
                    <span>{competitor.name}</span>
                    <strong>{number(competitor.distance_m)} м</strong>
                  </li>
                ))}
              </ul>
              {!report.competitors.length && (
                <p className="section-note">Рядом не найдено конкурентов в доступных данных</p>
              )}
            </section>
            <section className="bank-actions">
              <span className="eyebrow">СЛЕДУЮЩИЙ ШАГ</span>
              <h3>От места к своему бизнесу</h3>
              {BANK_ACTIONS.map((action, index) => (
                <button
                  key={action}
                  className={index === 0 ? 'primary-button' : ''}
                  onClick={() => onBankAction(action)}
                >
                  {action}
                  <span aria-hidden="true">↗</span>
                </button>
              ))}
            </section>
            {state.calculatedAt && (
              <BusinessPlanButton
                snapshot={{
                  report,
                  calculatedAt: state.calculatedAt,
                  cityName,
                  nicheName,
                  isDemo: useMocks,
                }}
                disabled={pending || invalid || !!error || !state.reportIsCurrent}
              />
            )}
            <p className="report-disclaimer">
              Оценка ориентировочная и не гарантирует финансовый результат. Версия данных{' '}
              {report.data_version}.
            </p>
            {onMethodology && (
              <button className="methodology-link" onClick={onMethodology}>
                Как считается оценка
              </button>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
