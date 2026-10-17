import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const directory = fileURLToPath(new URL('..', import.meta.url));
const bundle = await build({
  absWorkingDir: directory,
  entryPoints: { comparison: 'src/comparison.ts', requestQueue: 'src/api/requestQueue.ts' },
  outdir: 'test-output',
  bundle: true,
  write: false,
  platform: 'node',
  format: 'esm',
});
const loadModule = (name) =>
  import(
    `data:text/javascript;base64,${Buffer.from(bundle.outputFiles.find((file) => file.path.endsWith(`${name}.js`)).text).toString('base64')}`
  );
const { compareReports } = await loadModule('comparison');
const { createRequestQueue } = await loadModule('requestQueue');
const fixture = JSON.parse(
  await readFile(new URL('../src/mocks/report.json', import.meta.url), 'utf8'),
);

test('comparison subtracts the first address from the second for all money metrics', () => {
  const first = structuredClone(fixture);
  const second = structuredClone(fixture);
  first.revenue_month.p50 = 100000;
  second.revenue_month.p50 = 150000;
  first.costs_month.total = 80000;
  second.costs_month.total = 100000;
  first.profit_month_p50 = -20000;
  second.profit_month_p50 = 50000;
  const rows = compareReports(first, second);
  assert.equal(rows.length, 4);
  assert.deepEqual(
    rows.slice(0, 3).map((row) => row.difference),
    ['+50 000 ₽', '+20 000 ₽', '+70 000 ₽'],
  );
  assert.deepEqual(
    rows.slice(0, 3).map((row) => row.tone),
    ['positive', 'negative', 'positive'],
  );
  assert.deepEqual(
    compareReports(second, first)
      .slice(0, 3)
      .map((row) => row.difference),
    ['−50 000 ₽', '−20 000 ₽', '−70 000 ₽'],
  );
});

test('finite payback difference keeps the sign and treats a shorter period as favorable', () => {
  const first = { ...fixture, payback_months_p50: 6.1 };
  const second = { ...fixture, payback_months_p50: 4.5 };
  const row = compareReports(first, second)[3];
  assert.equal(row.difference, '−1,6 мес.');
  assert.equal(row.direction, 'Быстрее');
  assert.equal(row.tone, 'positive');
  assert.equal(compareReports(second, first)[3].difference, '+1,6 мес.');
});

for (const [first, second, expected] of [
  [null, null, 'Оба не окупаются'],
  [null, 12, 'Адрес 1 не окупается'],
  [12, null, 'Адрес 2 не окупается'],
]) {
  test(`missing payback ${first}/${second} stays explicit without numeric substitution`, () => {
    const row = compareReports(
      { ...fixture, payback_months_p50: first },
      { ...fixture, payback_months_p50: second },
    )[3];
    assert.equal(row.difference, expected);
    assert.equal(row.tone, 'neutral');
    assert.equal(row.direction, '');
  });
}

test('equal displayed values have zero differences without a negative zero', () => {
  const first = structuredClone(fixture);
  const second = structuredClone(fixture);
  first.revenue_month.p50 = 1000.1;
  second.revenue_month.p50 = 1000.2;
  first.payback_months_p50 = 6.14;
  second.payback_months_p50 = 6.11;
  const rows = compareReports(first, second);
  assert.deepEqual(
    rows.map((row) => row.difference),
    ['0 ₽', '0 ₽', '0 ₽', '0 мес.'],
  );
  assert.ok(rows.every((row) => row.tone === 'neutral'));
});

test('money difference agrees with rounded values shown in the two report columns', () => {
  const first = structuredClone(fixture);
  const second = structuredClone(fixture);
  first.revenue_month.p50 = 1000.4;
  second.revenue_month.p50 = 1000.6;
  const row = compareReports(first, second)[0];
  assert.equal(row.first, '1 000 ₽');
  assert.equal(row.second, '1 001 ₽');
  assert.equal(row.difference, '+1 ₽');
});

test('report requests share one queue and keep their result order', async () => {
  const enqueue = createRequestQueue();
  const events = [];
  let release;
  const first = enqueue(async () => {
    events.push('first started');
    await new Promise((resolve) => {
      release = resolve;
    });
    events.push('first completed');
    return 1;
  });
  const second = enqueue(async () => {
    events.push('second started');
    return 2;
  });
  await Promise.resolve();
  assert.deepEqual(events, ['first started']);
  release();
  assert.deepEqual(await Promise.all([first, second]), [1, 2]);
  assert.deepEqual(events, ['first started', 'first completed', 'second started']);
});

test('a failed report does not block the next address in the shared queue', async () => {
  const enqueue = createRequestQueue();
  const failed = enqueue(async () => {
    throw new Error('outside city');
  });
  const next = enqueue(async () => 'second report');
  await assert.rejects(failed, /outside city/);
  assert.equal(await next, 'second report');
});
