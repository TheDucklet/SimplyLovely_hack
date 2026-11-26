import assert from 'node:assert/strict';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const bundle = await build({
  entryPoints: [fileURLToPath(new URL('../widget/api.ts', import.meta.url))],
  bundle: true,
  write: false,
  platform: 'node',
  format: 'esm',
});
const { settings } = await import(
  'data:text/javascript;base64,' + Buffer.from(bundle.outputFiles[0].text).toString('base64')
);

function element(overrides = {}) {
  const attributes = {
    city: 'moscow',
    niche: 'coffee',
    lat: '55.76',
    lon: '37.62',
    api: '/geostart/',
    ...overrides,
  };
  return {
    getAttribute: (name) => attributes[name] ?? null,
    ownerDocument: { URL: 'https://bank.example/cabinet' },
  };
}

test('Префикс API сохраняется для абсолютного адреса и пути на сайте кабинета', () => {
  assert.equal(settings(element()).api, 'https://bank.example/geostart');
  assert.equal(
    settings(element({ api: 'https://service.example/proxy/' })).api,
    'https://service.example/proxy',
  );
});

test('Отсутствующая координата отличается от нулевой', () => {
  assert.equal(settings(element({ lat: '0', lon: '0' })).point.lon, 0);
  for (const lat of [null, ' ', 'NaN', '90.1'])
    assert.throws(() => settings(element({ lat })), /lat/);
  assert.throws(() => settings(element({ lon: '-180.1' })), /lon/);
});
