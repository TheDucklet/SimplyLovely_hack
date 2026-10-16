import type { ReactElement } from 'react';
import type { useLocationReport } from '../hooks/useLocationReport';
import { compareReports, type ReportSlot } from '../comparison';
import { ReportPanel } from './ReportPanel';

type ReportState = ReturnType<typeof useLocationReport>;

function reportAddress(state: ReportState): string {
  return (
    state.report?.location.address ||
    state.location?.address ||
    (state.location
      ? `${state.location.lat.toFixed(5)}, ${state.location.lon.toFixed(5)}`
      : 'Выберите на карте или найдите через поиск')
  );
}

function ready(state: ReportState): boolean {
  return (
    !!state.report && state.reportIsCurrent && !state.pending && !state.error && !state.invalid
  );
}

export function ComparisonPanel({
  first,
  second,
  activeSlot,
  onSelectSlot,
  onClose,
  onBankAction,
  cityName,
  nicheName,
}: {
  first: ReportState;
  second: ReportState;
  activeSlot: ReportSlot;
  onSelectSlot: (slot: ReportSlot) => void;
  onClose: () => void;
  onBankAction: (action: string) => void;
  cityName: string;
  nicheName: string;
}): ReactElement {
  const compatible =
    first.report?.city === second.report?.city &&
    first.report?.niche === second.report?.niche &&
    first.report?.data_version === second.report?.data_version;
  const metrics =
    first.report && second.report && ready(first) && ready(second) && compatible
      ? compareReports(first.report, second.report)
      : null;
  return (
    <section className="comparison-panel" aria-label="Сравнение двух адресов">
      <div className="comparison-overview">
        <header className="comparison-heading">
          <h2>Сравнение адресов</h2>
          <button onClick={onClose}>Завершить сравнение</button>
        </header>
        <div className="comparison-slots" role="group" aria-label="Выбор адреса для карты и поиска">
          {(['first', 'second'] as const).map((slot, index) => (
            <button
              key={slot}
              aria-pressed={activeSlot === slot}
              onClick={() => onSelectSlot(slot)}
            >
              <strong>Адрес {index + 1}</strong>
              <span>{reportAddress(slot === 'first' ? first : second)}</span>
            </button>
          ))}
        </div>
        <p className="section-note">
          Карта и поиск выбирают адрес {activeSlot === 'first' ? '1' : '2'}. Площадь и аренда
          задаются отдельно в каждом отчёте. Разница посчитана по показанным округлённым значениям.
        </p>
        {metrics ? (
          <table className="comparison-table">
            <caption>Разница = адрес 2 минус адрес 1</caption>
            <thead>
              <tr>
                <th scope="col">Показатель</th>
                <th scope="col">Адрес 1</th>
                <th scope="col">Адрес 2</th>
                <th scope="col">Разница</th>
              </tr>
            </thead>
            <tbody>
              {metrics.map((metric) => (
                <tr key={metric.label}>
                  <th scope="row">{metric.label}</th>
                  <td>{metric.first}</td>
                  <td>{metric.second}</td>
                  <td className={metric.tone}>
                    <strong>{metric.difference}</strong>
                    {metric.direction && <small>{metric.direction}</small>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="comparison-status" role="status">
            {!first.location || !second.location
              ? 'Выберите оба адреса для сравнения'
              : !ready(first) || !ready(second)
                ? 'Сравнение появится после успешного расчёта обоих адресов с текущими параметрами'
                : 'Для сравнения нужны один город, одна ниша и одна версия данных. Пересчитайте оба адреса'}
          </p>
        )}
      </div>
      <div className="comparison-reports">
        <ReportPanel
          state={first}
          cityName={cityName}
          nicheName={nicheName}
          onBankAction={onBankAction}
          heading="Отчёт 1"
          titleId="report-first-title"
          onClose={() => {
            first.close();
            onClose();
          }}
        />
        {second.location ? (
          <ReportPanel
            state={second}
            cityName={cityName}
            nicheName={nicheName}
            onBankAction={onBankAction}
            heading="Отчёт 2"
            titleId="report-second-title"
            onClose={onClose}
          />
        ) : (
          <aside className="comparison-empty" aria-labelledby="report-second-title">
            <h2 id="report-second-title">Отчёт 2</h2>
            <p>
              Выберите второй адрес на карте или найдите его в поиске. Первый отчёт сохранится
              рядом.
            </p>
          </aside>
        )}
      </div>
    </section>
  );
}
