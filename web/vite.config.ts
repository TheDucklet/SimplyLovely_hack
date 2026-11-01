import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const VENDOR_CHUNKS: [RegExp, string][] = [
  [/vite[\\/]preload-helper/, 'preload'],
  [/node_modules[\\/]maplibre-gl[\\/]/, 'maplibre'],
  [/node_modules[\\/]@(deck\.gl|luma\.gl|loaders\.gl|math\.gl|probe\.gl)[\\/]/, 'deckgl'],
];

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks: (id) => VENDOR_CHUNKS.find(([pattern]) => pattern.test(id))?.[1],
      },
    },
  },
});
