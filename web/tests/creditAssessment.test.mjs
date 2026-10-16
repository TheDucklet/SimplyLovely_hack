import assert from 'node:assert/strict';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const bundle = await build({
  absWorkingDir: fileURLToPath(new URL('..', import.meta.url)),
  entryPoints: ['src/creditAssessment.ts'],
  bundle: true,
  write: false,
  platform: 'node',
  format: 'esm',
});
const { parsePlanRevenue, assessPlanRevenue, formatRevenue } = await import(
  `data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`
);
const range = { p10: 100, p50: 150, p90: 200 };

test('plan input accepts Russian decimal notation, grouped rubles and zero', () => {
  for (const [input, value] of [
    ['1 000 000,50', 1000000.5],
    ['1000.25', 1000.25],
    ['0', 0],
  ])
    assert.deepEqual(parsePlanRevenue(input), { kind: 'valid', value });
});

test('plan input rejects negative, non-finite, exponent and imprecise amounts', () => {
  for (const input of [
    '-1',
    'NaN',
    'Infinity',
    '1e6',
    '100,001',
    '1,2,3',
    'текст',
    '9999999999999999999',
  ])
    assert.equal(parsePlanRevenue(input).kind, 'invalid', input);
});

test('blank plan input stays empty instead of becoming zero', () => {
  assert.equal(parsePlanRevenue('').kind, 'empty');
  assert.equal(parsePlanRevenue('  ').kind, 'empty');
});

test('below-range deviation uses p10 as the denominator', () => {
  const result = assessPlanRevenue(range, 75);
  assert.equal(result.kind, 'below');
  assert.equal(result.differenceRub, 25);
  assert.equal(result.differencePercent, 25);
  assert.equal(result.message, 'Выручка в плане ниже p10 модели на 25%');
});

test('both boundaries and the median belong to the inclusive range', () => {
  for (const value of [range.p10, range.p50, range.p90]) {
    const result = assessPlanRevenue(range, value);
    assert.equal(result.kind, 'within');
    assert.equal(result.differenceRub, 0);
  }
});

test('above-range deviation uses p90 and reports the requested 35 percent example', () => {
  const result = assessPlanRevenue(range, 270);
  assert.equal(result.kind, 'above');
  assert.equal(result.differenceRub, 70);
  assert.equal(result.differencePercent, 35);
  assert.equal(result.message, 'Выручка в плане выше p90 модели на 35%');
});

test('fractional API percentiles use the same kopeck precision as the displayed boundaries', () => {
  const fractional = { p10: 1421957.543392, p50: 2168636.34, p90: 3380925.60001 };
  assert.equal(assessPlanRevenue(fractional, 1421957.54).kind, 'within');
  assert.equal(assessPlanRevenue(fractional, 3380925.6).kind, 'within');
  assert.equal(assessPlanRevenue(fractional, 1421957.53).kind, 'below');
  assert.equal(assessPlanRevenue(fractional, 3380925.61).kind, 'above');
});

test('a small nonzero deviation cannot be displayed as zero percent', () => {
  assert.equal(
    assessPlanRevenue(range, 200.01).message,
    'Выручка в плане выше p90 модели менее чем на 0,1%',
  );
});

test('a zero plan is 100 percent below a positive p10', () => {
  const result = assessPlanRevenue(range, 0);
  assert.equal(result.kind, 'below');
  assert.equal(result.differencePercent, 100);
});

test('a zero model range avoids division by zero and states the ruble difference', () => {
  const zero = { p10: 0, p50: 0, p90: 0 };
  assert.equal(assessPlanRevenue(zero, 0).kind, 'within');
  const result = assessPlanRevenue(zero, 100);
  assert.equal(result.differencePercent, null);
  assert.ok(result.message.includes('на 100 ₽'));
  assert.ok(!/Infinity|NaN/.test(result.message));
});

test('invalid model ranges and invalid numeric plans produce no assessment', () => {
  for (const invalid of [
    { p10: -1, p50: 10, p90: 20 },
    { p10: 200, p50: 150, p90: 100 },
    { p10: 100, p50: 300, p90: 200 },
    { p10: 0, p50: 1, p90: Infinity },
  ])
    assert.equal(assessPlanRevenue(invalid, 100), null);
  assert.equal(assessPlanRevenue(range, NaN), null);
  assert.equal(assessPlanRevenue(range, -1), null);
});

test('a collapsed nonzero range still has meaningful above and below comparisons', () => {
  const collapsed = { p10: 100, p50: 100, p90: 100 };
  assert.equal(assessPlanRevenue(collapsed, 100).kind, 'within');
  assert.equal(assessPlanRevenue(collapsed, 110).differencePercent, 10);
  assert.equal(assessPlanRevenue(collapsed, 90).differencePercent, 10);
});

test('revenue labels keep kopecks and normalize nonbreaking spaces', () => {
  assert.equal(formatRevenue(3000000.5), '3 000 000,5 ₽');
});
