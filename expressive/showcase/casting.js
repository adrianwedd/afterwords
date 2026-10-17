'use strict';
const data = JSON.parse(document.getElementById('manifest').textContent);
const status = document.getElementById('status');
const players = [];
let queue = [];
function node(tag, text) {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  return n;
}
function stop() { queue = []; players.forEach(a => a.pause()); }
async function play(audio, label) {
  players.forEach(a => { if (a !== audio) a.pause(); });
  try { await audio.play(); status.textContent = label; }
  catch { stop(); status.textContent = 'Playback unavailable. The transcript is still below.'; }
}
for (const pair of [data.vixen, ...data.performances]) {
  const section = node('section'); section.append(node('h2', pair.title), node('p', pair.reason));
  section.append(node('p', pair.status));
  section.append(node('p', `Text model: ${pair.model || 'Vixen’s configured Hermes model'}${pair.specimen_id ? ' · ' + pair.specimen_id : ''}`));
  if (pair.reference_audio) {
    const details = node('details'); details.append(node('summary', 'Hear the source reference'));
    const source = node('audio'); source.controls = true; source.preload = 'none'; source.src = pair.reference_audio;
    source.setAttribute('aria-label', `Source reference: ${pair.reference_name}`);
    source.addEventListener('play', () => { queue = []; players.forEach(a => { if (a !== source) a.pause(); }); });
    players.push(source); details.append(source, node('p', pair.reference_text)); section.append(details);
  }
  const group = [];
  for (const key of ['baseline', 'candidate']) {
    const clip = pair[key], card = node('article'), audio = node('audio');
    card.append(node('h3', clip.label), node('p', `${clip.duration_seconds.toFixed(2)} seconds · ${clip.reference_label}`));
    audio.controls = true; audio.preload = 'none'; audio.src = clip.audio;
    audio.setAttribute('aria-label', clip.label); players.push(audio);
    const item = {audio, label: clip.label}; group.push(item);
    audio.addEventListener('play', () => {
      if (queue.length && queue[0].audio !== audio) queue = [];
      players.forEach(a => { if (a !== audio) a.pause(); });
      status.textContent = clip.label;
    });
    audio.addEventListener('ended', () => {
      if (queue[0]?.audio === audio) {
        queue.shift();
        if (queue.length) { queue[0].audio.currentTime = 0; play(queue[0].audio, queue[0].label); }
        else status.textContent = 'Comparison finished.';
      }
    });
    audio.addEventListener('error', () => { stop(); status.textContent = 'Playback unavailable. The transcript is still below.'; });
    const replay = node('button', `Play / replay ${key === 'baseline' ? 'A' : 'B'}`);
    replay.addEventListener('click', () => { stop(); audio.currentTime = 0; play(audio, clip.label); });
    card.append(audio, replay); section.append(card);
  }
  const compare = node('button', 'Play A → B');
  compare.addEventListener('click', () => { stop(); queue = [...group]; queue[0].audio.currentTime = 0; play(queue[0].audio, queue[0].label); });
  section.append(compare);
  const transcript = node('details');
  transcript.append(node('summary', pair.excerpt ? 'Exact performed excerpt' : 'Exact Vixen reply'));
  const text = node('p', pair.text); text.className = 'transcript'; transcript.append(text); section.append(transcript);
  if (pair.full_text) {
    const source = node('details'); source.append(node('summary', `${pair.model} · ${pair.specimen_id} · complete source exchange`));
    source.append(node('h3', 'Prompt'), node('p', pair.prompt), node('h3', 'Original complete response'));
    const full = node('p', pair.full_text); full.className = 'transcript'; source.append(full); section.append(source);
  }
  document.getElementById('pairs').append(section);
}
document.getElementById('pause').addEventListener('click', () => { stop(); status.textContent = 'Paused.'; });
document.getElementById('mute').addEventListener('click', e => {
  const muted = e.target.getAttribute('aria-pressed') !== 'true';
  e.target.setAttribute('aria-pressed', String(muted)); e.target.textContent = muted ? 'Unmute all' : 'Mute all';
  players.forEach(a => { a.muted = muted; });
});
window.addEventListener('pagehide', stop);
