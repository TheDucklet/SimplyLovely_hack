import { expect, test } from '@playwright/test';
import Ajv2020 from 'ajv/dist/2020.js';
import { readFileSync } from 'node:fs';

const contract = JSON.parse(
  readFileSync(new URL('../../docs/api-v2.openapi.json', import.meta.url), 'utf8'),
);
const validator = new Ajv2020({ strict: false, allErrors: true });
validator.addSchema(contract, 'geostart');
const responses = [
  ['economics', 'post', 'economics'],
  ['economics', 'post', 'economics-plus-ten'],
  ['credit-check', 'post', 'credit-check'],
  ['credit-products', 'get', 'credit-products'],
  ['sensitivity', 'post', 'sensitivity'],
];

for (const [endpoint, method, fixture] of responses) {
  test('Ответ «' + fixture + '» соответствует OpenAPI', () => {
    const path = '~1api~1v2~1' + endpoint;
    const schema = validator.compile({
      $ref:
        'geostart#/paths/' +
        path +
        '/' +
        method +
        '/responses/200/content/application~1json/schema',
    });
    const sample = JSON.parse(
      readFileSync(new URL('../src/mocks/' + fixture + '.json', import.meta.url), 'utf8'),
    );
    expect(schema(sample), validator.errorsText(schema.errors)).toBe(true);
  });
}
