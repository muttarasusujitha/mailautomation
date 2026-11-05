import api from './api'

const wait = milliseconds => new Promise(resolve => window.setTimeout(resolve, milliseconds))

export async function syncGmailInbox({ limit = 50, sinceDays = 3, process = false } = {}) {
  const response = await api.post('/gmail/sync-now', null, {
    params: { limit, since_days: sinceDays, process },
    timeout: 20000,
    retry: false,
  })
  const syncId = response.data?.sync_id
  if (!syncId) {
    throw new Error(response.data?.message || 'Gmail did not return a sync status id')
  }

  const deadline = Date.now() + 120000
  while (Date.now() < deadline) {
    await wait(2000)
    const statusResponse = await api.get('/gmail/sync-status/' + encodeURIComponent(syncId), {
      timeout: 10000,
      retry: false,
    })
    const status = statusResponse.data || {}
    if (status.status === 'completed') return status
    if (status.status === 'failed') {
      throw new Error(status.error || 'Gmail inbox sync failed')
    }
  }
  throw new Error('Inbox sync is still running. Refresh Client Requests shortly to see the latest messages.')
}
