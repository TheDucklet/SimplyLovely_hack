import type { Content, TableCell, TDocumentDefinitions } from 'pdfmake/interfaces';
import type { LocationReport, MonthlyCosts, RiskLevel } from '../api/types';
import { decimal, months, rubles } from '../format';
import { createLocationMap } from './locationMap';

export interface BusinessPlanSnapshot {
  report: LocationReport;
  calculatedAt: string;
  cityName: string;
  nicheName: string;
  isDemo: boolean;
}

const PAGE_MARGIN = 32;
const INK = '#14233A';
const MUTED = '#58645E';
const ORANGE = '#B5541C';
const SOURCE_COLUMNS = 3;
const RISK_LABELS: Record<RiskLevel, string> = {
  low: 'Низкий риск',
  medium: 'Средний риск',
  high: 'Высокий риск',
};
const RISK_COLORS: Record<RiskLevel, string> = {
  low: '#21634A',
  medium: '#7A461C',
  high: '#8B3822',
};
const COSTS: [keyof MonthlyCosts, string][] = [
  ['rent', 'Аренда'],
  ['payroll', 'Зарплаты'],
  ['cogs', 'Себестоимость'],
  ['taxes', 'Налоги'],
  ['other', 'Прочие расходы'],
  ['total', 'Итого'],
];
const BASE_SOURCES = ['https://www.openstreetmap.org/copyright', 'https://data.mos.ru'];
const RUSSIAN_UNITS: Record<string, string> = { rub: '₽', share: 'доля' };

function safeLink(value: string): string | undefined {
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : undefined;
  } catch {
    return undefined;
  }
}

function sourceLabel(value: string): string {
  const link = safeLink(value);
  return link ? new URL(link).hostname : value;
}

function sectionTitle(text: string): Content {
  return { text, style: 'sectionTitle' };
}

export function createBusinessPlanDefinition(snapshot: BusinessPlanSnapshot): TDocumentDefinitions {
  const { report, calculatedAt, cityName, nicheName, isDemo } = snapshot;
  const address =
    report.location.address ||
    `${report.location.lat.toFixed(5)}, ${report.location.lon.toFixed(5)}`;
  const date = new Intl.DateTimeFormat('ru-RU', {
    dateStyle: 'long',
    timeStyle: 'short',
    timeZone: 'Europe/Moscow',
  })
    .format(new Date(calculatedAt))
    .replace(/\u00a0|\u202f/g, ' ');
  const sources = [
    ...new Set([
      ...BASE_SOURCES,
      ...report.assumptions.flatMap((item) => (item.source ? [item.source] : [])),
    ]),
  ];
  const risk = {
    text: RISK_LABELS[report.risk_level],
    color: RISK_COLORS[report.risk_level],
    bold: true,
    fontSize: 10,
    margin: [0, 6, 0, 14],
  } as Content;
  const expenseRows: TableCell[][] = COSTS.map(([key, label]) => [
    { text: label, bold: key === 'total', color: key === 'total' ? INK : MUTED },
    { text: rubles(report.costs_month[key]), alignment: 'right', bold: key === 'total' },
  ]);
  const factors: Content[] = [...report.factors]
    .sort((a, b) => Math.abs(b.effect_rub) - Math.abs(a.effect_rub))
    .slice(0, 5)
    .map((factor) => ({
      stack: [
        { text: factor.name, fontSize: 8.5 },
        { text: `${decimal(factor.value)} ${factor.unit}`, fontSize: 7, color: MUTED },
        {
          text: `${factor.effect_rub > 0 ? '+' : factor.effect_rub < 0 ? '−' : ''}${rubles(Math.abs(factor.effect_rub))}`,
          bold: true,
          color: factor.effect_rub > 0 ? '#21634A' : factor.effect_rub < 0 ? '#9D3C26' : MUTED,
          fontSize: 10,
        },
      ],
      margin: [0, 0, 0, 7],
      unbreakable: true,
    }));
  const assumptions: TableCell[][] = [
    [
      { text: 'Допущение', style: 'tableHeader' },
      { text: 'Значение', style: 'tableHeader' },
      { text: 'Источник', style: 'tableHeader' },
    ],
    ...report.assumptions.map((item): TableCell[] => [
      { text: item.name },
      {
        text: `${typeof item.value === 'number' ? decimal(item.value) : item.value}${item.unit ? ` ${RUSSIAN_UNITS[item.unit] || item.unit}` : ''}`,
      },
      item.source
        ? {
            text: `[${sources.indexOf(item.source) + 1}]`,
            link: safeLink(item.source),
            color: '#21634A',
          }
        : { text: 'Не подтверждён', color: '#8A431B' },
    ]),
  ];
  const content: Content[] = [
    { text: 'ГеоСтарт', fontSize: 12, bold: true, color: ORANGE, margin: [0, 0, 0, 9] },
    { text: 'Черновик бизнес-плана', fontSize: 24, bold: true, margin: [0, 0, 0, 6] },
    { text: `${cityName} · ${nicheName}`, fontSize: 12, margin: [0, 0, 0, 8] },
    { text: address, fontSize: 11, bold: true, margin: [0, 0, 0, 4] },
    {
      text: `${report.location.lat.toFixed(5)}, ${report.location.lon.toFixed(5)} · Расчёт ${date} МСК`,
      style: 'note',
      margin: [0, 0, 0, 13],
    },
    ...(isDemo
      ? [
          {
            text: 'ДЕМОНСТРАЦИОННЫЕ ДАННЫЕ · ФИКСИРОВАННЫЙ ПРИМЕР',
            color: '#8A431B',
            bold: true,
            fontSize: 9,
            margin: [0, 0, 0, 8],
          } as Content,
        ]
      : []),
    {
      columns: [
        {
          width: 300,
          stack: [
            { svg: createLocationMap(report), width: 300 },
            {
              text: 'Выбранная точка, ячейка H3 и ближайшие конкуренты. Север сверху, пунктирный круг – 500 м по прямой.',
              style: 'note',
              margin: [0, 5, 0, 0],
            },
            {
              text: '© участники OpenStreetMap, data.mos.ru',
              fontSize: 6.5,
              color: MUTED,
              margin: [0, 3, 0, 0],
            },
          ],
        },
        {
          width: '*',
          stack: [
            { text: 'Выручка в месяц', style: 'label' },
            {
              text: rubles(report.revenue_month.p50),
              fontSize: 21,
              bold: true,
              margin: [0, 3, 0, 7],
            },
            {
              text: `От ${rubles(report.revenue_month.p10)} до ${rubles(report.revenue_month.p90)}, вероятнее всего ${rubles(report.revenue_month.p50)}`,
              fontSize: 8.5,
              lineHeight: 1.15,
            },
            risk,
            { text: 'Прибыль в месяц, p50', style: 'label' },
            {
              text: rubles(report.profit_month_p50),
              fontSize: 16,
              bold: true,
              color: report.profit_month_p50 < 0 ? '#9D3C26' : INK,
              margin: [0, 3, 0, 11],
            },
            { text: 'Капитальные затраты, p50', style: 'label' },
            { text: rubles(report.capex_rub_p50), fontSize: 12, bold: true, margin: [0, 3, 0, 11] },
            { text: 'Окупаемость', style: 'label' },
            {
              text:
                report.payback_months_p50 === null
                  ? 'Не окупается при текущих допущениях'
                  : months(report.payback_months_p50),
              fontSize: 11,
              bold: true,
              margin: [0, 3, 0, 0],
            },
          ],
        },
      ],
      columnGap: 18,
      margin: [0, 0, 0, 17],
    },
    {
      columns: [
        {
          width: 255,
          stack: [
            sectionTitle('Расходы в месяц'),
            { table: { widths: ['*', 'auto'], body: expenseRows }, layout: 'lightHorizontalLines' },
            {
              text: 'Медиана прибыли рассчитана по сценариям и может отличаться от разницы показанных выручки и расходов.',
              style: 'note',
              margin: [0, 9, 0, 0],
            },
          ],
        },
        {
          width: '*',
          stack: [
            sectionTitle('Что влияет на выручку'),
            ...factors,
            ...(!factors.length
              ? [{ text: 'Факторы не предоставлены моделью', style: 'note' } as Content]
              : []),
          ],
        },
      ],
      columnGap: 22,
    },
    {
      text: 'Оценка ориентировочная, основана на открытых данных и допущениях модели. Документ не гарантирует финансовый результат и не является решением о выдаче кредита.',
      fontSize: 8.5,
      color: MUTED,
      margin: [0, 13, 0, 0],
    },
    {
      text: 'Допущения и источники',
      fontSize: 18,
      bold: true,
      pageBreak: 'before',
      margin: [0, 0, 0, 6],
    },
    {
      text: `${cityName} · ${nicheName} · ${address}`,
      fontSize: 9,
      bold: true,
      margin: [0, 0, 0, 5],
    },
    {
      text: `Расчёт ${date} МСК · Версия данных ${report.data_version}`,
      style: 'note',
      margin: [0, 0, 0, 4],
    },
    {
      table: { headerRows: 1, widths: [148, '*', 76], body: assumptions, dontBreakRows: true },
      layout: {
        hLineWidth: (index) => (index === 1 ? 1 : 0.4),
        vLineWidth: () => 0,
        hLineColor: () => '#CCD1CD',
        paddingLeft: () => 4,
        paddingRight: () => 4,
        paddingTop: () => 0.25,
        paddingBottom: () => 0.25,
      },
      fontSize: 7.5,
      lineHeight: 1.05,
    },
    sectionTitle('Источники'),
    {
      columns: Array.from({ length: SOURCE_COLUMNS }, (_, column) => ({
        width: '*',
        stack: sources.flatMap((source, index): Content[] =>
          index % SOURCE_COLUMNS === column
            ? [
                {
                  text: [
                    { text: `[${index + 1}] `, bold: true },
                    { text: sourceLabel(source), link: safeLink(source) },
                  ],
                  fontSize: 7,
                  color: MUTED,
                  margin: [0, 0, 0, 3],
                },
              ]
            : [],
        ),
      })),
      columnGap: 14,
    },
    {
      text: `H3 ${report.location.h3}. «Не подтверждён» – допущение без источника. Полные адреса публикаций доступны по ссылкам.`,
      style: 'note',
      margin: [0, 4, 0, 0],
    },
  ];
  return {
    pageSize: 'A4',
    pageMargins: [PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, 42],
    defaultStyle: { font: 'Roboto', fontSize: 9, color: INK, lineHeight: 1.1 },
    content,
    styles: {
      sectionTitle: { fontSize: 11, bold: true, margin: [0, 11, 0, 7] },
      label: { fontSize: 8, color: MUTED },
      note: { fontSize: 7.5, color: MUTED, lineHeight: 1.15 },
      tableHeader: { bold: true, color: INK, fillColor: '#F5F4EF' },
    },
    footer: (page, count) => ({
      columns: [
        { text: `ГеоСтарт · ${isDemo ? 'Демонстрация · ' : ''}Версия ${report.data_version}` },
        { text: `${page} / ${count}`, alignment: 'right' },
      ],
      fontSize: 7,
      color: MUTED,
      margin: [PAGE_MARGIN, 14, PAGE_MARGIN, 0],
    }),
    info: {
      title: `Черновик бизнес-плана · ${address}`,
      author: 'ГеоСтарт',
      subject: `${cityName}, ${nicheName}`,
      creator: 'ГеоСтарт',
      creationDate: new Date(calculatedAt),
    },
  };
}
