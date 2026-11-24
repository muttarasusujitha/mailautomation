import { useState, useEffect } from 'react'
import {
  X,
  Mail,
  Phone,
  Linkedin,
  MapPin,
  Clock,
  Award,
  Briefcase,
  ExternalLink,
  Copy,
  CheckCircle2,
  FileText,
  Download,
  MessageSquare,
  Star,
  Zap,
  Users,
} from 'lucide-react'
import clsx from 'clsx'
import toast from 'react-hot-toast'

export function TrainerDetailModal({ trainer, onClose }) {
  const [copied, setCopied] = useState(null)

  if (!trainer) return null

  const displayName = trainer.display_name || trainer.name || trainer.role_designation || 'Trainer'
  const matchScore = trainer.match_score || trainer.resume_rank_score || 0
  const matchRank = trainer.match_rank || trainer.rank || Math.floor(Math.random() * 1000) + 1
  const matchTotal = 100
  const category = trainer.primary_category || trainer.technology_category || trainer.category || 'Uncategorised'
  const status = trainer.status || 'new'
  
  const skills = Array.isArray(trainer.skills) ? trainer.skills 
    : trainer.skills ? String(trainer.skills).split(/[,;\n]/).map(s => s.trim()).filter(Boolean)
    : []
  
  const technologies = trainer.technologies ? String(trainer.technologies).split(/[,;\n]/).map(t => t.trim()).filter(Boolean) : []
  const allTech = [...new Set([...skills, ...technologies])].slice(0, 15)
  
  const certifications = Array.isArray(trainer.certifications) ? trainer.certifications
    : trainer.certifications ? String(trainer.certifications).split(/[,;\n]/).map(c => c.trim()).filter(Boolean)
    : []
  
  const pastClients = Array.isArray(trainer.past_clients) ? trainer.past_clients
    : trainer.past_clients ? String(trainer.past_clients).split(/[,;\n]/).map(c => c.trim()).filter(Boolean)
    : []

  const experience = trainer.experience_raw || (trainer.experience_years ? `${trainer.experience_years}+ years` : 'Not available')
  const location = trainer.location || 'Not available'
  const rating = trainer.rating || trainer.avg_rating || Math.round(matchScore / 20 * 10) / 10 || 0
  const totalRatings = trainer.total_ratings || trainer.review_count || Math.floor(Math.random() * 50) + 5
  
  const profileDescription = trainer.objective || trainer.summary || `${displayName} is shortlisted for ${category} with a match score of ${matchScore}/100.`
  
  const resumeEvidence = trainer.resume ? trainer.resume.substring(0, 800) : ''
  const resumeUrl = trainer.resume_url || trainer.resume_link || null
  const skype = trainer.skype || trainer.skype_id || null
  
  // Parse match breakdown or generate defaults
  const matchBreakdown = trainer.match_breakdown || {
    technology: { score: 35, total: 35 },
    skills: { score: 20, total: 25 },
    experience: { score: 13, total: 15 },
    certifications: { score: 0, total: 1 },
    location: { score: 0, total: 1 },
  }

  const breakdownItems = [
    { label: 'Technology', ...matchBreakdown.technology || { score: 35, total: 35 }, color: 'blue' },
    { label: 'Skills', ...matchBreakdown.skills || { score: 20, total: 25 }, color: 'blue' },
    { label: 'Experience', ...matchBreakdown.experience || { score: 13, total: 15 }, color: 'blue' },
    { label: 'Certifications', ...matchBreakdown.certifications || { score: 0, total: 1 }, color: 'slate' },
    { label: 'Location', ...matchBreakdown.location || { score: 0, total: 1 }, color: 'slate' },
  ]
  
  const copyToClipboard = (text, label) => {
    navigator.clipboard.writeText(text)
    setCopied(label)
    setTimeout(() => setCopied(null), 2000)
  }

  const STATUS_BADGE = {
    new: 'bg-slate-100 text-slate-700',
    pending_review: 'bg-yellow-100 text-yellow-700',
    contacted: 'bg-blue-100 text-blue-700',
    interested: 'bg-green-100 text-green-700',
    declined: 'bg-red-100 text-red-700',
    confirmed: 'bg-emerald-100 text-emerald-700',
  }

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center p-3 sm:p-4 bg-black/40 backdrop-blur-sm overflow-y-auto">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-5xl my-8">
        {/* Header */}
        <div className="sticky top-0 z-10 bg-white border-b border-slate-200 px-6 py-2">
          <div className="flex items-start justify-between gap-4 mb-2">
            <div className="flex items-center gap-3">
              <div className="inline-flex items-center gap-2">
                <span className="text-xs font-bold text-blue-600">Rank #1</span>
                <span className="text-xs font-bold text-green-600">{matchScore}/100 match</span>
                <span className={clsx('px-2 py-0.5 rounded-full text-xs font-semibold border', STATUS_BADGE[status] || STATUS_BADGE.new)}>
                  {status}
                </span>
              </div>
            </div>
            <button
              onClick={onClose}
              className="p-2 hover:bg-slate-100 rounded-lg transition-colors flex-shrink-0"
              aria-label="Close"
            >
              <X className="w-5 h-5 text-slate-500" />
            </button>
          </div>
          
          <div>
            <h1 className="text-xl font-bold text-slate-900">{displayName}</h1>
            <p className="text-xs text-slate-600 mt-0.5 leading-tight">{allTech.join(', ')}</p>
          </div>
        </div>

        {/* Content - Two Column Layout */}
        <div className="overflow-y-auto max-h-[calc(100vh-160px)] px-6 py-8">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            
            {/* LEFT COLUMN */}
            <div className="space-y-6">
              
              {/* Profile Description */}
              <div className="space-y-1 p-3 border border-slate-200 rounded-lg bg-slate-50">
                <div className="flex items-center gap-2">
                  <FileText className="w-4 h-4 text-blue-600" />
                  <h3 className="font-semibold text-sm text-slate-900">Profile Description</h3>
                </div>
                <p className="text-xs text-slate-700 leading-relaxed">{profileDescription}</p>
              </div>

              {/* Resume Evidence */}
              {resumeEvidence && (
                <div className="space-y-2 p-4 border border-slate-200 rounded-xl bg-white">
                  <div className="flex items-center gap-2">
                    <FileText className="w-5 h-5 text-slate-600" />
                    <h3 className="font-semibold text-slate-900">Resume Evidence</h3>
                  </div>
                  <pre className="text-xs text-slate-600 leading-relaxed whitespace-pre-wrap font-mono bg-slate-50 p-3 rounded-lg max-h-48 overflow-y-auto">
                    {resumeEvidence.trim()}
                    {trainer.resume && trainer.resume.length > 800 && '...'}
                  </pre>
                </div>
              )}

              {/* Skills & Technologies */}
              {allTech.length > 0 && (
                <div className="space-y-3 p-4 border border-slate-200 rounded-xl bg-white">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="w-5 h-5 text-yellow-500" />
                    <h3 className="font-semibold text-slate-900">Skills & Technologies</h3>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {allTech.map(tech => (
                      <span
                        key={tech}
                        className="inline-block px-3 py-1 bg-blue-50 text-blue-700 rounded-full text-sm font-medium border border-blue-100"
                      >
                        {tech}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* RIGHT COLUMN */}
            <div className="space-y-6">
              
              {/* Contact & Experience */}
              <div className="space-y-2 p-3 border border-slate-200 rounded-lg bg-white">
                <h3 className="font-semibold text-sm text-slate-900 flex items-center gap-2">
                  <Mail className="w-4 h-4 text-blue-600" />
                  Contact & Experience
                </h3>
                
                <div className="space-y-1 text-xs">
                  <div className="flex items-center justify-between">
                    <span className="text-slate-600 font-semibold">Experience:</span>
                    <span className="text-slate-900">{experience}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-slate-600 font-semibold">Location:</span>
                    <span className="text-slate-900">{location}</span>
                  </div>
                  
                {rating > 0 && (
                    <div className="flex items-center justify-between">
                      <span className="text-slate-600 font-semibold">Rating:</span>
                      <div className="flex items-center gap-1">
                        <div className="flex items-center gap-0.5">
                          {[...Array(5)].map((_, i) => (
                            <Star
                              key={i}
                              className={clsx('w-3 h-3', i < Math.floor(rating) ? 'fill-yellow-400 text-yellow-400' : 'text-slate-300')}
                            />
                          ))}
                        </div>
                        <span className="text-slate-700 text-xs font-medium">{rating.toFixed(1)}</span>
                      </div>
                    </div>
                  )}
                  
                  {trainer.email && (
                    <div className="flex items-center justify-between">
                      <span className="text-slate-600 font-semibold">Email:</span>
                      <div className="flex items-center gap-2">
                        <a href={`mailto:${trainer.email}`} className="text-blue-600 hover:underline truncate text-xs">{trainer.email}</a>
                        <button
                          onClick={() => copyToClipboard(trainer.email, 'email')}
                          className="p-1 hover:bg-slate-100 rounded transition-colors flex-shrink-0"
                          title="Copy email"
                        >
                          {copied === 'email' ? <CheckCircle2 className="w-4 h-4 text-green-600" /> : <Copy className="w-4 h-4 text-slate-400" />}
                        </button>
                      </div>
                    </div>
                  )}
                  {trainer.phone && (
                    <div className="flex items-center justify-between">
                      <span className="text-slate-600 font-semibold">Phone:</span>
                      <div className="flex items-center gap-2">
                        <a href={`tel:${trainer.phone}`} className="text-blue-600 hover:underline">{trainer.phone}</a>
                        <button
                          onClick={() => copyToClipboard(trainer.phone, 'phone')}
                          className="p-1 hover:bg-slate-100 rounded transition-colors flex-shrink-0"
                          title="Copy phone"
                        >
                          {copied === 'phone' ? <CheckCircle2 className="w-4 h-4 text-green-600" /> : <Copy className="w-4 h-4 text-slate-400" />}
                        </button>
                      </div>
                    </div>
                  )}
                  {skype && (
                    <div className="flex items-center justify-between">
                      <span className="text-slate-600 font-semibold">Skype:</span>
                      <div className="flex items-center gap-2">
                        <a href={`skype:${skype}?call`} className="text-blue-600 hover:underline text-xs">{skype}</a>
                        <button
                          onClick={() => copyToClipboard(skype, 'skype')}
                          className="p-1 hover:bg-slate-100 rounded transition-colors flex-shrink-0"
                          title="Copy Skype"
                        >
                          {copied === 'skype' ? <CheckCircle2 className="w-4 h-4 text-green-600" /> : <Copy className="w-4 h-4 text-slate-400" />}
                        </button>
                      </div>
                    </div>
                  )}
                  {trainer.linkedin && trainer.linkedin !== '-' && (
                    <div className="flex items-center justify-between">
                      <span className="text-slate-600 font-semibold">LinkedIn:</span>
                      <a href={trainer.linkedin} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline flex items-center gap-1">
                        Open <ExternalLink className="w-3 h-3" />
                      </a>
                    </div>
                  )}
                  {trainer.day_rate && (
                    <div className="flex items-center justify-between">
                      <span className="text-slate-600 font-semibold">Day rate:</span>
                      <span className="text-slate-900 font-semibold text-green-600">{trainer.day_rate}</span>
                    </div>
                  )}
                  {trainer.trainings_completed && (
                    <div className="flex items-center justify-between">
                      <span className="text-slate-600 font-semibold">Trainings:</span>
                      <span className="text-slate-900">{trainer.trainings_completed}</span>
                    </div>
                  )}
                  {trainer.hourly_rate && (
                    <div className="flex items-center justify-between">
                      <span className="text-slate-600 font-semibold">Hourly rate:</span>
                      <span className="text-slate-900 font-semibold text-green-600">{trainer.hourly_rate}</span>
                    </div>
                  )}
                </div>
                
                {/* Quick Action Buttons */}
                <div className="pt-2 border-t border-slate-200 grid grid-cols-2 gap-1">
                  {trainer.email && (
                    <button
                      onClick={() => window.location.href = `mailto:${trainer.email}`}
                      className="flex items-center justify-center gap-1 px-2 py-1.5 bg-blue-50 text-blue-600 rounded text-xs hover:bg-blue-100 transition-colors font-medium"
                    >
                      <Mail className="w-3 h-3" />
                      Email
                    </button>
                  )}
                  {trainer.phone && (
                    <button
                      onClick={() => window.location.href = `tel:${trainer.phone}`}
                      className="flex items-center justify-center gap-1 px-2 py-1.5 bg-green-50 text-green-600 rounded text-xs hover:bg-green-100 transition-colors font-medium"
                    >
                      <Phone className="w-3 h-3" />
                      Call
                    </button>
                  )}
                </div>
              </div>

              {/* Certifications & Clients */}
              <div className="space-y-3 p-4 border border-slate-200 rounded-xl bg-white">
                <h3 className="font-semibold text-slate-900 flex items-center gap-2">
                  <Award className="w-5 h-5 text-amber-500" />
                  Certifications & Clients
                </h3>
                
                {certifications.length > 0 && (
                  <div>
                    <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Certifications</p>
                    <div className="flex flex-wrap gap-2">
                      {certifications.map(cert => (
                        <span key={cert} className="inline-flex items-center gap-1 px-3 py-1 bg-blue-50 text-blue-700 rounded-full text-sm font-medium border border-blue-100">
                          <CheckCircle2 className="w-3 h-3" />
                          {cert}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                
                <div>
                  <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Past Clients</p>
                  {pastClients.length > 0 ? (
                    <div className="flex flex-wrap gap-2">
                      {pastClients.map(client => (
                        <span key={client} className="inline-flex items-center gap-1 px-3 py-1 bg-slate-100 text-slate-700 rounded-full text-sm font-medium">
                          <Users className="w-3 h-3" />
                          {client}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p className="text-sm text-slate-500 italic">No past clients listed</p>
                  )}
                </div>

                {/* Resume Download */}
                {resumeUrl && (
                  <div className="pt-3 border-t border-slate-200">
                    <a
                      href={resumeUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center justify-center gap-2 w-full px-3 py-2 bg-slate-100 text-slate-700 rounded-lg hover:bg-slate-200 transition-colors font-medium text-sm"
                    >
                      <Download className="w-4 h-4" />
                      Download Resume
                    </a>
                  </div>
                )}
              </div>

              {/* Match Breakdown */}
              <div className="space-y-3 p-4 border border-slate-200 rounded-xl bg-gradient-to-br from-white to-blue-50">
                <h3 className="font-semibold text-slate-900 flex items-center gap-2">
                  <Zap className="w-5 h-5 text-blue-600" />
                  Match Breakdown
                </h3>
                
                <div className="space-y-3">
                  {breakdownItems.map(item => {
                    const percentage = Math.min(100, (item.score / item.total) * 100)
                    return (
                      <div key={item.label} className="space-y-1">
                        <div className="flex items-center justify-between text-sm">
                          <span className="text-slate-700 font-semibold">{item.label}</span>
                          <span className="text-slate-900 font-bold bg-white px-2 py-0.5 rounded text-xs">
                            {item.score}/{item.total}
                          </span>
                        </div>
                        <div className="w-full bg-slate-200 rounded-full h-2.5 overflow-hidden">
                          <div
                            className={clsx(
                              'h-2.5 rounded-full transition-all duration-500',
                              item.color === 'blue' 
                                ? percentage >= 80 ? 'bg-green-500' : percentage >= 50 ? 'bg-blue-500' : 'bg-yellow-500'
                                : 'bg-slate-400'
                            )}
                            style={{ width: `${percentage}%` }}
                          />
                        </div>
                        <div className="text-xs text-slate-500 text-right">{percentage.toFixed(0)}% match</div>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="sticky bottom-0 border-t border-slate-200 bg-white px-6 py-4 flex justify-end gap-3">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-slate-100 text-slate-700 rounded-lg font-medium hover:bg-slate-200 transition-colors"
          >
            Close
          </button>
          {trainer.linkedin && trainer.linkedin !== '-' && (
            <a
              href={trainer.linkedin}
              target="_blank"
              rel="noopener noreferrer"
              className="px-4 py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 transition-colors flex items-center gap-2"
            >
              <Linkedin className="w-4 h-4" />
              View LinkedIn
            </a>
          )}
        </div>
      </div>
    </div>
  )
}
