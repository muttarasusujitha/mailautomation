import { Link } from 'react-router-dom'
import { ArrowRight, Building2, GraduationCap } from 'lucide-react'
import BrandMark from '../components/BrandMark'

const choices = [
  { label: 'Client', description: 'Find trainers and manage your training requests.', path: '/client-login', icon: Building2 },
  { label: 'Trainer', description: 'Build your profile and explore opportunities.', path: '/trainer-login', icon: GraduationCap },
]

export default function LoginChoice() {
  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-gradient-to-br from-blue-950 via-blue-800 to-cyan-700 px-5 py-12">
      <div aria-hidden="true" className="absolute -right-32 -top-32 h-96 w-96 rounded-full bg-white/5" />
      <div aria-hidden="true" className="absolute -bottom-40 -left-24 h-[30rem] w-[30rem] rounded-full bg-cyan-300/10" />
      <section className="relative w-full max-w-3xl rounded-3xl border border-white/20 bg-white p-7 shadow-2xl sm:p-10">
        <BrandMark size="lg" />
        <p className="mt-10 text-xs font-bold uppercase tracking-[.2em] text-blue-700">Welcome to TrainerSync</p>
        <h1 className="mt-2 text-3xl font-extrabold tracking-tight text-slate-950 sm:text-4xl">Choose your workspace</h1>
        <p className="mt-3 max-w-xl text-sm leading-6 text-slate-600">Select the account type you use. We’ll take you to the matching sign in page.</p>
        <div className="mt-8 grid gap-4 sm:grid-cols-2">
          {choices.map(({ label, description, path, icon: Icon }) => (
            <Link key={label} to={path} className="group flex min-h-40 items-center gap-4 rounded-2xl border-2 border-slate-200 p-5 transition hover:-translate-y-1 hover:border-blue-500 hover:bg-blue-50/50 hover:shadow-lg focus-visible:outline-blue-600">
              <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-blue-700 text-white shadow-md shadow-blue-900/20"><Icon size={27} aria-hidden="true" /></span>
              <span className="min-w-0 flex-1"><span className="block text-xl font-bold text-slate-900">{label}</span><span className="mt-1 block text-sm leading-5 text-slate-600">{description}</span></span>
              <ArrowRight className="shrink-0 text-blue-700 transition group-hover:translate-x-1" size={20} aria-hidden="true" />
            </Link>
          ))}
        </div>
        <div className="mt-7 flex items-center justify-between border-t border-slate-100 pt-5 text-sm">
          <Link to="/home" className="font-semibold text-slate-600 hover:text-blue-700">Back to home</Link>
          <Link to="/admin-login" className="font-semibold text-blue-700 hover:text-blue-800">Team sign in</Link>
        </div>
      </section>
    </main>
  )
}
