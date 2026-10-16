import type { HexScore } from '../api/types';
import { metricScale, NO_PAYBACK_COLOR, type Color, type Metric } from '../mapStyle';
function colorCss(color: Color): string {
  return `rgb(${color.join(',')})`;
}
export function Legend({ items, metric }: { items: HexScore[]; metric: Metric }) {
  const scale = metricScale(items, metric);
  return (
    <div className="legend">
      <strong>{metric === 'revenue' ? 'Выручка, ₽ / месяц' : 'Окупаемость, месяцы'}</strong>
      {scale.values.length > 0 && (
        <>
          <div className="legend-bins">
            {scale.colors.map((color, index) => (
              <span key={index} style={{ background: colorCss(color) }} />
            ))}
          </div>
          <div className="legend-labels">
            <span>{scale.format(scale.values[0])}</span>
            <span>{scale.format(scale.values[scale.values.length - 1])}</span>
          </div>
          <details className="legend-details">
            <summary>Границы цветовых групп</summary>
            {scale.colors.map((color, index) => (
              <div className="legend-row" key={index}>
                <i style={{ background: colorCss(color) }} />
                <span>
                  {scale.format(index === 0 ? scale.values[0] : scale.thresholds[index - 1])} –{' '}
                  {scale.format(
                    index === scale.colors.length - 1
                      ? scale.values[scale.values.length - 1]
                      : scale.thresholds[index],
                  )}
                </span>
              </div>
            ))}
          </details>
        </>
      )}
      {metric === 'payback' && (
        <div className="legend-row no-payback">
          <i style={{ background: colorCss(NO_PAYBACK_COLOR) }} />
          Не окупается
        </div>
      )}
      <small>
        {scale.values.length
          ? 'Сравнение участков внутри города'
          : 'Нет участков с положительной прибылью'}
      </small>
    </div>
  );
}
