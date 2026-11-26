import { gzipSync } from 'node:zlib';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const fileName = 'geostart-widget.js';
const limit = 300_000;

export default defineConfig({
  plugins: [
    react(),
    {
      name: 'widget-size',
      generateBundle(_, files) {
        const script = files[fileName];
        if (Object.keys(files).length !== 1 || script?.type !== 'chunk')
          this.error('Сборка виджета должна содержать один файл JavaScript.');
        const size = gzipSync(script.code).byteLength;
        if (size > limit) this.error(`Размер gzip ${size} байт превышает предел ${limit} байт.`);
        this.info(`Размер виджета после gzip – ${size} байт.`);
      },
    },
  ],
  publicDir: false,
  build: {
    outDir: 'widget/dist',
    rollupOptions: {
      input: 'widget/element.tsx',
      output: { format: 'iife', entryFileNames: fileName, inlineDynamicImports: true },
    },
  },
});
