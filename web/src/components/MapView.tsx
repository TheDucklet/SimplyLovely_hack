import { useEffect, useRef, useState } from 'react';
import { Map, NavigationControl, setWorkerUrl, type StyleSpecification } from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
import { MapboxOverlay } from '@deck.gl/mapbox';
import { H3HexagonLayer } from '@deck.gl/geo-layers';
import { ScatterplotLayer } from '@deck.gl/layers';
import type { PickingInfo } from '@deck.gl/core';
import { cellToLatLng } from 'h3-js';
import type { CityInfo, Competitor, HexScore } from '../api/types';
import type { SelectedLocation } from '../hooks/useLocationReport';
import { metricScale, type Metric } from '../mapStyle';

setWorkerUrl(workerUrl);
const HEX_OPACITY = 0.5;
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
      paint: { 'raster-saturation': -0.45, 'raster-opacity': 0.95 },
    },
  ],
};
export interface MapViewProps {
  city: CityInfo;
  items: HexScore[];
  competitors: Competitor[];
  metric: Metric;
  selected: SelectedLocation | null;
  disabled: boolean;
  onSelect: (point: SelectedLocation) => void;
}

export function MapView({
  city,
  items,
  competitors,
  metric,
  selected,
  disabled,
  onSelect,
}: MapViewProps) {
  const container = useRef<HTMLDivElement>(null);
  const initialCity = useRef(city);
  const map = useRef<Map | null>(null);
  const overlay = useRef<MapboxOverlay | null>(null);
  const selectRef = useRef(onSelect);
  const disabledRef = useRef(disabled);
  const [mapError, setMapError] = useState(false);
  useEffect(() => {
    selectRef.current = onSelect;
    disabledRef.current = disabled;
  }, [onSelect, disabled]);
  useEffect(() => {
    if (!container.current) return;
    const instance = new Map({
      container: container.current,
      style: MAP_STYLE,
      center: [initialCity.current.center[1], initialCity.current.center[0]],
      zoom: initialCity.current.zoom,
      attributionControl: false,
      locale: {
        'Map.Title': 'Карта',
        'NavigationControl.ZoomIn': 'Приблизить карту',
        'NavigationControl.ZoomOut': 'Отдалить карту',
      },
    });
    const deckOverlay = new MapboxOverlay({ interleaved: false });
    instance.addControl(deckOverlay);
    instance.addControl(new NavigationControl({ showCompass: false }), 'bottom-right');
    instance.on('error', () => setMapError(true));
    instance.on('idle', () => setMapError(false));
    instance.on('click', (event) => {
      if (disabledRef.current) return;
      const picked = deckOverlay.pickObject({ x: event.point.x, y: event.point.y, radius: 3 });
      if (!picked?.object) selectRef.current({ lat: event.lngLat.lat, lon: event.lngLat.lng });
    });
    map.current = instance;
    overlay.current = deckOverlay;
    const observer = new ResizeObserver(() => instance.resize());
    observer.observe(container.current);
    return () => {
      observer.disconnect();
      overlay.current = null;
      map.current = null;
      instance.remove();
    };
  }, []);
  useEffect(() => {
    map.current?.flyTo({
      center: [city.center[1], city.center[0]],
      zoom: city.zoom,
      essential: false,
    });
  }, [city]);
  useEffect(() => {
    if (selected)
      map.current?.easeTo({
        center: [selected.lon, selected.lat],
        duration: 600,
        essential: false,
      });
  }, [selected]);
  useEffect(() => {
    const scale = metricScale(items, metric);
    overlay.current?.setProps({
      layers: [
        new H3HexagonLayer<HexScore>({
          id: 'forecast-hexagons',
          data: items,
          getHexagon: (item) => item.h3,
          getFillColor: scale.color,
          getLineColor: [255, 255, 255, 105],
          lineWidthMinPixels: 0.5,
          extruded: false,
          pickable: true,
          opacity: HEX_OPACITY,
          updateTriggers: { getFillColor: [items, metric] },
          onClick: ({ object }: PickingInfo<HexScore>) => {
            if (object && !disabledRef.current) {
              const [lat, lon] = cellToLatLng(object.h3);
              selectRef.current({ lat, lon });
            }
            return true;
          },
        }),
        new ScatterplotLayer<Competitor>({
          id: 'competitors',
          data: competitors,
          getPosition: (item) => [item.lon, item.lat],
          getFillColor: [255, 255, 255, 240],
          getLineColor: [10, 46, 115],
          stroked: true,
          lineWidthMinPixels: 1.5,
          getRadius: 4,
          radiusUnits: 'pixels',
          pickable: true,
          onClick: ({ object }: PickingInfo<Competitor>) => {
            if (object && !disabledRef.current)
              selectRef.current({ lat: object.lat, lon: object.lon });
            return true;
          },
        }),
        new ScatterplotLayer<SelectedLocation>({
          id: 'selected-location',
          data: selected ? [selected] : [],
          getPosition: (item) => [item.lon, item.lat],
          getRadius: 9,
          radiusUnits: 'pixels',
          getFillColor: [0, 174, 239],
          getLineColor: [255, 255, 255],
          stroked: true,
          lineWidthMinPixels: 3,
          pickable: false,
        }),
      ],
      getTooltip: ({ object }: PickingInfo<HexScore | Competitor>) =>
        object
          ? {
              text:
                'source' in object
                  ? `${object.name}\nИсточник: ${object.source === 'osm' ? 'OpenStreetMap' : 'data.mos.ru'}`
                  : `${metric === 'revenue' ? 'Выручка в месяц' : 'Окупаемость'}\n${scale.format(metric === 'revenue' ? object.revenue_p50 : object.payback_months_p50)}`,
            }
          : null,
      getCursor: ({ isHovering }: { isHovering: boolean }) =>
        disabled ? 'progress' : isHovering ? 'pointer' : 'grab',
    });
  }, [items, competitors, metric, selected, disabled]);
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
