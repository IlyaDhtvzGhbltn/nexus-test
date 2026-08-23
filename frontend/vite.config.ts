import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// В docker-compose бэкенд доступен как http://backend:8000,
// при локальном запуске без docker — http://localhost:8000
const target = process.env.VITE_PROXY_TARGET ?? 'http://localhost:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target, changeOrigin: true },
      '/hosted': { target, changeOrigin: true },
      '/proxy': { target, changeOrigin: true },
    },
  },
});
