import { createRoot, type Root } from 'react-dom/client';
import financeStyles from '../src/components/finance.css?inline';
import { settings } from './api';
import { Report } from './Report';
import widgetStyles from './widget.css?inline';

class GeoStartReport extends HTMLElement {
  static observedAttributes = ['city', 'niche', 'lat', 'lon', 'api'];
  private root?: Root;
  private readonly mount = document.createElement('div');
  private queued = false;

  constructor() {
    super();
    const shadow = this.attachShadow({ mode: 'open' });
    const style = document.createElement('style');
    style.textContent = financeStyles + widgetStyles;
    shadow.append(style, this.mount);
  }

  connectedCallback(): void {
    this.root ??= createRoot(this.mount);
    this.schedule();
  }

  disconnectedCallback(): void {
    this.root?.unmount();
    this.root = undefined;
  }

  attributeChangedCallback(_name: string, before: string | null, after: string | null): void {
    if (before !== after) this.schedule();
  }

  private schedule(): void {
    if (this.queued || !this.root) return;
    this.queued = true;
    queueMicrotask(() => {
      this.queued = false;
      if (!this.root) return;
      try {
        this.root.render(<Report {...settings(this)} />);
      } catch (error) {
        this.root.render(
          <p lang="ru" role="alert">
            {error instanceof Error ? error.message : 'Проверьте атрибуты виджета.'}
          </p>,
        );
      }
    });
  }
}

if (!customElements.get('geostart-report'))
  customElements.define('geostart-report', GeoStartReport);
