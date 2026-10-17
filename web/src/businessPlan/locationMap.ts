import { cellToBoundary } from 'h3-js';
import type { LocationReport } from '../api/types';

const MAP_WIDTH = 360;
const MAP_HEIGHT = 250;
const HALF_HEIGHT_METERS = 650;
const GRID_SPACING_METERS = 200;
const NEARBY_RADIUS_METERS = 500;
const EARTH_RADIUS_METERS = 6371008.8;
const RADIANS_PER_DEGREE = Math.PI / 180;

export function createLocationMap(report: LocationReport): string {
  const scale = MAP_HEIGHT / (HALF_HEIGHT_METERS * 2);
  const { lat, lon, h3 } = report.location;
  function project(pointLat: number, pointLon: number): [number, number] {
    return [
      MAP_WIDTH / 2 +
        (pointLon - lon) *
          RADIANS_PER_DEGREE *
          EARTH_RADIUS_METERS *
          Math.cos(lat * RADIANS_PER_DEGREE) *
          scale,
      MAP_HEIGHT / 2 - (pointLat - lat) * RADIANS_PER_DEGREE * EARTH_RADIUS_METERS * scale,
    ];
  }
  const cell = cellToBoundary(h3)
    .map(([pointLat, pointLon]) =>
      project(pointLat, pointLon)
        .map((value) => value.toFixed(2))
        .join(','),
    )
    .join(' ');
  const grid: string[] = [];
  const gridStep = GRID_SPACING_METERS * scale;
  for (let position = (MAP_WIDTH / 2) % gridStep; position < MAP_WIDTH; position += gridStep)
    grid.push(`<path d="M ${position.toFixed(2)} 0 V ${MAP_HEIGHT}"/>`);
  for (let position = (MAP_HEIGHT / 2) % gridStep; position < MAP_HEIGHT; position += gridStep)
    grid.push(`<path d="M 0 ${position.toFixed(2)} H ${MAP_WIDTH}"/>`);
  const points = report.competitors
    .map((competitor) => {
      const [x, y] = project(competitor.lat, competitor.lon);
      return x >= 0 && x <= MAP_WIDTH && y >= 0 && y <= MAP_HEIGHT
        ? `<circle cx="${x.toFixed(2)}" cy="${y.toFixed(2)}" r="3.6" fill="#14233A" stroke="#FFFFFF" stroke-width="1.2"/>`
        : '';
    })
    .join('');
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${MAP_WIDTH}" height="${MAP_HEIGHT}" viewBox="0 0 ${MAP_WIDTH} ${MAP_HEIGHT}"><rect width="${MAP_WIDTH}" height="${MAP_HEIGHT}" fill="#F5F4EF"/><g stroke="#E1E4DE" stroke-width="0.6">${grid.join('')}</g><circle cx="${MAP_WIDTH / 2}" cy="${MAP_HEIGHT / 2}" r="${NEARBY_RADIUS_METERS * scale}" fill="none" stroke="#A6B9AA" stroke-width="1" stroke-dasharray="4 4"/><polygon points="${cell}" fill="#EFD3BA" stroke="#B5541C" stroke-width="2"/>${points}<circle cx="${MAP_WIDTH / 2}" cy="${MAP_HEIGHT / 2}" r="6" fill="#B5541C" stroke="#FFFFFF" stroke-width="2"/><path d="M 330 46 V 20 L 324 30 M 330 20 L 336 30" fill="none" stroke="#14233A" stroke-width="1.5"/><text x="326" y="14" font-family="Roboto" font-size="10" fill="#14233A">С</text><path d="M 18 220 V 225 H ${18 + GRID_SPACING_METERS * scale} V 220" fill="none" stroke="#14233A" stroke-width="1.5"/><text x="18" y="240" font-family="Roboto" font-size="10" fill="#14233A">200 м</text></svg>`;
}
