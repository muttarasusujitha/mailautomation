export function createInterviewAlarm(AudioContextClass) {
  let context
  let busyUntil = 0
  let volume = 0.5
  const voices = new Set()
  const stop = () => {
    for (const { oscillator, gain } of voices) {
      try { oscillator.stop() } catch { /* Already finished. */ }
      oscillator.disconnect()
      gain.disconnect()
    }
    voices.clear()
    busyUntil = 0
  }
  return {
    stop,
    setVolume(value) {
      if (Number.isFinite(value)) volume = Math.max(0, Math.min(1, value))
    },
    async enable() {
      if (!AudioContextClass) throw new Error('This browser does not support alarm audio.')
      if (!context || context.state === 'closed') context = new AudioContextClass()
      if (context.state !== 'running') await context.resume()
      if (context.state !== 'running') throw new Error('Audio is blocked. Click Enable & test alarm again.')
    },
    play() {
      if (!context || context.state !== 'running') return false
      if (context.currentTime < busyUntil) return true
      const start = context.currentTime
      // Original ascending chime melody, repeated for 30 seconds.
      // Synthesized locally: no music downloads, microphone, or external service.
      const melody = [523.25, 659.25, 783.99, 1046.5, 783.99, 659.25, 587.33, 783.99]
      for (let i = 0; i < 60; i += 1) {
        const oscillator = context.createOscillator()
        const gain = context.createGain()
        const voice = { oscillator, gain }
        voices.add(voice)
        const at = start + i * 0.5
        oscillator.type = 'sine'
        oscillator.frequency.value = melody[i % melody.length]
        gain.gain.setValueAtTime(0, at)
        gain.gain.linearRampToValueAtTime(volume * 0.25, at + 0.02)
        gain.gain.exponentialRampToValueAtTime(0.001, at + 0.4)
        gain.gain.linearRampToValueAtTime(0, at + 0.45)
        oscillator.connect(gain)
        gain.connect(context.destination)
        oscillator.onended = () => { oscillator.disconnect(); gain.disconnect(); voices.delete(voice) }
        oscillator.start(at)
        oscillator.stop(at + 0.45)
      }
      busyUntil = start + 30
      return true
    },
    close() {
      stop()
      if (context && context.state !== 'closed') context.close().catch(() => {})
      context = undefined
      busyUntil = 0
    },
  }
}
