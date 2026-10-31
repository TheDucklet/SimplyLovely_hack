import assert from 'node:assert/strict';
import test from 'node:test';
import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';

const directory = fileURLToPath(new URL('..', import.meta.url));
const bundle = await build({
  absWorkingDir: directory,
  entryPoints: ['src/welcome.ts'],
  bundle: true,
  write: false,
  platform: 'node',
  format: 'esm',
});
const { WELCOME_STORAGE_KEY, markWelcomeSeen, welcomeSeen } = await import(
  `data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`
);

const memoryStorage = () => {
  const values = new Map();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  };
};
const brokenStorage = {
  getItem: () => {
    throw new Error('blocked');
  },
  setItem: () => {
    throw new Error('blocked');
  },
};

test('welcome is shown on the first visit and hidden after it is marked as seen', () => {
  const storage = memoryStorage();
  assert.equal(welcomeSeen(storage), false);
  markWelcomeSeen(storage);
  assert.equal(welcomeSeen(storage), true);
  assert.equal(storage.getItem(WELCOME_STORAGE_KEY), '1');
});

test('welcome survives blocked or missing storage', () => {
  assert.equal(welcomeSeen(brokenStorage), false);
  assert.doesNotThrow(() => markWelcomeSeen(brokenStorage));
  assert.equal(welcomeSeen(undefined), false);
  assert.doesNotThrow(() => markWelcomeSeen(undefined));
});
