// vite.config.js - build/dev-server settings for the React app.
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()], // enables JSX + fast refresh
  server: {
    port: 5173,
    // In development the browser talks only to Vite (same origin), and Vite forwards /api/* to the Node
    // backend. Same-origin means the httpOnly SameSite=Strict login cookie works with no CORS tricks.
    proxy: { '/api': { target: 'http://localhost:4000', changeOrigin: false } },
  },
});
