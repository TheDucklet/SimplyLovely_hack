import type { Content, TableCell } from 'pdfmake/interfaces';
import type { EconomicsReport } from '../api/economicsTypes';
import { decimal, rubles } from '../format';

const thousand = (value: number) => decimal(Math.round(value / 100) / 10);
function table(headings: string[], rows: string[][]): Content {
  const body: TableCell[][] = [
    headings.map((text) => ({ text, bold: true, fillColor: '#e7eef6' })),
    ...rows.map((row) => row.map((text) => ({ text, alignment: 'right' as const }))),
  ];
  return {
    table: { headerRows: 1, widths: headings.map(() => 100 / headings.length + '%'), body },
    layout: {
      hLineWidth: (i) => (i === 1 ? 0.8 : 0.3),
      vLineWidth: () => 0,
      hLineColor: () => '#a3b4c6',
      paddingLeft: () => 2,
      paddingRight: () => 2,
      paddingTop: () => 1.5,
      paddingBottom: () => 1.5,
    },
    fontSize: 8,
  };
}
export function creditAndTax({ credit, tax }: EconomicsReport): Content[] {
  return [
    { text: 'Налоговый режим и кредит', style: 'sectionTitle' },
    { text: [{ text: tax.name + '. ', bold: true }, tax.explanation] },
    {
      text:
        (credit.amount > 0 ? (credit.product_name ?? 'Кредит') : 'Без кредита') +
        ' · сумма ' +
        rubles(credit.amount) +
        ' · ' +
        (credit.amount > 0 ? 'ставка ' + decimal(credit.rate_annual * 100) + '% в год · ' : '') +
        'первый платёж ' +
        rubles(credit.first_payment) +
        ' · переплата ' +
        rubles(credit.total_interest) +
        ' · минимальный DSCR ' +
        (credit.dscr_min.p50 === null ? 'нет оценки' : decimal(credit.dscr_min.p50)) +
        ' · предельный кредит ' +
        rubles(credit.max_loan_rub.p50),
      margin: [0, 3, 0, 0],
    },
  ];
}
export function financialPage(report: EconomicsReport): Content[] {
  const { assumptions } = report;
  const items = assumptions.map((item): Content => {
    const val = typeof item.value === 'number' ? decimal(item.value) : item.value;
    let link: string | undefined;
    try {
      const url = new URL(item.source ?? '');
      if (['https:', 'http:'].includes(url.protocol)) link = url.href;
    } catch {
      link = undefined;
    }
    return {
      text: [
        { text: item.name.replace(/ – допущение без источника$/, '') + ' · ', bold: true },
        String(val) + ' ' + item.unit + ' · ',
        {
          text: link ? new URL(link).hostname : (item.source ?? 'без источника'),
          link,
          color: '#344b62',
        },
      ],
      margin: [0, 0, 0, 2],
      fontSize: 8,
    };
  });
  const split = Math.ceil(items.length / 2);
  const start = new Date(report.start_year, report.start_month - 1, 1);
  const date = (month: number) =>
    new Intl.DateTimeFormat('ru-RU', { month: '2-digit', year: '2-digit' }).format(
      new Date(start.getFullYear(), start.getMonth() + month - 1, 1),
    );
  return [
    { text: 'Финансовая модель точки', pageBreak: 'before', fontSize: 18, bold: true },
    {
      text: 'Исходный расчёт · ' + report.scenarios + ' сценариев · суммы в таблицах в тыс. ₽',
      style: 'note',
      margin: [0, 2, 0, 5],
    },
    { text: 'Первый год по месяцам', style: 'sectionTitle' },
    table(
      [
        'Месяц',
        'Выручка',
        'Себест. продаж',
        'Аренда',
        'Штат',
        'Прочие',
        'Налоги',
        'Чистая прибыль',
        'Накопл. поток',
      ],
      report.monthly
        .slice(0, 12)
        .map((row) => [
          date(row.month),
          ...[
            row.revenue,
            row.cogs,
            row.rent,
            row.payroll,
            row.other,
            row.taxes,
            row.net_profit,
            row.cumulative_project_cash,
          ].map(thousand),
        ]),
    ),
    { text: 'Денежный поток по годам проекта', style: 'sectionTitle' },
    table(
      ['Год', 'Выручка', 'Расходы', 'Налоги', 'Проценты', 'Основной долг', 'Операц. поток'],
      report.years
        .slice(0, 3)
        .map((row) => [
          String(row.year),
          ...[
            row.revenue,
            row.operating_costs,
            row.taxes,
            row.interest,
            row.principal,
            row.operating_cash_flow,
          ].map(thousand),
        ]),
    ),
    { text: 'Допущения финансовой модели', style: 'sectionTitle' },
    {
      columns: [
        { width: '*', stack: items.slice(0, split) },
        { width: '*', stack: items.slice(split) },
      ],
      columnGap: 12,
    },
  ];
}
