import type { ReactNode } from 'react';
import type { EconomicsReport, MonthRow, YearRow } from '../api/economicsTypes';
import { decimal, months, rubles, riskLabels } from '../format';
import { CashFlow } from './FinanceCharts';
import { AssumptionSource } from './AssumptionSource';

const missing = 'Нет оценки';
const metric = (value: number | null, format: (amount: number) => string) =>
  value === null ? missing : format(value);
const percent = (value: number) => decimal(Math.round(value * 1000) / 10) + '%';
const period = (value: number | null) =>
  value === null ? 'Не достигнут за горизонт' : months(value);

function Values({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="finance-values">
      {items.map(([name, value]) => (
        <div key={name}>
          <dt>{name}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function Ledger<T extends MonthRow | YearRow>({
  rows,
  columns,
  periodKey,
}: {
  rows: T[];
  columns: [keyof T, string][];
  periodKey: keyof T;
}) {
  return (
    <div className="finance-scroll" tabIndex={0} aria-label="Денежные показатели в рублях">
      <table>
        <thead>
          <tr>
            <th>{periodKey === 'month' ? 'Месяц' : 'Год проекта'}</th>
            {columns.map(([key, name]) => (
              <th key={String(key)}>{name}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row[periodKey])}>
              <th scope="row">{String(row[periodKey])}</th>
              {columns.map(([key]) => (
                <td key={String(key)}>
                  {metric(row[key] as number | null, key === 'dscr' ? decimal : rubles)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
const annual: [keyof YearRow, string][] = [
  ['revenue', 'Выручка'],
  ['operating_costs', 'Операционные расходы'],
  ['ebitda', 'EBITDA'],
  ['depreciation', 'Амортизация'],
  ['ebit', 'Операционная прибыль'],
  ['taxes', 'Налоги'],
  ['interest', 'Проценты'],
  ['principal', 'Основной долг'],
  ['net_profit', 'Чистая прибыль'],
  ['operating_cash_flow', 'Операционный поток'],
];
const monthly: [keyof MonthRow, string][] = [
  ['revenue', 'Выручка'],
  ['cogs', 'Себестоимость'],
  ['rent', 'Аренда'],
  ['payroll', 'Фонд оплаты труда'],
  ['other', 'Прочие расходы'],
  ['taxes', 'Налоги'],
  ['ebitda', 'EBITDA'],
  ['depreciation', 'Амортизация'],
  ['interest', 'Проценты'],
  ['principal', 'Основной долг'],
  ['net_profit', 'Чистая прибыль'],
  ['owner_cash_flow', 'Поток собственника'],
  ['cumulative_project_cash', 'Накопленный поток проекта'],
  ['dscr', 'Покрытие долга'],
];

export function FinanceReport({ report }: { report: EconomicsReport }) {
  const { metrics, credit, tax, investment } = report;
  return (
    <>
      <p>
        Открытие в {String(report.start_month).padStart(2, '0')}.{report.start_year}. Прогноз на{' '}
        {report.horizon_months} месяцев по {report.scenarios} сценариям.
      </p>
      <CashFlow band={report.cash_band} payback={metrics.payback_months.p50} />
      <h4>Показатели проекта</h4>
      <span className={'risk-badge risk-' + metrics.risk_level}>
        {riskLabels[metrics.risk_level]}
      </span>
      <Values
        items={[
          ['Чистая приведённая стоимость (NPV)', rubles(metrics.npv.p50)],
          ['Внутренняя норма доходности (IRR) за год', metric(metrics.irr_annual.p50, percent)],
          ['Простая окупаемость', period(metrics.payback_months.p50)],
          ['Дисконтированная окупаемость', period(metrics.discounted_payback_months.p50)],
          ['Первый прибыльный месяц', period(metrics.first_profit_month.p50)],
          ['Вероятность не окупиться', percent(metrics.probability_no_payback)],
          ['Безубыточная выручка в месяц', metric(metrics.break_even_revenue_month.p50, rubles)],
          [
            'Безубыточность, ' + metrics.unit_name + ' в день',
            metric(metrics.break_even_units_per_day.p50, decimal),
          ],
          ['Запас прочности', metric(metrics.safety_margin.p50, percent)],
        ]}
      />
      <h4>Вложения по статьям</h4>
      <Values
        items={[
          ...investment.items.map((item): [string, string] => [item.name, rubles(item.amount)]),
          ['Итого по медиане', rubles(investment.total.p50)],
        ]}
      />
      <h4>Налоговый режим</h4>
      <strong>{tax.name}</strong>
      <p>{tax.explanation}</p>
      <details>
        <summary>Сравнить налоговые режимы</summary>
        <div className="finance-scroll" tabIndex={0}>
          <table>
            <thead>
              <tr>
                {['Режим', 'Доступность', 'Налоги за горизонт', 'Взносы за горизонт'].map(
                  (label) => (
                    <th key={label}>{label}</th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {tax.options.map((o) => (
                <tr key={o.regime}>
                  <th scope="row">{o.name}</th>
                  <td>{o.eligible ? 'Доступен' : o.reason || 'Недоступен'}</td>
                  <td>{metric(o.taxes_horizon_p50, rubles)}</td>
                  <td>{metric(o.contributions_horizon_p50, rubles)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
      <h4>Кредитная нагрузка</h4>
      <p>{credit.amount > 0 ? credit.product_name || 'Кредит' : 'Без кредита'}</p>
      <Values
        items={[
          ['Сумма кредита', rubles(credit.amount)],
          ['Ставка по расчёту', credit.amount > 0 ? percent(credit.rate_annual) : 'Кредит не взят'],
          ['Срок по расчёту', credit.amount > 0 ? months(credit.term_months) : 'Кредит не взят'],
          ['Первый ежемесячный платёж', rubles(credit.first_payment)],
          ['Переплата по процентам', rubles(credit.total_interest)],
          ['Минимальный DSCR', metric(credit.dscr_min.p50, decimal)],
          [
            'Доля сценариев с DSCR ниже ' + decimal(credit.dscr_threshold),
            credit.amount > 0 ? percent(credit.probability_dscr_below_threshold) : 'Кредит не взят',
          ],
          ['Предельный кредит', rubles(credit.max_loan_rub.p50)],
        ]}
      />
      {report.warnings.length > 0 && (
        <section className="finance-warnings">
          <h4>Предупреждения</h4>
          <ul>
            {report.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </section>
      )}
      <h4>Результаты по годам</h4>
      <Ledger rows={report.years} columns={annual} periodKey="year" />
      <details>
        <summary>Таблица по месяцам</summary>
        <Ledger rows={report.monthly} columns={monthly} periodKey="month" />
      </details>
      <details>
        <summary>Допущения финансовой модели и источники</summary>
        <ul className="finance-assumptions">
          {report.assumptions.map((item, index) => (
            <li key={item.name + index}>
              <strong>{item.name}</strong>
              <span>
                {typeof item.value === 'number' ? decimal(item.value) : item.value} {item.unit}
              </span>
              <AssumptionSource assumption={item} />
            </li>
          ))}
        </ul>
      </details>
    </>
  );
}
