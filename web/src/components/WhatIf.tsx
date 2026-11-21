import { useMemo, useState } from 'react';
import { financeApi } from '../api/economics';
import type { EconomicsReport, EconomicsRequest } from '../api/economicsTypes';
import { useResource } from '../hooks/useEconomics';
import {
  compareScenarios,
  initialNumbers,
  scenarioFields,
  scenarioRequest,
  type ScenarioValues,
} from '../whatIf';

const RECALC_DELAY_MS = 500;
export function WhatIf({ base, body }: { base: EconomicsReport; body: EconomicsRequest }) {
  const [values, setValues] = useState<ScenarioValues>({});
  const defaults = initialNumbers(base, body);
  const changed = Object.keys(values).length > 0;
  const inactiveLoanField = (key: string) =>
    ['rate', 'term', 'grace'].includes(key) && Number(values.share ?? defaults.share) === 0;
  const invalid = scenarioFields.find((field) => {
    if (inactiveLoanField(field.key)) return false;
    const raw = values[field.key];
    if (raw === undefined) return false;
    const n = Number(raw);
    return (
      !Number.isFinite(n) ||
      n < field.min ||
      n > field.max ||
      (['term', 'grace'].includes(field.key) && !Number.isInteger(n))
    );
  });
  const load = useMemo(
    () =>
      changed && !invalid
        ? (signal: AbortSignal) => financeApi.economics(scenarioRequest(body, base, values), signal)
        : null,
    [changed, invalid, body, base, values],
  );
  const result = useResource(load, RECALC_DELAY_MS);
  function update(key: keyof ScenarioValues, value: string) {
    setValues((previous) => {
      const next = { ...previous };
      if (value === '') delete next[key];
      else Object.assign(next, { [key]: value });
      return next;
    });
  }
  const comparison = changed ? result.value : base;
  return (
    <details className="what-if">
      <summary>Что если</summary>
      <p>
        Измените параметры, чтобы сравнить сценарий с исходным расчётом. Пустые поля сохраняют
        исходные условия.
      </p>
      <div className="scenario-fields">
        {scenarioFields.map((f) => (
          <label key={f.key}>
            {f.label}
            <input
              type="number"
              min={f.min}
              max={f.max}
              step={['term', 'grace'].includes(f.key) ? 1 : 'any'}
              placeholder={String(defaults[f.key] ?? 'По модели')}
              value={values[f.key] ?? ''}
              onChange={(e) => update(f.key, e.target.value)}
              aria-invalid={invalid?.key === f.key}
              disabled={inactiveLoanField(f.key)}
            />
            {invalid?.key === f.key && (
              <small role="alert">
                Введите значение от {f.min} до {f.max}
                {['term', 'grace'].includes(f.key) ? ' целыми месяцами' : ''}.
              </small>
            )}
          </label>
        ))}
        <label>
          Налоговый режим
          <select
            value={values.regime ?? body.tax?.regime ?? 'auto'}
            onChange={(e) =>
              update(
                'regime',
                e.target.value === (body.tax?.regime ?? 'auto') ? '' : e.target.value,
              )
            }
          >
            <option value="auto">Автоматический выбор</option>
            {base.tax.options.map((o) => (
              <option key={o.regime} value={o.regime} disabled={!o.eligible}>
                {o.name}
                {!o.eligible ? ' · ' + (o.reason ?? 'Недоступен') : ''}
              </option>
            ))}
          </select>
        </label>
      </div>
      <button type="button" onClick={() => setValues({})} disabled={!changed}>
        Вернуть исходный расчёт
      </button>
      {result.pending && <p role="status">Пересчитываем сценарий…</p>}
      {result.error && (
        <p role="alert">
          {result.error.message} <button onClick={result.retry}>Повторить сценарий</button>
        </p>
      )}
      {comparison && !invalid && (
        <section aria-label="Сравнение сценария">
          <h4>Сравнение с исходным расчётом</h4>
          <div className="scenario-grid">
            <b>Показатель</b>
            <b>Исходный</b>
            <b>Сценарий</b>
            {compareScenarios(base, comparison).map((row) => (
              <div key={row.label} className="scenario-row">
                <strong>{row.label}</strong>
                <span>{row.before}</span>
                <span>{row.after}</span>
                <small>{row.delta}</small>
              </div>
            ))}
          </div>
        </section>
      )}
    </details>
  );
}
