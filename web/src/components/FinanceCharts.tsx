import type { CashBand, SensitivityReport } from '../api/economicsTypes';
import { decimal, months, rubles } from '../format';
import { mockSensitivity } from '../api/economics';

const CHART_WIDTH = 320;
const CHART_HEIGHT = 156;
const INSET = 12;

export function CashFlow({ band, payback }: { band: CashBand[]; payback: number | null }) {
  if (!band.length) return <p>Нет данных о денежном потоке.</p>;
  const first = band[0].month;
  const last = band[band.length - 1].month;
  const min = Math.min(0, ...band.map((row) => row.p10));
  const max = Math.max(0, ...band.map((row) => row.p90));
  const x = (month: number) =>
    INSET + ((month - first) * (CHART_WIDTH - 2 * INSET)) / Math.max(1, last - first);
  const y = (amount: number) =>
    CHART_HEIGHT - INSET - ((amount - min) * (CHART_HEIGHT - 2 * INSET)) / (max - min || 1);
  const points = (rows: CashBand[], key: 'p10' | 'p50' | 'p90') =>
    rows.map((row) => x(row.month) + ',' + y(row[key])).join(' ');
  const marker = payback === null ? null : Math.min(last, Math.max(first, payback));
  return (
    <figure className="cash-chart">
      <figcaption>
        <strong>Накопленный денежный поток</strong>
        <span>Линия показывает медиану, полоса – диапазон p10-p90.</span>
      </figcaption>
      <p>{rubles(max)}</p>
      <svg
        viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
        role="img"
        aria-label="Денежный поток проекта по месяцам, рубли"
      >
        <polygon
          fill="#d7e7f8"
          points={points(band, 'p90') + ' ' + points([...band].reverse(), 'p10')}
        />
        <line
          x1={INSET}
          x2={CHART_WIDTH - INSET}
          y1={y(0)}
          y2={y(0)}
          stroke="#536379"
          strokeDasharray="4 3"
        />
        <polyline points={points(band, 'p50')} fill="none" stroke="#0a4282" strokeWidth="3" />
        {marker !== null && (
          <g>
            <line
              x1={x(marker)}
              x2={x(marker)}
              y1={INSET}
              y2={CHART_HEIGHT - INSET}
              stroke="#863a0b"
              strokeDasharray="3 3"
            />
            <circle cx={x(marker)} cy={y(0)} r="4" fill="#863a0b" />
            <text
              x={x(marker) + (marker > last / 2 ? -5 : 5)}
              y={INSET + 9}
              textAnchor={marker > last / 2 ? 'end' : 'start'}
              fill="#542503"
              fontSize="12"
            >
              {months(payback)}
            </text>
          </g>
        )}
      </svg>
      <p>{rubles(min)}</p>
      <div className="chart-axis">
        <span>Месяц {first}</span>
        <span>Месяц {last}</span>
      </div>
      <p>
        {payback === null
          ? 'Вложения не окупаются за 36 месяцев в половине сценариев.'
          : 'Возврат вложений через ' + months(payback)}
      </p>
      <details>
        <summary>Значения графика по месяцам</summary>
        <div className="finance-scroll" tabIndex={0}>
          <table>
            <thead>
              <tr>
                {['Месяц', 'p10, ₽', 'Медиана, ₽', 'p90, ₽'].map((label) => (
                  <th key={label}>{label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {band.map((row) => (
                <tr key={row.month}>
                  <th>{row.month}</th>
                  <td>{rubles(row.p10)}</td>
                  <td>{rubles(row.p50)}</td>
                  <td>{rubles(row.p90)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}

export function Sensitivity({ data }: { data: SensitivityReport }) {
  const base = data.base.profit_steady_month_p50;
  const rows = data.factors.map((f) => ({
    ...f,
    lower: f.low.profit_steady_month_p50 - base,
    upper: f.high.profit_steady_month_p50 - base,
  }));
  const limit = Math.max(1, ...rows.flatMap((row) => [Math.abs(row.lower), Math.abs(row.upper)]));
  return (
    <section className="sensitivity">
      <h4>Чувствительность прибыли</h4>
      {mockSensitivity && (
        <p className="finance-demo">
          Демонстрационный пример. Числа в диаграмме и стресс-сценариях условные.
        </p>
      )}
      <p>
        Изменение прибыли типового месяца относительно {rubles(base)} при изменении каждого фактора
        на {decimal(data.shift_share * 100)}%.
      </p>
      {rows.map((row) => (
        <div className="tornado-factor" key={row.code}>
          <strong>{row.name}</strong>
          {[
            { label: 'Снижение', value: row.lower },
            { label: 'Рост', value: row.upper },
          ].map(({ label, value }) => (
            <div key={label} className="tornado-row">
              <span>{label}</span>
              <div className="tornado-track" aria-hidden="true">
                <i
                  style={{
                    left: (value < 0 ? 50 - (50 * Math.abs(value)) / limit : 50) + '%',
                    width: (50 * Math.abs(value)) / limit + '%',
                    background: label === 'Рост' ? '#0a4282' : '#945113',
                  }}
                />
              </div>
              <span>
                {value > 0 ? '+' : ''}
                {rubles(value)}
              </span>
            </div>
          ))}
        </div>
      ))}
      <h4>Стресс-сценарии</h4>
      <div className="finance-scroll" tabIndex={0} aria-label="Стресс-сценарии">
        <table>
          <thead>
            <tr>
              {[
                'Сценарий',
                'Прибыль месяца',
                'NPV',
                'Окупаемость',
                'Без окупаемости за 24 месяца',
              ].map((label) => (
                <th key={label}>{label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.stresses.map((s) => (
              <tr key={s.code}>
                <th scope="row">{s.name}</th>
                <td>{rubles(s.profit_steady_month_p50)}</td>
                <td>{rubles(s.npv_p50)}</td>
                <td>{months(s.payback_months_p50)}</td>
                <td>{decimal(s.probability_no_payback_24 * 100)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
