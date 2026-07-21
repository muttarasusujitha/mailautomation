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
  const coreApiTarget =
    env.VITE_CORE_API_PROXY_TARGET ||
    env.VITE_API_PROXY_TARGET ||
    'http://127.0.0.1:8000'
  const intelligenceServiceTarget = env.VITE_INTELLIGENCE_SERVICE_PROXY_TARGET || 'http://127.0.0.1:8000'
  const emailServiceTarget = env.VITE_EMAIL_SERVICE_PROXY_TARGET || 'http://127.0.0.1:8000'
  const trainerServiceTarget = env.VITE_TRAINER_SERVICE_PROXY_TARGET || 'http://127.0.0.1:8000'
  const rewriteApiToV1 = env.VITE_API_PROXY_REWRITE_TO_V1 !== 'false'

  return {
    plugins: [react()],
    server: {
      port: 5174,
      strictPort: true,
      proxy: {
        '/api/client-leads': apiProxyConfig(intelligenceServiceTarget, rewriteApiToV1),
        '/api/linkedin-leads': apiProxyConfig(intelligenceServiceTarget, rewriteApiToV1),
        '/api/trainer-profile-leads': apiProxyConfig(intelligenceServiceTarget, rewriteApiToV1),
        '/api/gmail': apiProxyConfig(emailServiceTarget, rewriteApiToV1),
        '/api/email': apiProxyConfig(emailServiceTarget, rewriteApiToV1),
        '/api/emails': apiProxyConfig(emailServiceTarget, rewriteApiToV1),
        '/api/inbox': apiProxyConfig(emailServiceTarget, rewriteApiToV1),
        '/api/client-conversations': apiProxyConfig(emailServiceTarget, rewriteApiToV1),
        '/api/business-excel': apiProxyConfig(emailServiceTarget, rewriteApiToV1),
        '/api/client-updates': apiProxyConfig(emailServiceTarget, rewriteApiToV1),
        '/api/toc': apiProxyConfig(trainerServiceTarget, rewriteApiToV1),
        '/api/trainers': apiProxyConfig(trainerServiceTarget, rewriteApiToV1),
        '/api/resume-data': apiProxyConfig(trainerServiceTarget, rewriteApiToV1),
        '/api/resume-uploads': apiProxyConfig(trainerServiceTarget, rewriteApiToV1),
        '/api/shortlists': apiProxyConfig(trainerServiceTarget, rewriteApiToV1),
        '/api/interview-schedules': apiProxyConfig(trainerServiceTarget, rewriteApiToV1),
        '/api/interview-reminders': apiProxyConfig(trainerServiceTarget, rewriteApiToV1),
        '/api': apiProxyConfig(coreApiTarget, rewriteApiToV1),
      }
    }
  }
})
