export function createInterviewAlarm(AudioContextClass) {
  let context
  let busyUntil = 0
  return {
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
      // Classic alarm clock: four short beeps, then a pause, for ten seconds.
      for (let i = 0; i < 20; i += 1) {
        const oscillator = context.createOscillator()
        const gain = context.createGain()
        const at = start + Math.floor(i / 4) * 2 + (i % 4) * 0.3
        oscillator.type = 'square'
        oscillator.frequency.value = 880
        gain.gain.setValueAtTime(0, at)
        gain.gain.linearRampToValueAtTime(0.15, at + 0.01)
        gain.gain.setValueAtTime(0.15, at + 0.15)
        gain.gain.linearRampToValueAtTime(0, at + 0.2)
        oscillator.connect(gain)
        gain.connect(context.destination)
        oscillator.onended = () => { oscillator.disconnect(); gain.disconnect() }
        oscillator.start(at)
        oscillator.stop(at + 0.2)
      }
      busyUntil = start + 10
      return true
    },
    close() {
      if (context && context.state !== 'closed') context.close().catch(() => {})
      context = undefined
      busyUntil = 0
    },
  }
}
