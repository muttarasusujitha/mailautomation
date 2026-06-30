import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || 'http://localhost'
const rewriteApiToV1 = process.env.VITE_API_PROXY_REWRITE_TO_V1 !== 'false'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: apiProxyTarget,
        changeOrigin: true,
        timeout: 300000,
        proxyTimeout: 300000,
        ...(rewriteApiToV1 && {
          rewrite: path => path.replace(/^\/api(?=\/|$)/, '/api/v1'),
        }),
      }
    }
  }
})



