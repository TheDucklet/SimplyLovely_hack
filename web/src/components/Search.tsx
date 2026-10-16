import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { api } from '../api/client';
import type { AddressMatch } from '../api/types';
import { message } from '../format';

const SEARCH_DELAY_MS = 300;
export function Search({
  city,
  disabled,
  onSelect,
}: {
  city: string;
  disabled: boolean;
  onSelect: (point: AddressMatch) => void;
}) {
  const [query, setQuery] = useState('');
  const [matches, setMatches] = useState<AddressMatch[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [active, setActive] = useState(-1);
  const wrapper = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const outside = (event: PointerEvent) => {
      if (!wrapper.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', outside);
    return () => document.removeEventListener('pointerdown', outside);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setMatches([]);
    setActive(-1);
    setError('');
    setLoading(false);
    if (!open || !query.trim()) return;
    setLoading(true);
    const timer = window.setTimeout(() => {
      void api
        .search(city, query.trim(), controller.signal)
        .then((items) => {
          if (!controller.signal.aborted) setMatches(items);
        })
        .catch((cause: unknown) => {
          if (!controller.signal.aborted) setError(message(cause));
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, SEARCH_DELAY_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [city, query, open]);
  function choose(item: AddressMatch): void {
    if (disabled) return;
    setQuery(item.address);
    setOpen(false);
    onSelect(item);
  }
  function onKeyDown(event: KeyboardEvent<HTMLInputElement>): void {
    if (event.key === 'Escape') {
      setOpen(false);
      return;
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      setOpen(true);
      setActive((value) =>
        matches.length
          ? (value + (event.key === 'ArrowDown' ? 1 : -1) + matches.length) % matches.length
          : -1,
      );
    }
    if (event.key === 'Enter' && open && matches.length) {
      event.preventDefault();
      choose(matches[Math.max(active, 0)]);
    }
  }
  return (
    <div className="search" ref={wrapper}>
      <label className="field-label" htmlFor="address-search">
        Адрес
      </label>
      <div className="search-input">
        <svg aria-hidden="true" viewBox="0 0 24 24" width="19" height="19">
          <circle cx="10" cy="10" r="6" fill="none" stroke="currentColor" strokeWidth="1.7" />
          <path d="m15 15 5 5" stroke="currentColor" strokeWidth="1.7" />
        </svg>
        <input
          id="address-search"
          aria-label="Адрес"
          type="search"
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={open && !!query.trim()}
          aria-controls="address-results"
          aria-activedescendant={active >= 0 ? `address-${active}` : undefined}
          placeholder="Улица и номер дома"
          autoComplete="off"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
        />
      </div>
      {open && query.trim() && (
        <div className="search-dropdown">
          <ul id="address-results" role="listbox" aria-label="Найденные адреса">
            {matches.map((item, index) => (
              <li
                key={`${item.address}-${item.lat}-${item.lon}`}
                id={`address-${index}`}
                role="option"
                aria-selected={index === active}
              >
                <button
                  disabled={disabled}
                  onClick={() => choose(item)}
                  onMouseEnter={() => setActive(index)}
                >
                  {item.address}
                </button>
              </li>
            ))}
          </ul>
          {loading ? (
            <p role="status">Ищем адреса…</p>
          ) : error ? (
            <p role="alert">{error}</p>
          ) : !matches.length ? (
            <p role="status">Адресов не найдено. Уточните улицу и номер дома.</p>
          ) : disabled ? (
            <p role="status">Дождитесь расчёта отчёта</p>
          ) : null}
        </div>
      )}
    </div>
  );
}
