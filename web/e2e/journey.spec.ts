import { expect, test, type Page } from '@playwright/test';
import { readFile } from 'node:fs/promises';

async function checkDownload(page: Page, button: string, filename: RegExp): Promise<void> {
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: button, exact: true }).click(),
  ]);
  expect(download.suggestedFilename()).toMatch(filename);
  expect(await download.failure()).toBeNull();
  const path = await download.path();
  expect(path).toBeTruthy();
  const pdf = await readFile(path!);
  expect(pdf.subarray(0, 5).toString()).toBe('%PDF-');
  expect(pdf.subarray(-32).toString()).toContain('%%EOF');
}

test('От выбора места до финансовой модели и заключения по кредиту', async ({
  context,
  page,
  baseURL,
}) => {
  const denied: string[] = [];
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const origin = new URL(baseURL!).origin;
  await context.route('**/*', (route) => {
    const url = new URL(route.request().url());
    if (
      ['data:', 'blob:'].includes(url.protocol) ||
      (url.origin === origin && !url.pathname.startsWith('/api/'))
    ) {
      return route.continue();
    }
    denied.push(url.href);
    return route.abort();
  });
  await context.routeWebSocket('**/*', (socket) => {
    denied.push(socket.url());
    socket.close();
  });

  await test.step('Выбрать Москву и кофейню, переключить карту и найти адрес', async () => {
    await page.goto('/');
    await page.getByRole('dialog').getByRole('link', { name: 'Открыть карту' }).click();
    await page.getByLabel('Город', { exact: true }).selectOption({ label: 'Москва' });
    await page.getByLabel('Бизнес', { exact: true }).selectOption({ label: 'Кофейня' });
    const map = page.getByRole('region', { name: 'Карта прогноза' });
    await expect(map.getByRole('heading', { name: 'Москва' })).toBeVisible();
    await expect(map.locator('.maplibregl-canvas').first()).toBeVisible();
    await page.getByRole('button', { name: 'Окупаемость', exact: true }).click();
    await expect(map.getByText('Кофейня · окупаемость', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Выручка', exact: true }).click();
    await expect(map.getByText('Кофейня · выручка в месяц', { exact: true })).toBeVisible();
    await page.getByRole('combobox', { name: 'Адрес' }).fill('улица, 315');
    await page.getByRole('option', { name: 'Тестовая улица, 315' }).getByRole('button').click();
  });

  await test.step('Прочитать диапазон выручки, уровень риска и финансовый прогноз', async () => {
    const panel = page.getByRole('complementary', { name: 'Отчёт по адресу' });
    await expect(panel.getByText('Тестовая улица, 315', { exact: true })).toBeVisible();
    await expect(
      panel.getByText('От 690 715 ₽ до 1 178 820 ₽, вероятнее всего 920 953 ₽', { exact: true }),
    ).toBeVisible();
    await expect(panel.getByText('Средний риск', { exact: true })).toBeVisible();
    await expect(
      panel.getByRole('heading', { name: 'Финансовая модель', exact: true }),
    ).toBeVisible();
    await expect(
      panel.getByText('Линия показывает медиану, полоса – диапазон p10-p90.', { exact: true }),
    ).toBeVisible();
  });

  await test.step('Увеличить средний чек, сравнить выручку, вернуть исходный расчёт и скачать PDF', async () => {
    await page.getByText('Что если', { exact: true }).click();
    const comparison = page.getByRole('region', { name: 'Сравнение сценария' });
    const revenue = comparison
      .locator('.scenario-row')
      .filter({ has: page.getByText('Выручка в месяц', { exact: true }) });
    await page.getByLabel('Изменение среднего чека, %', { exact: true }).fill('10');
    await expect(revenue.locator('span')).toHaveText(['921 039 ₽', '1 013 237 ₽']);
    await expect(revenue.locator('small')).toHaveText('+92 198 ₽ · лучше');
    await page.getByRole('button', { name: 'Вернуть исходный расчёт' }).click();
    await expect(revenue.locator('span')).toHaveText(['921 039 ₽', '921 039 ₽']);
    await expect(revenue.locator('small')).toHaveText('0 · без изменения');
    await checkDownload(
      page,
      'Скачать черновик бизнес-плана',
      /^geostart-business-plan-moscow-coffee-\d{4}-\d{2}-\d{2}\.pdf$/,
    );
  });

  await test.step('Проверить план заёмщика и скачать заключение', async () => {
    await page.getByRole('button', { name: 'Проверка бизнес-плана', exact: true }).click();
    const panel = page.getByRole('complementary', { name: 'Проверка бизнес-плана' });
    for (const [field, value] of Object.entries({
      'Выручка в месяц, ₽': '920000',
      'Вложения, ₽': '3200000',
      'Срок окупаемости, мес.': '30',
      'Сумма кредита, ₽': '100000',
      'Ставка, % годовых': '20',
      'Срок кредита, мес.': '36',
      'Возраст бизнеса, мес.': '24',
    }))
      await panel.getByLabel(field, { exact: true }).fill(value);
    await panel.getByLabel('Кредитный продукт', { exact: true }).selectOption('vtb_express');
    await panel.getByRole('button', { name: 'Проверить бизнес-план' }).click();
    const result = panel.getByRole('region', { name: 'Заключение по бизнес-плану' });
    await expect(
      result.getByRole('heading', { name: 'Не подтверждён', exact: true }),
    ).toBeVisible();
    await expect(result.getByRole('columnheader', { name: 'Модель p10-p90' })).toBeVisible();
    const row = result
      .getByRole('row')
      .filter({ has: page.getByRole('rowheader', { name: 'Выручка в месяц' }) });
    await expect(row.getByRole('cell')).toHaveText([
      '920 000 ₽',
      '691 866 ₽ / 1 177 531 ₽',
      '50',
      'в диапазоне',
      'Нет',
    ]);
    await result.getByRole('link', { name: 'Перейти к полной финансовой модели' }).click();
    await expect(
      result.getByText('Чистая приведённая стоимость (NPV)', { exact: true }),
    ).toBeVisible();
    await checkDownload(page, 'Скачать заключение', /^geostart-credit-check-moscow-coffee\.pdf$/);
  });

  expect(denied, 'Запросы к API или внешним ресурсам').toEqual([]);
  expect(errors, 'Ошибки приложения').toEqual([]);
});
