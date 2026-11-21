import assert from 'node:assert/strict';
import test from 'node:test';
import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';

const bundle = await build({
  absWorkingDir: fileURLToPath(new URL('..', import.meta.url)),
  entryPoints: ['src/borrowerPlan.ts'],
  bundle: true,
  write: false,
  platform: 'node',
  format: 'esm',
});
const { borrowerPlan, emptyPlan, checkCells, coverageValue } = await import(
  'data:text/javascript;base64,' + Buffer.from(bundle.outputFiles[0].text).toString('base64')
);

test('zero values remain explicit and blank optional plan inputs are omitted', () => {
  const plan = JSON.parse(
    JSON.stringify(
      borrowerPlan({
        ...emptyPlan,
        revenue_month_rub: '1320000.45',
        loan_amount_rub: '0',
        rate_annual: '0',
        business_age_months: '0',
      }),
    ),
  );
  assert.deepEqual(plan, {
    revenue_month_rub: 1320000.45,
    loan_amount_rub: 0,
    rate_annual: 0,
    business_age_months: 0,
  });
  assert.equal(borrowerPlan({ ...emptyPlan, rate_annual: '18.5' }).rate_annual, 0.185);
});
test('percentiles are already percentages while debt coverage is a probability', () => {
  const row = checkCells({
    code: 'payback_months',
    name: 'Окупаемость',
    plan_value: 18,
    model: { p10: 12, p50: 15, p90: null },
    percentile: 75.5,
    status: 'within',
    risk_flag: false,
  });
  assert.deepEqual(row, [
    'Окупаемость',
    '18 мес.',
    '12 мес. / не достигнут',
    '75,5',
    'в диапазоне',
    'Нет',
  ]);
  assert.equal(coverageValue({ probability_dscr_ok: 0.835 }), '83,5%');
});
