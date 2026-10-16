import { useId, type ReactElement } from 'react';
import type { MoneyRange } from '../api/types';
import { assessPlanRevenue, formatRevenue, parsePlanRevenue } from '../creditAssessment';

const CHART_PADDING_FACTOR = 1.12;
const PERCENT_SCALE = 100;
const POSITION_LABELS = {
  below: 'Ниже диапазона',
  within: 'В диапазоне модели',
  above: 'Выше диапазона',
};

export function CreditAssessment({
  range,
  value,
  onChange,
  ready,
}: {
  range: MoneyRange;
  value: string;
  onChange: (value: string) => void;
  ready: boolean;
}): ReactElement {
  const id = useId();
  const input = parsePlanRevenue(value);
  const assessment = ready && input.kind === 'valid' ? assessPlanRevenue(range, input.value) : null;
  const maximum =
    assessment && input.kind === 'valid'
      ? Math.max(range.p90, input.value, 1) * CHART_PADDING_FACTOR
      : 1;
  const position = (amount: number): string => `${(amount / maximum) * PERCENT_SCALE}%`;
  return (
    <section className="credit-assessment" aria-labelledby={`${id}-title`}>
      <h3 id={`${id}-title`}>Кредитный специалист</h3>
      <label htmlFor={`${id}-revenue`}>Выручка в бизнес-плане, ₽/месяц</label>
      <input
        id={`${id}-revenue`}
        type="text"
        inputMode="decimal"
        autoComplete="off"
        placeholder="Например, 3000000"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={input.kind === 'invalid'}
        aria-describedby={`${id}-help`}
      />
      <p className="section-note" id={`${id}-help`}>
        Месячная выручка в рублях. Допустимы ноль, пробелы и дробная часть до двух знаков.
      </p>
      {input.kind === 'invalid' ? (
        <p className="inline-error" role="alert">
          Введите неотрицательную сумму, не более двух знаков после запятой и в пределах точности
          расчёта
        </p>
      ) : !ready ? (
        <p className="section-note" role="status">
          Дождитесь актуального расчёта для проверки плана
        </p>
      ) : input.kind === 'empty' ? (
        <p className="section-note">Введите выручку из бизнес-плана для сравнения с моделью</p>
      ) : assessment && input.kind === 'valid' ? (
        <>
          <div className={`credit-verdict credit-${assessment.kind}`} role="status">
            <strong>{POSITION_LABELS[assessment.kind]}</strong>
            <p>{assessment.message}</p>
          </div>
          <div
            className="revenue-chart"
            role="img"
            aria-label={`Диапазон модели от ${formatRevenue(range.p10)} до ${formatRevenue(range.p90)}, медиана ${formatRevenue(range.p50)}, в плане ${formatRevenue(input.value)}`}
          >
            <div className="revenue-chart-track">
              <span
                className="revenue-chart-range"
                style={{ left: position(range.p10), width: position(range.p90 - range.p10) }}
              />
              <span className="revenue-chart-median" style={{ left: position(range.p50) }} />
              <span className="revenue-chart-plan" style={{ left: position(input.value) }} />
            </div>
            <div className="revenue-chart-scale">
              <span>0 ₽</span>
              <span>{formatRevenue(maximum)}</span>
            </div>
          </div>
          <div className="revenue-chart-legend">
            <span>
              <i className="range-key" />
              Диапазон p10-p90
            </span>
            <span>
              <i className="median-key" />
              Медиана p50
            </span>
            <span>
              <i className="plan-key" />В плане {formatRevenue(input.value)}
            </span>
          </div>
          <dl className="credit-range-values">
            {(['p10', 'p50', 'p90'] as const).map((key) => (
              <div key={key}>
                <dt>{key}</dt>
                <dd>{formatRevenue(range[key])}</dd>
              </div>
            ))}
          </dl>
        </>
      ) : (
        <p className="inline-error" role="alert">
          Модель вернула некорректный диапазон выручки. Повторите расчёт отчёта
        </p>
      )}
    </section>
  );
}
