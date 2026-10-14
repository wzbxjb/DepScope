import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true, proxy: { '/api': 'http://127.0.0.1:8100', '/health': 'http://127.0.0.1:8100' } },
  test: { environment: 'jsdom', setupFiles: ['./tests/setup.ts'], exclude: ['node_modules/**', 'e2e/**'] },
});
