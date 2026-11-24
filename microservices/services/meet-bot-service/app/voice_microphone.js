(() => {
  if (!navigator.mediaDevices || window.clahanMicrophone) return;
  const devices = navigator.mediaDevices;
  const original = devices.getUserMedia.bind(devices);
  const enumerate = devices.enumerateDevices.bind(devices);
  let context, destination;
  const tracks = new Set();
  let playing = false;
  function ensureAudio() {
    if (!context) {
      context = new AudioContext({sampleRate: 48000});
      destination = context.createMediaStreamDestination();
    }
  }
  // The stream stays silent except while this tab's welcome is playing.
  // Nothing is connected to the speaker output or another meeting tab.
  devices.getUserMedia = async constraints => {
    if (!constraints || !constraints.audio) return original(constraints);
    const stream = constraints.video
      ? await original({...constraints, audio: false}) : new MediaStream();
    ensureAudio();
    await context.resume();
    const track = destination.stream.getAudioTracks()[0].clone();
    tracks.add(track);
    stream.addTrack(track);
    return stream;
  };
  devices.enumerateDevices = async () => {
    const found = (await enumerate()).filter(device => device.kind !== 'audioinput');
    found.push({deviceId: 'default', groupId: 'clahan-voice', kind: 'audioinput',
      label: 'Clahan meeting assistant', toJSON() {return {...this};}});
    return found;
  };
  window.clahanMicrophone = {
    async speak(wav) {
      if (playing || ![...tracks].some(track => track.readyState === 'live' && track.enabled)) return false;
      playing = true;
      let source;
      try {
        ensureAudio();
        await context.resume();
        const bytes = Uint8Array.from(atob(wav), c => c.charCodeAt(0));
        const buffer = await context.decodeAudioData(bytes.buffer);
        source = context.createBufferSource();
        source.buffer = buffer;
        source.connect(destination);
        await new Promise((resolve, reject) => {
          const timer = setTimeout(() => reject(new Error('Voice playback timed out')), 80000);
          source.onended = () => {clearTimeout(timer); resolve();};
          source.start();
        });
        return [...tracks].some(track => track.readyState === 'live' && track.enabled);
      } finally {
        if (source) {try {source.stop();} catch (_) {} source.disconnect();}
        playing = false;
      }
    }
  };
})();
