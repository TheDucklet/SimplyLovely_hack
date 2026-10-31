export interface LandingFact {
  value: string;
  label: string;
}

export interface LandingStep {
  title: string;
  text: string;
}

export const LANDING_FACTS: LandingFact[] = [
  { value: '8 717', label: 'участков Москвы внутри МКАД с прогнозом выручки' },
  { value: '9 381', label: 'конкурентов в расчёте, кофейни и пункты выдачи' },
  { value: '0,676', label: 'ROC AUC для кофеен Москвы на действующих точках' },
  { value: '1,36 / 1,46', label: 'млн ₽, медиана прогноза против медианы доходов по РЦНИ' },
];

export const LANDING_STEPS: LandingStep[] = [
  {
    title: 'Город и вид бизнеса',
    text: 'Москва или Тула, кофейня или пункт выдачи заказов. Карта сразу показывает потенциал каждого участка.',
  },
  {
    title: 'Адрес или участок',
    text: 'Найдите помещение по адресу или нажмите на карту. Два адреса можно сравнить рядом.',
  },
  {
    title: 'Расчёт и бизнес-план',
    text: 'Выручка, расходы, прибыль и окупаемость, PDF на два листа и переход к счёту или кредиту.',
  },
];

export const LANDING_EXAMPLE = {
  address: 'Саянская улица, 3 к1',
  niche: 'кофейня',
  revenue: '1 656 885 ₽',
  profit: '488 817 ₽',
  payback: '7,7 мес.',
};

const HEX_COLUMNS = 9;
const HEX_ROWS = 7;
const HEX_RADIUS = 34;
const HEX_SHADES = ['#cfe8f8', '#8ac9f0', '#3e9bdc', '#1663b8', '#0a2e73'];

export interface HeroHex {
  points: string;
  fill: string;
}

function hexPoints(cx: number, cy: number): string {
  return Array.from({ length: 6 }, (_, corner) => {
    const angle = (Math.PI / 3) * corner + Math.PI / 6;
    return `${(cx + HEX_RADIUS * Math.cos(angle)).toFixed(1)},${(cy + HEX_RADIUS * Math.sin(angle)).toFixed(1)}`;
  }).join(' ');
}

export function heroHexes(): HeroHex[] {
  const width = Math.sqrt(3) * HEX_RADIUS;
  const center = { x: (HEX_COLUMNS * width) / 2, y: (HEX_ROWS * HEX_RADIUS * 1.5) / 2 };
  const reach = Math.hypot(center.x, center.y);
  return Array.from({ length: HEX_COLUMNS * HEX_ROWS }, (_, index) => {
    const row = Math.floor(index / HEX_COLUMNS);
    const column = index % HEX_COLUMNS;
    const cx = column * width + (row % 2 ? width / 2 : 0) + width / 2;
    const cy = row * HEX_RADIUS * 1.5 + HEX_RADIUS;
    const closeness = 1 - Math.hypot(cx - center.x, cy - center.y) / reach;
    const wave = (Math.sin(column * 1.7 + row * 0.9) + 1) / 2;
    const level = Math.min(
      HEX_SHADES.length - 1,
      Math.floor((closeness * 0.75 + wave * 0.25) * HEX_SHADES.length),
    );
    return { points: hexPoints(cx, cy), fill: HEX_SHADES[level] };
  });
}

export const HERO_VIEWBOX = `0 0 ${Math.ceil((HEX_COLUMNS + 0.5) * Math.sqrt(3) * HEX_RADIUS)} ${Math.ceil((HEX_ROWS * 1.5 + 0.5) * HEX_RADIUS)}`;
