import type { Assumption } from '../api/types';

export function AssumptionSource({ assumption }: { assumption: Assumption }) {
  if (!assumption.source) return <span className="unverified">без подтверждённого источника</span>;
  try {
    const url = new URL(assumption.source);
    if (['https:', 'http:'].includes(url.protocol))
      return (
        <a href={url.href} target="_blank" rel="noreferrer">
          {url.hostname}
        </a>
      );
  } catch {
    return <span>{assumption.source}</span>;
  }
  return <span>{assumption.source}</span>;
}
