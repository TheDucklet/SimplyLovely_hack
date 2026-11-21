import { useEffect, useId, useMemo, useRef, useState, type FormEvent } from 'react';
import { financeApi } from '../api/economics';
import type {
  CreditCheckReport,
  CreditCheckRequest,
  EconomicsRequest,
} from '../api/economicsTypes';
import {
  borrowerPlan,
  checkCells,
  checkHeaders,
  coverageLabel,
  coverageValue,
  emptyPlan,
  planFields,
  verdictLabels,
  type PlanDraft,
} from '../borrowerPlan';
import { useResource, type useEconomics } from '../hooks/useEconomics';
import { rubles } from '../format';
import { FinanceReport } from './FinanceReport';
import './borrowerReview.css';

type Products = ReturnType<typeof useEconomics>['products'];
function Conclusion({ report, place }: { report: CreditCheckReport; place: string }) {
  const details = useRef<HTMLDetailsElement>(null);
  const title = useRef<HTMLHeadingElement>(null);
  const id = useId();
  const [exporting, setExporting] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    title.current?.focus();
  }, [report]);
  async function download(): Promise<void> {
    setExporting(true);
    setFailed(false);
    try {
      const { downloadConclusion } = await import('../businessPlan/creditConclusion');
      await downloadConclusion(report, place);
    } catch {
      setFailed(true);
    } finally {
      setExporting(false);
    }
  }
  return (
    <section className="credit-conclusion" aria-label="Заключение по бизнес-плану">
      <header>
        <h3 ref={title} tabIndex={-1} className={'verdict ' + report.verdict}>
          {verdictLabels[report.verdict]}
        </h3>
        <button onClick={download} disabled={exporting}>
          {exporting ? 'Готовим PDF…' : 'Скачать заключение'}
        </button>
      </header>
      {failed && <p role="alert">Не удалось сохранить PDF. Повторите скачивание.</p>}
      <ul>
        {report.summary.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      <div
        className="finance-scroll"
        tabIndex={0}
        role="region"
        aria-label="Сравнение плана с моделью"
      >
        <table>
          <thead>
            <tr>
              {checkHeaders.map((text) => (
                <th scope="col" key={text}>
                  {text}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {report.checks.map((check) => {
              const [name, ...cells] = checkCells(check);
              return (
                <tr key={check.code}>
                  <th scope="row">{name}</th>
                  {cells.map((text, i) => (
                    <td key={checkHeaders[i + 1]}>{text}</td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <a
        href={'#' + id}
        onClick={(event) => {
          event.preventDefault();
          if (details.current) {
            details.current.open = true;
            details.current.scrollIntoView({ block: 'start' });
            details.current.querySelector('summary')?.focus({ preventScroll: true });
          }
        }}
      >
        Перейти к полной финансовой модели
      </a>
      <dl className="finance-values">
        <div>
          <dt>{coverageLabel(report)}</dt>
          <dd>{coverageValue(report)}</dd>
        </div>
        <div>
          <dt>Предельный кредит модели (p50)</dt>
          <dd>{rubles(report.max_loan_rub.p50)}</dd>
        </div>
      </dl>
      <details ref={details} id={id}>
        <summary>Финансовая модель проверки</summary>
        <FinanceReport report={report.economics} />
      </details>
    </section>
  );
}

export function BorrowerReview({
  economics,
  products,
  place,
}: {
  economics: EconomicsRequest | null;
  products: Products;
  place: string;
}) {
  const [draft, setDraft] = useState<PlanDraft>(emptyPlan);
  const [submission, setSubmission] = useState<CreditCheckRequest | null>(null);
  const load = useMemo(
    () =>
      submission && submission.economics === economics
        ? (signal: AbortSignal) => financeApi.creditCheck(submission, signal)
        : null,
    [submission, economics],
  );
  const check = useResource(load);
  function edit(name: keyof PlanDraft, value: string): void {
    setSubmission(null);
    setDraft((old) => ({ ...old, [name]: value }));
  }
  function submit(event: FormEvent): void {
    event.preventDefault();
    if (economics && !check.pending) setSubmission({ economics, plan: borrowerPlan(draft) });
  }
  function errorFor(field: string) {
    return check.error?.errors.find((issue) => issue.field === 'plan.' + field)?.message;
  }
  return (
    <section className="credit-screen finance-block" aria-label="Параметры бизнес-плана">
      <form onSubmit={submit}>
        <fieldset>
          <legend>Показатели из бизнес-плана</legend>
          <p>Введите выручку и сумму кредита. Остальные поля уточняют проверку.</p>
          <div className="plan-inputs">
            {planFields.map((field) => (
              <label key={field.key}>
                {field.label}
                <input
                  type="number"
                  min={field.min}
                  max={field.max}
                  step={field.step}
                  value={draft[field.key]}
                  required={'required' in field}
                  onChange={(e) => edit(field.key, e.target.value)}
                  aria-invalid={!!errorFor(field.key)}
                />
                {errorFor(field.key) && <small>{errorFor(field.key)}</small>}
              </label>
            ))}
            <label>
              Кредитный продукт
              <select
                aria-label="Кредитный продукт"
                value={draft.product}
                onChange={(e) => edit('product', e.target.value)}
              >
                <option value="">Без выбора продукта</option>
                {products.value?.map((product) => (
                  <option value={product.code} key={product.code}>
                    {product.name}
                  </option>
                ))}
              </select>
              {errorFor('product') && <small>{errorFor('product')}</small>}
            </label>
          </div>
          {products.error && (
            <p role="alert">
              {products.error.message}{' '}
              <button type="button" onClick={products.retry}>
                Повторить загрузку продуктов
              </button>
            </p>
          )}
          <button type="submit" className="review-submit" disabled={!economics || check.pending}>
            {check.pending ? 'Проверяем план…' : 'Проверить бизнес-план'}
          </button>
        </fieldset>
      </form>
      {check.error && <p role="alert">{check.error.message}</p>}
      {check.value && <Conclusion report={check.value} place={place} />}
    </section>
  );
}
