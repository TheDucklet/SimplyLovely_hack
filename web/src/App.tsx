import { useEffect, useState } from 'react';
import { api, useMocks } from './api/client';
import type { CityInfo, HexesResponse, NicheInfo } from './api/types';
import { MapView } from './components/MapView';
import { message, number, rubles } from './format';

export function App() {
  const [city, setCity] = useState<CityInfo>();
  const [niche, setNiche] = useState<NicheInfo>();
  const [hexes, setHexes] = useState<HexesResponse>();
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([api.cities(), api.niches(), api.health()])
      .then(async ([cities, niches]) => {
        if (controller.signal.aborted) return;
        const initialCity = cities.find((item) => item.code === 'moscow') || cities[0];
        const initialNiche = niches.find((item) => item.code === 'coffee') || niches[0];
        if (!initialCity || !initialNiche) throw new Error('Список городов или ниш пуст');
        setCity(initialCity);
        setNiche(initialNiche);
        setError('');
        const response = await api.hexes(initialCity.code, initialNiche.code, controller.signal);
        if (!controller.signal.aborted) setHexes(response);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setError(message(error));
      });
    return () => controller.abort();
  }, [reload]);

  const revenues = hexes?.items.map((item) => item.revenue_p50).sort((left, right) => left - right);
  const median = revenues?.[Math.floor(revenues.length / 2)];

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
              <circle cx="20" cy="20" r="5" fill="#e8945e" />
            </svg>
          </span>
          ГеоСтарт<span className="brand-note">Место имеет значение</span>
        </a>
        <span className="pilot-label">Пилот для малого бизнеса</span>
      </header>
      <main className="workspace">
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
          <div className="selection-summary">
            <span>Город</span>
            <strong>{city?.name || 'Загрузка'}</strong>
            <span>Бизнес</span>
            <strong>{niche?.name || 'Загрузка'}</strong>
          </div>
          <div className="stat-block">
            <span>Участков на карте</span>
            <strong>{hexes ? number(hexes.items.length) : '…'}</strong>
          </div>
          <div className="stat-block">
            <span>Медиана выручки по городу</span>
            <strong>
              {median === undefined ? '…' : rubles(median)}
              <small>/ месяц</small>
            </strong>
          </div>
          <p className="footnote">
            Прогноз основан на открытых данных. Значения ориентировочные и зависят от допущений
            модели.
          </p>
        </aside>
        <section className="map-region" aria-label="Карта прогноза выручки">
          {city && <MapView city={city} items={hexes?.items || []} />}
          <div className="map-heading">
            <span className="eyebrow">ПРОГНОЗ НА КАРТЕ</span>
            <h2>{city?.name || 'Загружаем карту'}</h2>
            <span>{niche?.name} · выручка в месяц</span>
          </div>
          {!hexes && !error && (
            <div className="map-status" role="status">
              <span className="spinner" />
              Загружаем прогноз
            </div>
          )}
          {error && (
            <div className="map-status error" role="alert">
              <strong>Данные недоступны</strong>
              <p>{error}</p>
              <button onClick={() => setReload((value) => value + 1)}>Повторить</button>
            </div>
          )}
          {revenues && revenues.length > 0 && (
            <div className="legend">
              <strong>Выручка, ₽ / месяц</strong>
              <div className="legend-gradient" />
              <div className="legend-labels">
                <span>{number(revenues[0])}</span>
                <span>{number(revenues[revenues.length - 1])}</span>
              </div>
              <small>От меньшей к большей внутри города</small>
            </div>
          )}
        </section>
      </main>
      <footer className="footer">
        <span>Simply Lovely · ГеоСтарт</span>
        <span>
          {useMocks ? 'Демонстрационные данные' : 'Открытые данные'}
          {hexes ? ` · версия ${hexes.data_version}` : ''}
        </span>
      </footer>
    </div>
  );
}
