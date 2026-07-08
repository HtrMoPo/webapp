import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// VITE_BASE_PATH lets the whole app (asset URLs, router history mode) be
// served from a subfolder (e.g. "/plop/" for foobar.com/plop/) when there is
// no dedicated domain. Vite's default build already content-hashes output
// filenames for cache-busting.
export default defineConfig({
  plugins: [vue()],
  base: process.env.VITE_BASE_PATH || '/',
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
  build: {
    outDir: '../backend/static',
    emptyOutDir: true,
  },
})
