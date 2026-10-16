import { useEffect, useRef, useState } from 'react';
import { Map, NavigationControl, setWorkerUrl, type StyleSpecification } from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
import { MapboxOverlay } from '@deck.gl/mapbox';
import { H3HexagonLayer } from '@deck.gl/geo-layers';
import type { CityInfo, HexScore } from '../api/types';
import { rubles } from '../format';

setWorkerUrl(workerUrl);

const MAP_STYLE: string | StyleSpecification = import.meta.env.VITE_MAP_STYLE_URL || {
  version: 8,
  sources: {
    openstreetmap: {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      maxzoom: 19,
    },
  },
  layers: [
    {
      id: 'openstreetmap',
      type: 'raster',
      source: 'openstreetmap',
      paint: { 'raster-saturation': -0.75, 'raster-opacity': 0.65 },
    },
  ],
};
const HEX_OPACITY = 0.58;
const REVENUE_COLORS: [number, number, number][] = [
  [230, 189, 152],
  [211, 161, 113],
  [145, 175, 147],
  [83, 140, 122],
  [32, 105, 93],
];

export interface MapViewProps {
  city: CityInfo;
  items: HexScore[];
}

export function MapView({ city, items }: MapViewProps) {
  const container = useRef<HTMLDivElement>(null);
  const initialCity = useRef(city);
  const map = useRef<Map | null>(null);
  const overlay = useRef<MapboxOverlay | null>(null);
  const [mapError, setMapError] = useState(false);

  useEffect(() => {
    if (!container.current) return;
    const instance = new Map({
      container: container.current,
      style: MAP_STYLE,
      center: [initialCity.current.center[1], initialCity.current.center[0]],
      zoom: initialCity.current.zoom,
      attributionControl: false,
    });
    const deckOverlay = new MapboxOverlay({ interleaved: false });
    instance.addControl(deckOverlay);
    instance.addControl(new NavigationControl({ showCompass: false }), 'bottom-right');
    instance.on('error', () => setMapError(true));
    map.current = instance;
    overlay.current = deckOverlay;
    const resizeObserver = new ResizeObserver(() => instance.resize());
    resizeObserver.observe(container.current);
    return () => {
      resizeObserver.disconnect();
      overlay.current = null;
      map.current = null;
      instance.remove();
    };
  }, []);

  useEffect(() => {
    map.current?.flyTo({ center: [city.center[1], city.center[0]], zoom: city.zoom });
  }, [city]);

  useEffect(() => {
    const sorted = items.map((item) => item.revenue_p50).sort((left, right) => left - right);
    const thresholds = REVENUE_COLORS.slice(1).map((_, index) =>
      sorted.length
        ? sorted[Math.floor(((index + 1) * (sorted.length - 1)) / REVENUE_COLORS.length)]
        : 0,
    );
    overlay.current?.setProps({
      layers: [
        new H3HexagonLayer<HexScore>({
          id: 'revenue-hexagons',
          data: items,
          getHexagon: (item) => item.h3,
          getFillColor: (item) =>
            REVENUE_COLORS[thresholds.filter((threshold) => item.revenue_p50 >= threshold).length],
          getLineColor: [255, 255, 255, 110],
          lineWidthMinPixels: 0.5,
          extruded: false,
          pickable: true,
          opacity: HEX_OPACITY,
          updateTriggers: { getFillColor: [items] },
        }),
      ],
      getTooltip: ({ object }: { object?: HexScore }) =>
        object ? { text: `Выручка в месяц\n${rubles(object.revenue_p50)}` } : null,
    });
  }, [items]);

  return (
    <>
      <div ref={container} className="map-canvas" aria-label={`Карта ${city.name}`} />
      {mapError && (
        <div className="map-warning" role="status">
          Подложка карты недоступна. Проверьте подключение к серверу тайлов.
        </div>
      )}
      <div className="map-attribution">
        © участники <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>,{' '}
        <a href="https://data.mos.ru">data.mos.ru</a>
      </div>
    </>
  );
}
