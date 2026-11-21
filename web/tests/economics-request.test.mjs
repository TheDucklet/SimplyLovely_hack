import assert from 'node:assert/strict';
import test from 'node:test';
import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';

const bundle = await build({
  absWorkingDir: fileURLToPath(new URL('..', import.meta.url)),
  entryPoints: ['src/api/economicsRequest.ts'],
  bundle: true,
  write: false,
  platform: 'node',
  format: 'esm',
});
const { economicsRequest } = await import(
  'data:text/javascript;base64,' + Buffer.from(bundle.outputFiles[0].text).toString('base64')
);
const point = {
  city: 'moscow',
  niche: 'grocery',
  lat: 55.77,
  lon: 37.58,
  area_m2: 60,
  rent_rub_m2_month: 1500,
};
test('December selection starts the 36-month projection in January of the following year', () => {
  const body = economicsRequest(point, null, new Date(2026, 11, 31));
  assert.deepEqual([body.start_year, body.start_month, body.horizon_months], [2027, 1, 36]);
  assert.deepEqual(body.demand, { source: 'geostart', lat: point.lat, lon: point.lon });
  assert.deepEqual(body.premises, { area_m2: 60, rent_rub_m2_month: 1500 });
  assert.equal(body.financing, null);
});
test('default premises and explicitly zero loan rate survive serialization', () => {
  const financing = { product: 'vtb_express', loan_share: 0.5, rate_annual: 0, term_months: 12 };
  const body = economicsRequest(
    { ...point, area_m2: null, rent_rub_m2_month: null },
    financing,
    new Date(2026, 0, 31),
  );
  assert.equal(body.start_month, 2);
  assert.deepEqual(body.financing, financing);
  assert.deepEqual(body.premises, { area_m2: null, rent_rub_m2_month: null });
});
