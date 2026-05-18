import axios from 'axios'

const api = axios.create({ baseURL: '/api', timeout: 300000 })

function formatApiError(value) {
  if (!value) return ''
  if (typeof value === 'string') return value
  if (Array.isArray(value)) {
    return value.map(formatApiError).filter(Boolean).join('\n')
  }
  if (typeof value === 'object') {
    if (value.msg) {
      const location = Array.isArray(value.loc) ? value.loc.join(' > ') : value.loc
      return [location, value.msg].filter(Boolean).join(': ')
    }
    if (value.message) return formatApiError(value.message)
    if (value.error) return formatApiError(value.error)
    if (value.detail) return formatApiError(value.detail)
    try {
      return JSON.stringify(value)
    } catch {
      return String(value)
    }
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

export const uploadResumes     = (files, confirm = false, onUploadProgress) => {
  const form = new FormData()
  const fileList = Array.isArray(files) ? files : [files]
  const fieldName = fileList.length === 1 ? 'file' : 'files'
  fileList.forEach(file => form.append(fieldName, file))
  return api.post(`/trainers/upload-resume?confirm=${confirm ? 'true' : 'false'}`, form, { onUploadProgress })
}
export const getTrainers       = (params) => api.get('/trainers', { params })
export const getTrainerCategories = ()    => api.get('/trainers/categories')
export const getTrainerDomains    = ()    => api.get('/trainers/domains')
export const getTrainerIndustries = ()    => api.get('/trainers/industries')
export const categoriseTrainer    = (id)  => api.post(`/trainers/${id}/categorise`)
export const categoriseAllTrainers = ()   => api.post('/trainers/categorise-all')
export const getCategoriseJob     = (id)  => api.get(`/trainers/categorise-jobs/${id}`)
export const deleteTrainer     = (id)     => api.delete(`/trainers/${id}`)
export const getRequirements   = ()       => api.get('/requirements')
export const createRequirement = (data)   => api.post('/requirements', data)
export const deleteRequirement = (id)     => api.delete(`/requirements/${id}`)
export const shortlistOnly     = (data)   => api.post('/requirements/shortlist-only', data)
export const getShortlist      = (id)     => api.get(`/shortlists/${id}`)
export const getEmails         = (params) => api.get('/emails', { params })
export const checkReplies      = ()       => api.post('/emails/check-replies')
export const retryEmail        = (id)     => api.post(`/emails/${id}/retry`)
export const sendMailToOne     = (id, msg) => api.post(`/emails/${id}/send-one`, { message: msg })
export const scheduleInterview = (id, interview_date, interview_link) =>
  api.post(`/emails/${id}/schedule-interview`, null, { params: { interview_date, interview_link } })
export const getDashboardStats = ()       => api.get('/dashboard/stats')
export const getDashboardAnalytics = (params) => api.get('/dashboard/analytics', { params })
export const clearDatabase     = ()       => api.delete('/database/clear')
export const forgotPassword    = (email)  => api.post('/auth/forgot-password', { email })

export default api
