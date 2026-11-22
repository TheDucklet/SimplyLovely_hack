import type { TDocumentDefinitions } from 'pdfmake/interfaces';
import type { CreditCheckReport } from '../api/economicsTypes';
import {
  checkHeaders,
  checkCells,
  coverageLabel,
  coverageValue,
  verdictLabels,
} from '../borrowerPlan';
import { rubles } from '../format';
import { assumptionColumns } from './financialPage';
import { downloadPdf } from './download';

export async function downloadConclusion(report: CreditCheckReport, place: string): Promise<void> {
  const { economics } = report;
  const title = 'Заключение по бизнес-плану';
  const colors = { confirmed: '#285e43', needs_review: '#80500f', not_confirmed: '#922b29' };
  const definition: TDocumentDefinitions = {
    pageSize: 'A4',
    pageMargins: [32, 30, 32, 30],
    defaultStyle: { font: 'Roboto', fontSize: 9, color: '#19334e' },
    info: { title, author: 'ГеоСтарт' },
    content: [
      { text: 'ГеоСтарт · Проверка бизнес-плана', fontSize: 10, color: '#345d84' },
      { text: title, fontSize: 21, bold: true, margin: [0, 5, 0, 3] },
      { text: place, margin: [0, 0, 0, 8] },
      {
        text: verdictLabels[report.verdict],
        bold: true,
        fontSize: 16,
        color: colors[report.verdict],
      },
      { ul: [...report.summary], margin: [0, 4, 0, 8] },
      {
        table: {
          headerRows: 1,
          widths: ['18%', '15%', '24%', '15%', '17%', '11%'],
          body: [
            checkHeaders.map((text) => ({ text, bold: true, fillColor: '#e7eff6' })),
            ...report.checks.map(checkCells),
          ],
        },
        layout: 'lightHorizontalLines',
        fontSize: 9,
      },
      { text: coverageLabel(report) + ' · ' + coverageValue(report), margin: [0, 6, 0, 2] },
      {
        text:
          'Запрошено ' +
          rubles(report.loan_amount_rub) +
          ' · Предельный кредит модели (p50) ' +
          rubles(report.max_loan_rub.p50),
      },
      { text: 'Допущения модели', bold: true, fontSize: 12, margin: [0, 10, 0, 5] },
      assumptionColumns(economics.assumptions),
    ],
    footer: {
      text:
        'Расчёт по ' +
        economics.scenarios +
        ' сценариям · Версия модели ' +
        economics.versions.model +
        ' · Данные ' +
        economics.versions.data,
      margin: [32, 3, 32, 0],
      fontSize: 8,
      color: '#43586b',
    },
  };
  await downloadPdf(
    definition,
    'geostart-credit-check-' + economics.city + '-' + economics.niche + '.pdf',
  );
}
