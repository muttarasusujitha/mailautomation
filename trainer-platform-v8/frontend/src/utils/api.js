import axios from 'axios'

const api = axios.create({ baseURL: '/api', timeout: 60000 })

api.interceptors.response.use(
  res => res,
  err => Promise.reject(new Error(err.response?.data?.detail || err.message || 'Error'))
)

export const uploadTrainers    = (file)   => { const f = new FormData(); f.append('file', file); return api.post('/trainers/upload', f) }
export const getTrainers       = (params) => api.get('/trainers', { params })
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
export const clearDatabase     = ()       => api.delete('/database/clear')

export default api
