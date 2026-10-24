'use strict';
const data = JSON.parse(document.getElementById('manifest').textContent);
const titles = ['Same words, two backends', 'One voice, three emotions', 'Vixen through Hermes', 'The LulzBench cast', 'A complete prompt and response'];
const status = document.getElementById('status');
const players = [];
let muted = false;
let sequence = null;
function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}
function pauseAll(except) {
  for (const audio of players) if (audio !== except) audio.pause();
}
async function play(audio, label) {
  pauseAll(audio);
  try { await audio.play(); status.textContent = `Playing: ${label}`; }
  catch { sequence = null; status.textContent = 'Playback unavailable. The text remains available below.'; }
}
document.querySelector('h1').textContent = data.title;
document.getElementById('notice').textContent = data.notice;
for (let part = 1; part <= 5; part++) {
  const section = node('section', undefined, 'part');
  const heading = node('div', undefined, 'part-heading');
  heading.append(node('span', String(part).padStart(2,'0'), 'number'), node('h2', titles[part-1]));
  section.append(heading);
  const clips = data.clips.filter(clip => clip.part === part);
  const required = [2,3,1,4,2][part-1];
  if (clips.length < required) section.append(node('p', `${clips.length} of at least ${required} recordings available — this demonstration is not complete.`, 'pending'));
  const group = node('div', undefined, 'clips');
  const groupPlayers = [];
  for (const clip of clips) {
    const card = node('article', undefined, 'clip');
    card.append(node('h3', clip.label));
    card.append(node('p', `${clip.backend} · ${clip.duration_seconds.toFixed(2)}s · ${clip.sample_rate/1000} kHz`, 'meta'));
    card.append(node('p', `Acoustic review: ${clip.acoustic_acceptance || 'unverified'}. ${clip.permission || ''}`, 'meta'));
    const audio = node('audio');
    audio.controls = true; audio.preload = 'none'; audio.src = clip.audio;
    audio.setAttribute('aria-label', clip.label); audio.dataset.clipId = clip.id;
    players.push(audio); groupPlayers.push({audio, label:clip.label});
    audio.addEventListener('play', () => { if (sequence && sequence[0]?.audio !== audio) sequence = null; pauseAll(audio); status.textContent = `Playing: ${clip.label}`; });
    audio.addEventListener('ended', () => {
      if (sequence && sequence[0]?.audio === audio) {
        sequence.shift();
        if (sequence.length) { sequence[0].audio.currentTime = 0; play(sequence[0].audio,sequence[0].label); }
        else { sequence = null; status.textContent = 'Exchange finished.'; }
      }
    });
    const replay = node('button', 'Play / replay');
    replay.addEventListener('click', () => { sequence = null; audio.currentTime = 0; play(audio,clip.label); });
    const details = node('details'); details.open = true;
    details.append(node('summary','Exact transcript'),node('p',clip.text,'transcript'));
    card.append(audio,replay,details); group.append(card);
  }
  if (part === 5 && groupPlayers.length > 1) {
    const exchange = node('button','Play / replay exchange');
    exchange.addEventListener('click', () => {
      sequence = [...groupPlayers]; sequence[0].audio.currentTime = 0;
      play(sequence[0].audio, sequence[0].label);
    });
    section.append(exchange);
  }
  section.append(group); document.getElementById('parts').append(section);
}
document.getElementById('pause').addEventListener('click', () => { sequence = null; pauseAll(); status.textContent = 'Playback paused.'; });
document.getElementById('mute').addEventListener('click', event => {
  muted = !muted; for (const audio of players) audio.muted = muted;
  event.target.setAttribute('aria-pressed', String(muted)); event.target.textContent = muted ? 'Unmute all' : 'Mute all';
});
window.addEventListener('pagehide', () => { sequence = null; pauseAll(); });
