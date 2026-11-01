import { Suspense, lazy, useCallback, useEffect, useState } from 'react';
import { api, useMocks } from './api/client';
import type { CityInfo, Competitor, HexesResponse, NicheInfo } from './api/types';
import { Search } from './components/Search';
import { Legend } from './components/Legend';
import { ReportPanel } from './components/ReportPanel';
import { ComparisonPanel } from './components/ComparisonPanel';
import type { ReportSlot } from './comparison';
import { BankModal } from './components/BankModal';
import { WelcomeToast } from './components/WelcomeToast';
import { Landing } from './components/Landing';
import { MethodologyDialog } from './components/MethodologyDialog';
import { useLocationReport } from './hooks/useLocationReport';
import { message, number, rubles } from './format';
import type { Metric } from './mapStyle';
import { browserStorage, markWelcomeSeen, welcomeSeen } from './welcome';

const MapView = lazy(() =>
  import('./components/MapView').then((module) => ({ default: module.MapView })),
);

export function App() {
  const [cities, setCities] = useState<CityInfo[]>([]);
  const [niches, setNiches] = useState<NicheInfo[]>([]);
  const [cityCode, setCityCode] = useState('moscow');
  const [nicheCode, setNicheCode] = useState('coffee');
  const [hexes, setHexes] = useState<HexesResponse>();
  const [competitors, setCompetitors] = useState<Competitor[]>([]);
  const [metric, setMetric] = useState<Metric>('revenue');
  const [showCompetitors, setShowCompetitors] = useState(false);
  const [error, setError] = useState('');
  const [bootError, setBootError] = useState('');
  const [version, setVersion] = useState('');
  const [reload, setReload] = useState(0);
  const [bankAction, setBankAction] = useState<string | null>(null);
  const [creditMode, setCreditMode] = useState(false);
  const [methodologyOpen, setMethodologyOpen] = useState(false);
  const reportState = useLocationReport(cityCode, nicheCode);
  const [welcomeOpen, setWelcomeOpen] = useState(() => !welcomeSeen(browserStorage()));
  const closeWelcome = useCallback(() => {
    markWelcomeSeen(browserStorage());
    setWelcomeOpen(false);
  }, []);
  const readAbout = useCallback(() => {
    closeWelcome();
    window.history.replaceState(null, '', window.location.pathname);
    window.scrollTo({ top: 0 });
  }, [closeWelcome]);
  const secondReportState = useLocationReport(cityCode, nicheCode);
  const [comparisonEnabled, setComparisonEnabled] = useState(false);
  const [activeSlot, setActiveSlot] = useState<ReportSlot>('first');
  const activeReport =
    comparisonEnabled && activeSlot === 'second' ? secondReportState : reportState;
  const reportPending = reportState.pending || secondReportState.pending;
  function stopComparison(): void {
    setComparisonEnabled(false);
    setActiveSlot('first');
    secondReportState.close();
  }
  const city = cities.find((item) => item.code === cityCode);
  const niche = niches.find((item) => item.code === nicheCode);

  useEffect(() => {
    let active = true;
    setBootError('');
    void Promise.all([api.cities(), api.niches(), api.health()])
      .then(([nextCities, nextNiches, health]) => {
        if (!active) return;
        if (!nextCities.length || !nextNiches.length)
          throw new Error('Список городов или ниш пуст');
        setCities(nextCities);
        setNiches(nextNiches);
        setVersion(health.data_version);
        setCityCode((current) =>
          nextCities.some((item) => item.code === current) ? current : nextCities[0].code,
        );
        setNicheCode((current) =>
          nextNiches.some((item) => item.code === current) ? current : nextNiches[0].code,
        );
      })
      .catch((cause: unknown) => {
        if (active) setBootError(message(cause));
      });
    return () => {
      active = false;
    };
  }, [reload]);
  useEffect(() => {
    if (!city || !niche) return;
    const controller = new AbortController();
    setHexes(undefined);
    setCompetitors([]);
    setError('');
    void Promise.all([
      api.hexes(city.code, niche.code, controller.signal),
      api.competitors(city.code, niche.code, controller.signal),
    ])
      .then(([response, points]) => {
        if (!controller.signal.aborted) {
          setHexes(response);
          setCompetitors(points);
          setVersion(response.data_version);
        }
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) setError(message(cause));
      });
    return () => controller.abort();
  }, [city, niche, reload]);
  const data = hexes?.city === cityCode && hexes.niche === nicheCode ? hexes : undefined;
  const revenues = data?.items.map((item) => item.revenue_p50).sort((a, b) => a - b);
  const median = revenues?.[Math.floor(revenues.length / 2)];
  const currentError = bootError || error;

  return (
    <div className="app">
      <header className="header">
        <a className="brand" href="/" aria-label="ГеоСтарт, главная">
          <span className="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 40 40" width="32" height="32">
              <path
                d="m20 7 11 6.5v13L20 33 9 26.5v-13Z"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              />
              <circle cx="20" cy="20" r="5" fill="#00aeef" />
            </svg>
          </span>
          ГеоСтарт<span className="brand-note">Место имеет значение</span>
        </a>
        <nav className="header-nav" aria-label="Разделы">
          <a href="#how">Как работает</a>
          <a href="#proof">Точность</a>
          <a href="#bank">Для банка</a>
          <a href="#map">Карта</a>
        </nav>
        <div className="header-actions">
          <button className="header-methodology" onClick={() => setMethodologyOpen(true)}>
            Как считается оценка
          </button>
          <button
            className="credit-mode-toggle"
            aria-pressed={creditMode}
            onClick={() => setCreditMode((enabled) => !enabled)}
          >
            Кредитный специалист
          </button>
          {useMocks && <span className="pilot-label">Демонстрация · Москва, кофейня</span>}
          <a className="primary-button button-link header-cta" href="#map">
            Открыть карту
          </a>
        </div>
      </header>
      <Landing onCreditMode={() => setCreditMode(true)} />
      <section id="map" className="tool" aria-label="Карта и отчёт">
        <div className="toolbar" aria-label="Настройки карты">
          <label className="select-field">
            <span className="field-label">Город</span>
            <select
              aria-label="Город"
              value={cityCode}
              onChange={(event) => {
                setCityCode(event.target.value);
                stopComparison();
              }}
              disabled={!cities.length}
            >
              {cities.map((item) => (
                <option key={item.code} value={item.code}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <label className="select-field niche-field">
            <span className="field-label">Бизнес</span>
            <select
              aria-label="Бизнес"
              value={nicheCode}
              onChange={(event) => {
                setNicheCode(event.target.value);
                stopComparison();
              }}
              disabled={!niches.length}
            >
              {niches.map((item) => (
                <option key={item.code} value={item.code}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <Search
            key={`${cityCode}-${nicheCode}-${comparisonEnabled ? activeSlot : 'single'}`}
            city={cityCode}
            disabled={reportPending || !data}
            onSelect={activeReport.select}
          />
          <div className="metric-field">
            <span className="field-label">Показать на карте</span>
            <div className="metric-toggle" role="group" aria-label="Метрика карты">
              <button aria-pressed={metric === 'revenue'} onClick={() => setMetric('revenue')}>
                Выручка
              </button>
              <button aria-pressed={metric === 'payback'} onClick={() => setMetric('payback')}>
                Окупаемость
              </button>
            </div>
          </div>
        </div>
        <main
          className={`workspace${reportState.location ? ' has-report' : ''}${comparisonEnabled ? ' is-comparing' : ''}`}
        >
          <aside className="intro-panel">
            <p className="eyebrow">ОТКРЫВАЙТЕ С ПОНИМАНИЕМ</p>
            <h1>
              Найдите место
              <br />
              для своего дела
            </h1>
            <p className="intro-copy">
              Оцените будущую выручку и окупаемость бизнеса до того, как подпишете договор аренды.
            </p>
            <div className="map-instruction">
              <span className="instruction-number">01</span>
              <p>Выберите участок на карте или найдите адрес, чтобы получить оценку.</p>
            </div>
            <div className="stat-block">
              <span>Участков на карте</span>
              <strong>{data ? number(data.items.length) : '…'}</strong>
            </div>
            <div className="stat-block">
              <span>Медиана выручки по городу</span>
              <strong>
                {median === undefined ? '…' : rubles(median)}
                <small>/ месяц</small>
              </strong>
            </div>
            <div className="stat-block">
              <span>Конкурентов в доступных данных</span>
              <strong>{data ? number(competitors.length) : '…'}</strong>
            </div>
            <p className="footnote">
              Прогноз основан на открытых данных. Значения ориентировочные и зависят от допущений
              модели.
            </p>
          </aside>
          <section className="map-region" aria-label="Карта прогноза">
            {reportState.location && (
              <a
                className="skip-map"
                href={comparisonEnabled ? `#report-${activeSlot}-title` : '#report-title'}
              >
                Перейти к отчёту
              </a>
            )}
            {city && (
              <Suspense
                fallback={
                  <div className="map-status" role="status">
                    <span className="spinner" />
                    Загружаем карту
                  </div>
                }
              >
                <MapView
                  city={city}
                  items={data?.items || []}
                  competitors={data && showCompetitors ? competitors : []}
                  metric={metric}
                  selected={activeReport.location}
                  disabled={reportPending || !data}
                  onSelect={activeReport.select}
                />
              </Suspense>
            )}
            <div className="map-heading">
              <span className="eyebrow">{useMocks ? 'ДЕМОНСТРАЦИЯ' : 'ПРОГНОЗ НА КАРТЕ'}</span>
              <h2>{city?.name || 'Загружаем карту'}</h2>
              <span>
                {niche?.name} · {metric === 'revenue' ? 'выручка в месяц' : 'окупаемость'}
              </span>
            </div>
            <label className="competitors-toggle">
              <input
                type="checkbox"
                checked={showCompetitors}
                onChange={(event) => setShowCompetitors(event.target.checked)}
              />
              <span className="competitor-dot" />
              Конкуренты{data ? ` · ${number(competitors.length)}` : ''}
            </label>
            {!data && !currentError && (
              <div className="map-status" role="status">
                <span className="spinner" />
                Загружаем прогноз
              </div>
            )}
            {currentError && (
              <div className="map-status error" role="alert">
                <strong>Данные недоступны</strong>
                <p>{currentError}</p>
                <button onClick={() => setReload((value) => value + 1)}>Повторить</button>
              </div>
            )}
            {data && !data.items.length && (
              <div className="map-status" role="status">
                Для этого города и ниши пока нет ячеек
              </div>
            )}
            {data && <Legend items={data.items} metric={metric} />}
            <div className="map-hint" role="status">
              {reportPending
                ? 'Рассчитываем отчёт…'
                : comparisonEnabled
                  ? `Выберите адрес ${activeSlot === 'first' ? '1' : '2'} для сравнения`
                  : 'Нажмите на участок для оценки'}
            </div>
          </section>
          {comparisonEnabled ? (
            <ComparisonPanel
              creditMode={creditMode}
              first={reportState}
              second={secondReportState}
              activeSlot={activeSlot}
              onSelectSlot={setActiveSlot}
              onClose={stopComparison}
              onBankAction={setBankAction}
              cityName={city?.name || cityCode}
              nicheName={niche?.name || nicheCode}
            />
          ) : reportState.location ? (
            <ReportPanel
              creditMode={creditMode}
              state={reportState}
              onBankAction={setBankAction}
              onMethodology={() => setMethodologyOpen(true)}
              cityName={city?.name || cityCode}
              nicheName={niche?.name || nicheCode}
              onCompare={() => {
                setComparisonEnabled(true);
                setActiveSlot('second');
              }}
            />
          ) : null}
        </main>
      </section>
      <footer className="footer">
        <span>Simply Lovely · ГеоСтарт</span>
        <span>
          {useMocks ? 'Демонстрационные данные' : 'Открытые данные'}
          {version ? ` · версия ${version}` : ''}
        </span>
      </footer>
      {bankAction && <BankModal action={bankAction} onClose={() => setBankAction(null)} />}
      {welcomeOpen && <WelcomeToast onClose={closeWelcome} onReadAbout={readAbout} />}
      {methodologyOpen && (
        <MethodologyDialog version={version} onClose={() => setMethodologyOpen(false)} />
      )}
    </div>
  );
}
