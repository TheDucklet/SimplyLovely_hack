import assert from 'node:assert/strict';
import test from 'node:test';
import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';

const bundle = await build({
  absWorkingDir: fileURLToPath(new URL('..', import.meta.url)),
  entryPoints: ['src/whatIf.ts'],
  bundle: true,
  write: false,
  platform: 'node',
  format: 'esm',
});
const { scenarioRequest, compareScenarios } = await import(
  'data:text/javascript;base64,' + Buffer.from(bundle.outputFiles[0].text).toString('base64')
);
const report = {
  demand: { revenue_steady_month: { p10: 100, p50: 200, p90: 300 } },
  assumptions: [{ name: 'Ставка аренды района', value: 1234 }],
  investment: { capex: 10000 },
  credit: { first_payment: 0, dscr_min: { p50: null } },
  metrics: {
    profit_steady_month: { p50: 20 },
    npv: { p50: 420 },
    payback_months: { p50: null },
    break_even_revenue_month: { p50: 150 },
  },
};
const base = {
  city: 'tula',
  niche: 'coffee',
  demand: { source: 'geostart', lat: 54.193, lon: 37.617 },
  premises: { area_m2: 35 },
  operations: { staff_count: 3 },
};
test('scenario scales each original percentile even after another scenario was calculated', () => {
  const before = structuredClone(report);
  for (const [check, flow, multiplier] of [
    [50, 50, 2.25],
    [-50, -50, 0.25],
    [0, 0, 1],
  ]) {
    const body = scenarioRequest(base, report, { check: String(check), flow: String(flow) });
    assert.deepEqual(body.demand, {
      source: 'revenue',
      provider: 'что если',
      revenue_month: { p10: 100 * multiplier, p50: 200 * multiplier, p90: 300 * multiplier },
    });
    assert.equal(body.premises.rent_rub_m2_month, 1234);
    assert.equal(body.premises.area_m2, 35);
  }
  assert.deepEqual(report, before);
  assert.equal(base.demand.source, 'geostart');
});
test('zero values override baseline costs and zero loan share removes the loan', () => {
  const body = scenarioRequest({ ...base, financing: { loan_share: 0.4 } }, report, {
    share: '0',
    staff: '0',
    capex: '0',
  });
  assert.equal(body.financing, null);
  assert.equal(body.operations.staff_count, 0);
  assert.equal(body.investment.capex_rub, 0);
});
test('recovering payback and reducing payments improve their indicators', () => {
  const next = {
    ...report,
    metrics: { ...report.metrics, payback_months: { p50: 20 } },
    credit: { first_payment: 900, dscr_min: { p50: 1.8 } },
  };
  const rows = compareScenarios(
    { ...report, credit: { first_payment: 1000, dscr_min: { p50: 1.5 } } },
    next,
  );
  assert.equal(rows.find((row) => row.label.includes('Окупаемость')).delta, 'Окупается · лучше');
  assert.equal(rows.find((row) => row.label === 'Первый платёж').delta, '−100 ₽ · лучше');
  assert.equal(rows.find((row) => row.label.includes('DSCR')).delta, '+0,3 · лучше');
});
