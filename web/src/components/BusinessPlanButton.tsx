import { useState, type ReactElement } from 'react';
import type { BusinessPlanSnapshot } from '../businessPlan/definition';

export function BusinessPlanButton({
  snapshot,
  disabled,
}: {
  snapshot: BusinessPlanSnapshot;
  disabled: boolean;
}): ReactElement {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [downloadedAt, setDownloadedAt] = useState<string | null>(null);
  async function download(): Promise<void> {
    if (loading || disabled) return;
    setLoading(true);
    setError('');
    setDownloadedAt(null);
    const frozen = structuredClone(snapshot);
    try {
      const { downloadBusinessPlan } = await import('../businessPlan/download');
      await downloadBusinessPlan(frozen);
      setDownloadedAt(frozen.calculatedAt);
    } catch {
      setError('Не удалось подготовить PDF. Повторите скачивание');
    } finally {
      setLoading(false);
    }
  }
  return (
    <section className="business-plan-export" aria-label="Черновик бизнес-плана">
      <button disabled={disabled || loading} onClick={() => void download()}>
        {loading ? (
          <>
            <span className="spinner" />
            Готовим PDF…
          </>
        ) : (
          'Скачать черновик бизнес-плана'
        )}
      </button>
      {disabled && !loading && <p className="section-note">Дождитесь актуального расчёта</p>}
      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
      {!disabled && downloadedAt === snapshot.calculatedAt && (
        <p className="section-note" role="status">
          PDF готов
        </p>
      )}
    </section>
  );
}
