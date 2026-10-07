import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

const apiProxyConfig = (target, rewriteApiToV1) => ({
  target,
  changeOrigin: true,
  timeout: 300000,
  proxyTimeout: 300000,
  ...(rewriteApiToV1 && {
    rewrite: path => path.replace(/^\/api(?=\/|$)/, '/api/v1'),
  }),
})

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // Browser traffic must never bypass the session-checking gateway.
  const coreApiTarget = env.VITE_API_PROXY_TARGET || 'http://ts-gateway:80'
  const rewriteApiToV1 = env.VITE_API_PROXY_REWRITE_TO_V1 !== 'false'
  const devHost = env.VITE_DEV_HOST || '0.0.0.0'
  const devPort = Number(env.VITE_DEV_PORT || 5174)

  return {
    plugins: [react()],
    // Keep all lazy-loaded pages on the same React runtime. This prevents hook
    // dispatcher errors when Vite's dependency cache is refreshed after updates.
    resolve: {
      dedupe: ['react', 'react-dom'],
    },
    optimizeDeps: {
      include: ['react', 'react-dom', 'react/jsx-runtime', 'react/jsx-dev-runtime'],
    },
    server: {
      host: devHost,
      port: devPort,
      strictPort: false,
      proxy: {
        '/api': apiProxyConfig(coreApiTarget, rewriteApiToV1),
      }
    }
  }
})
