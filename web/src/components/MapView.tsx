import { useEffect, useRef, useState } from 'react';
import {
  Map,
  NavigationControl,
  setWorkerUrl,
  type ExpressionSpecification,
  type StyleSpecification,
  type SymbolLayerSpecification,
} from 'maplibre-gl';
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
const MAP_STYLE_URL =
  import.meta.env.VITE_MAP_STYLE_URL || 'https://tiles.openfreemap.org/styles/positron';
const EMPTY_STYLE: StyleSpecification = { version: 8, sources: {}, layers: [] };
const LABEL_FIELD: ExpressionSpecification = ['coalesce', ['get', 'name:ru'], ['get', 'name']];
const LABEL_HALO_WIDTH = 1.8;
const LABEL_COLOR = '#0b1220';

function boldFont(font: unknown): unknown {
  return Array.isArray(font)
    ? font.map((name) => (typeof name === 'string' ? name.replace(/Regular|Italic/, 'Bold') : name))
    : font;
}

function withoutLabels(style: StyleSpecification): StyleSpecification {
  return { ...style, layers: style.layers.filter((layer) => layer.type !== 'symbol') };
}

function onlyLabels(style: StyleSpecification): StyleSpecification {
  return {
    ...style,
    layers: style.layers
      .filter((layer): layer is SymbolLayerSpecification => layer.type === 'symbol')
      .map((layer) => ({
        ...layer,
        layout: {
          ...layer.layout,
          ...(JSON.stringify(layer.layout?.['text-field'] ?? '').includes('name')
            ? { 'text-field': LABEL_FIELD }
            : {}),
          ...(layer.layout?.['text-font']
            ? { 'text-font': boldFont(layer.layout['text-font']) as string[] }
            : {}),
        },
        paint: {
          ...layer.paint,
          'text-color': LABEL_COLOR,
          'text-halo-color': '#ffffff',
          'text-halo-width': LABEL_HALO_WIDTH,
        },
      })),
  };
}
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
  const labelsContainer = useRef<HTMLDivElement>(null);
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
    if (!container.current || !labelsContainer.current) return;
    const instance = new Map({
      container: container.current,
      style: EMPTY_STYLE,
      center: [initialCity.current.center[1], initialCity.current.center[0]],
      zoom: initialCity.current.zoom,
      attributionControl: false,
      locale: {
        'Map.Title': 'Карта',
        'NavigationControl.ZoomIn': 'Приблизить карту',
        'NavigationControl.ZoomOut': 'Отдалить карту',
      },
    });
    instance.setStyle(MAP_STYLE_URL, { transformStyle: (_, next) => withoutLabels(next) });
    const labels = new Map({
      container: labelsContainer.current,
      style: EMPTY_STYLE,
      center: instance.getCenter(),
      zoom: instance.getZoom(),
      interactive: false,
      attributionControl: false,
    });
    labels.setStyle(MAP_STYLE_URL, { transformStyle: (_, next) => onlyLabels(next) });
    instance.on('move', () =>
      labels.jumpTo({
        center: instance.getCenter(),
        zoom: instance.getZoom(),
        bearing: instance.getBearing(),
        pitch: instance.getPitch(),
      }),
    );
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
    const observer = new ResizeObserver(() => {
      instance.resize();
      labels.resize();
    });
    observer.observe(container.current);
    return () => {
      observer.disconnect();
      overlay.current = null;
      map.current = null;
      labels.remove();
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
      <div ref={labelsContainer} className="map-labels" aria-hidden="true" />
      {mapError && (
        <div className="map-warning" role="status">
          Подложка карты недоступна. Проверьте подключение к серверу тайлов.
        </div>
      )}
      <div className="map-attribution">
        <a href="https://openfreemap.org">OpenFreeMap</a> ©{' '}
        <a href="https://www.openmaptiles.org">OpenMapTiles</a>, © участники{' '}
        <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>,{' '}
        <a href="https://data.mos.ru">data.mos.ru</a>
      </div>
    </>
  );
}
