import { useState, type FormEvent } from 'react';
import type { Financing } from '../api/economicsTypes';
import { useMocks } from '../api/client';
import type { useEconomics } from '../hooks/useEconomics';
import { Sensitivity } from './FinanceCharts';
import { FinanceReport } from './FinanceReport';
import './finance.css';

type FinanceState = ReturnType<typeof useEconomics>;
function CreditForm({ state }: { state: FinanceState }) {
  const saved = state.financing;
  const [product, setProduct] = useState(saved?.product ?? '');
  const [share, setShare] = useState(String((saved?.loan_share ?? 0.5) * 100));
  const [rate, setRate] = useState(
    saved?.rate_annual == null ? '' : String(saved.rate_annual * 100),
  );
  const [term, setTerm] = useState(saved?.term_months == null ? '' : String(saved.term_months));
  const chosen = state.products.value?.find((item) => item.code === product);
  function apply(event: FormEvent): void {
    event.preventDefault();
    const financing: Financing | null = product
      ? {
          product,
          loan_share: Number(share) / 100,
          rate_annual: rate === '' ? null : Number(rate) / 100,
          term_months: term === '' ? null : Number(term),
        }
      : null;
    state.setFinancing((previous) =>
      JSON.stringify(previous) === JSON.stringify(financing) ? previous : financing,
    );
  }
  const fields = [
    {
      name: 'loan_share',
      label: 'Доля кредита во вложениях, %',
      value: share,
      set: setShare,
      min: 0,
      max: 100,
      required: true,
      placeholder: '',
    },
    {
      name: 'rate_annual',
      label: 'Годовая ставка, %',
      value: rate,
      set: setRate,
      min: 0,
      max: 100,
      placeholder: chosen ? String(chosen.rate_annual.value * 100) : '',
    },
    {
      name: 'term_months',
      label: 'Срок кредита, мес.',
      value: term,
      set: setTerm,
      min: 1,
      max: 360,
      placeholder: 'По условиям продукта',
    },
  ];
  return (
    <form onSubmit={apply} className="finance-form">
      <fieldset disabled={state.economics.pending}>
        <legend>Условия кредита</legend>
        <label>
          Кредитный продукт
          <select value={product} onChange={(e) => setProduct(e.target.value)}>
            <option value="">Без кредита</option>
            {state.products.value?.map((item) => (
              <option key={item.code} value={item.code}>
                {item.name}
              </option>
            ))}
          </select>
          <small>{state.fieldError('financing.product')}</small>
        </label>
        {product &&
          fields.map((field) => (
            <label key={field.name}>
              {field.label}
              <input
                type="number"
                step={field.name === 'term_months' ? 1 : 'any'}
                min={field.min}
                max={field.max}
                required={field.required}
                value={field.value}
                placeholder={field.placeholder}
                onChange={(e) => field.set(e.target.value)}
                aria-invalid={!!state.fieldError('financing.' + field.name)}
              />
              <small>{state.fieldError('financing.' + field.name)}</small>
            </label>
          ))}
        <button type="submit">Применить условия</button>
      </fieldset>
    </form>
  );
}
export function FinancePanel({
  state,
  cityName,
  nicheName,
  invalid,
}: {
  state: FinanceState;
  cityName: string;
  nicheName: string;
  invalid: boolean;
}) {
  const { economics, sensitivity, products } = state;
  return (
    <section className="finance-block" aria-label="Финансовая модель">
      <header>
        <h3>Финансовая модель</h3>
        <p>
          {cityName} · {nicheName}
        </p>
      </header>
      {useMocks ? (
        <p>В автономном примере доступен отчёт по месту. Для финансового расчёта запустите API.</p>
      ) : (
        <>
          <CreditForm state={state} />
          {products.error && (
            <p role="alert">
              {products.error.message}{' '}
              <button onClick={products.retry}>Загрузить продукты повторно</button>
            </p>
          )}
          {invalid ? (
            <p>Исправьте параметры помещения для расчёта.</p>
          ) : (
            <>
              {economics.pending && (
                <p role="status">
                  <span className="spinner" /> Рассчитываем финансовую модель…
                </p>
              )}
              {economics.error && (
                <p role="alert">
                  {economics.error.message}{' '}
                  <button onClick={economics.retry}>Повторить финансовый расчёт</button>
                </p>
              )}
              {economics.value && <FinanceReport report={economics.value} />}
              {sensitivity.pending && <p role="status">Рассчитываем чувствительность…</p>}
              {sensitivity.error && (
                <p role="alert">
                  Анализ чувствительности. {sensitivity.error.message}{' '}
                  <button onClick={sensitivity.retry}>Повторить анализ</button>
                </p>
              )}
              {sensitivity.value && <Sensitivity data={sensitivity.value} />}
            </>
          )}
        </>
      )}
    </section>
  );
}
