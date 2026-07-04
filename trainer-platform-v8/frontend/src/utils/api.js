import axios from 'axios'

const api = axios.create({ baseURL: '/api', timeout: 300000 })

function stringifyApiError(value) {
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function formatApiObjectError(value) {
  if (value.msg) {
    const location = Array.isArray(value.loc) ? value.loc.join(' > ') : value.loc
    return [location, value.msg].filter(Boolean).join(': ')
  }

  const nested = value.message ?? value.error ?? value.detail
  return nested ? formatApiError(nested) : stringifyApiError(value)
}

function formatApiError(value) {
  if (!value) return ''
  if (typeof value === 'string') return value
  if (Array.isArray(value)) {
    return value.map(formatApiError).filter(Boolean).join('\n')
  }
  if (typeof value === 'object') {
    return formatApiObjectError(value)
  }
  return String(value)
}

api.interceptors.response.use(
  res => res,
  err => {
    const data = err.response?.data
    const message = formatApiError(data?.detail || data?.message || data?.error || data) || err.message || 'Error'
    return Promise.reject(new Error(message))
  }
)

export const uploadResumes     = (files, confirm, onUploadProgress) => {
  const form = new FormData()
  const fileList = Array.isArray(files) ? files : [files]
  const fieldName = fileList.length === 1 ? 'file' : 'files'
  fileList.forEach(file => form.append(fieldName, file))
  return api.post(`/trainers/upload-resume?confirm=${confirm ? 'true' : 'false'}`, form, { onUploadProgress })
}
export const confirmResumePreviews = (uploadIds, corrections = {}) =>
  api.post('/trainers/confirm-resumes', { upload_ids: uploadIds, corrections })
export const previewResumeDataByEmail = (email) =>
  api.get('/resume-data/by-email', { params: { email } })
export const deleteResumeDataByEmail = (email, includeLogs = false) =>
  api.delete('/resume-data/by-email', { params: { email, include_logs: includeLogs } })
export const previewResumeDataByDomain = (domain) =>
  api.get('/resume-data/by-domain', { params: { domain } })
export const deleteResumeDataByDomain = (domain, includeLogs = false) =>
  api.delete('/resume-data/by-domain', { params: { domain, include_logs: includeLogs } })
export const getResumeDomainSummary = () =>
  api.get('/resume-data/domain-summary')
export const getTrainers       = (params) => api.get('/trainers', { params })
export const getTrainer        = (id)     => api.get(`/trainers/${id}`)
export const getTrainerCategories = ()    => api.get('/trainers/categories')
export const getTrainerDomains    = ()    => api.get('/trainers/domains')
export const getTrainerIndustries = ()    => api.get('/trainers/industries')
export const categoriseTrainer    = (id)  => api.post(`/trainers/${id}/categorise`)
export const categoriseAllTrainers = ()   => api.post('/trainers/categorise-all')
export const getCategoriseJob     = (id)  => api.get(`/trainers/categorise-jobs/${id}`)
export const deleteTrainer     = (id)     => api.delete(`/trainers/${id}`)
export const updateTrainer     = (id, data) => api.patch(`/trainers/${id}`, data)
export const requestTrainerResume = (id, data) => api.post(`/trainers/${id}/request-resume`, data)
export const sendTrainerAutomationMail = (id, data) => api.post(`/trainers/${id}/send-automation-mail`, data)
export const tickTrainerAutomationPipeline = (id, data) => api.post(`/trainers/${id}/automation-pipeline/tick`, data)
export const getTrainerAutomationStatus = (id) => api.get(`/trainers/${id}/automation-status`)
export const getTrainerConversationThread = (id, params = {}) => api.get(`/trainers/${id}/conversation-thread`, { params })
export const getRequirements   = ()       => api.get('/requirements')
export const createRequirement = (data)   => api.post('/requirements', data)
export const updateRequirement = (id, data) => api.patch(`/requirements/${id}`, data)
export const deleteRequirement = (id)     => api.delete(`/requirements/${id}`)
export const shortlistOnly     = (data)   => api.post('/requirements/shortlist-only', data)
export const getShortlist      = (id)     => api.get(`/shortlists/${id}`)
export const getEmails         = (params) => api.get('/emails', { params })
export const checkReplies      = ()       => api.post('/emails/check-replies')
export const retryEmail        = (id)     => api.post(`/emails/${id}/retry`)
export const sendMailToOne     = (id, msg) => api.post(`/emails/${id}/send-one`, { message: msg })
export const sendClientSlotsFromEmail = (id, force = true, payload = {}) =>
  api.post(`/emails/${id}/send-client-slots`, { force, ...payload })
export const scheduleInterview = (id, interview_date, interview_link) =>
  api.post(`/emails/${id}/schedule-interview`, null, { params: { interview_date, interview_link } })
export const getDashboardStats = ()       => api.get('/dashboard/stats')
export const getDashboardAnalytics = (params) => api.get('/dashboard/analytics', { params })
export const clearDatabase     = ()       => api.delete('/database/clear')
export const forgotPassword    = (email)  => api.post('/auth/forgot-password', { email })
export const getTocKnowledge   = ()       => api.get('/toc/knowledge')
export const getTocKnowledgeDomain = (key) => api.get(`/toc/knowledge/${key}`)
export const saveTocKnowledge  = (data)   => api.post('/toc/knowledge', data)
export const importTocKnowledge = (text)   => api.post('/toc/knowledge/import', { text })
export const deleteTocKnowledge = (key)    => api.delete(`/toc/knowledge/${key}`)

export default api
