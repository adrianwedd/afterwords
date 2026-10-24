'use strict';
const data = JSON.parse(document.getElementById('manifest').textContent);
const status = document.getElementById('status');
const players = [], reviews = new Map(), byId = new Map();
let queue = [], muted = false, generation = 0;
function node(tag, text) {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  return n;
}
function button(text, action) {
  const b = node('button', text); b.addEventListener('click', action); return b;
}
function stop() { generation++; queue = []; players.forEach(a => a.pause()); }
async function start(audio, label, offset = 0, ordered = false) {
  if (!ordered) stop();
  const token = generation;
  players.forEach(a => { if (a !== audio) a.pause(); });
  audio.currentTime = offset;
  try { await audio.play(); if (token === generation) status.textContent = `Playing: ${label}`; }
  catch { if (token === generation) { stop(); status.textContent = 'Playback unavailable; transcript remains below.'; } }
}
function sequence(ids) {
  stop(); queue = ids.map(id => byId.get(id));
  if (queue.length) start(queue[0].audio, queue[0].clip.label, 0, true);
}
const titles = ['Same words · Qwen A / Drama B', 'Same words · three emotions', 'Vixen’s signature voice', 'Four LulzBench model characters', 'Long conversational performance', 'Full cast · retained reference gallery'];
const cues = {'hugo-public': [[25.38, 'shape / shaped'], [50.84, 'possible added “is”'], [131.26, 'possible added “conversation”']],
  'jasper-public': [[0, 'opening “re”'], [23.28, 'maternal / internal'], [52.06, 'possible added “plant”'], [110.40, 'knead / need (homophones)']]};
for (let part = 1; part <= 6; part++) {
  const section = node('section'); section.id = `part-${part}`;
  section.append(node('h2', titles[part - 1]));
  if (part === 1) section.append(button('Play A → B', () => sequence(['qwen-existing-reference-dry-humour', 'drama-dry-humour'])));
  if (part === 2) section.append(button('Compare all three emotions', () => sequence(['drama-emotion-excited', 'drama-emotion-sad', 'drama-emotion-angry'])));
  if (part === 5) section.append(button('Play complete request → answer', () => sequence(['exchange-prompt', 'exchange-answer'])));
  for (const clip of data.clips.filter(c => c.part === part)) {
    const card = node('article'); card.append(node('h3', clip.label), node('p', clip.judge));
    const meta = node('p', `${clip.duration_seconds.toFixed(2)} seconds · ${clip.sample_rate} Hz · ${clip.id}`); meta.className = 'meta'; card.append(meta);
    card.append(node('p', `${clip.backend} · ${clip.acoustic_acceptance}. ${clip.permission}`));
    const audio = node('audio'); audio.controls = true; audio.preload = 'none'; audio.src = clip.audio;
    audio.setAttribute('aria-label', clip.label); players.push(audio); byId.set(clip.id, {audio, clip});
    audio.addEventListener('play', () => {
      if (queue.length && queue[0].audio !== audio) { queue = []; generation++; }
      players.forEach(a => { if (a !== audio) a.pause(); });
      status.textContent = `Playing: ${clip.label}`;
    });
    audio.addEventListener('ended', () => {
      if (queue[0]?.audio === audio) {
        queue.shift();
        if (queue.length) start(queue[0].audio, queue[0].clip.label, 0, true);
        else status.textContent = 'Sequence finished. Listening verdict remains yours.';
      }
    });
    card.append(audio, button('Play / replay', () => start(audio, clip.label)));
    for (const [time, label] of cues[clip.id] || []) card.append(button(`${time.toFixed(1)}s · ${label}`, () => start(audio, clip.label, time)));
    const details = node('details'); details.append(node('summary', 'Exact transcript and recording bindings'));
    const text = node('p', clip.text); text.className = 'transcript'; details.append(text);
    const binding = node('pre', JSON.stringify({audio_sha256: clip.audio_sha256, text_sha256: clip.text_sha256, collection: clip.bindings, voice_key: clip.voice_key}, null, 2));
    details.append(binding); card.append(details);
    // Identical audio/text share notes, including the repeated long-answer card.
    const key = `${clip.audio_sha256}/${clip.text_sha256}`;
    if (!reviews.has(key)) {
      const verdict = node('select'), coverage = node('select'), notes = node('input');
      for (const value of ['pending', 'pass', 'fail', 'unsure']) verdict.append(node('option', value));
      for (const value of ['not listened', 'partial', 'complete']) coverage.append(node('option', value));
      for (const [label, control] of [['Verdict', verdict], ['Coverage', coverage], ['Specific observation / timestamp', notes]]) {
        const wrapper = node('label', `${clip.label} · ${label}`); wrapper.append(control); card.append(wrapper);
        control.addEventListener('input', summary);
      }
      reviews.set(key, {clip, verdict, coverage, notes});
    } else card.append(node('p', 'Same exact recording and text as above: verdict and coverage are shared with that card.'));
    section.append(card);
  }
  document.getElementById('parts').append(section);
}
function summary() {
  const lines = ['Expressive voice listening verdict', `Reviewer: ${document.getElementById('reviewer').value || 'unspecified'}`,
    `Inventory: ${data.inventory_sha256}`, `Candidate: ${data.candidate_manifest_sha256}`];
  for (const r of reviews.values()) {
    if (r.verdict.value === 'pending' && r.coverage.value === 'not listened' && !r.notes.value) continue;
    lines.push(`${r.clip.label}: ${r.verdict.value}; ${r.coverage.value}; ${r.notes.value || 'no observation recorded'}`,
      `  audio=${r.clip.audio_sha256}; text=${r.clip.text_sha256}`);
    if (r.verdict.value === 'pass' && r.coverage.value !== 'complete') lines.push('  PARTIAL COVERAGE: not a complete-recording acceptance.');
  }
  lines.push(`Overall: ${document.getElementById('overall').value || 'pending'}`, 'Unmentioned recordings remain pending. No release receipt or deployment approval created.');
  document.getElementById('result').value = lines.join('\n');
}
document.getElementById('pause').addEventListener('click', () => { stop(); status.textContent = 'Paused; sequence cancelled.'; });
document.getElementById('mute').addEventListener('click', e => {
  muted = !muted; players.forEach(a => { a.muted = muted; });
  e.target.textContent = muted ? 'Unmute all' : 'Mute all'; e.target.setAttribute('aria-pressed', String(muted));
});
document.getElementById('word-flags').textContent = data.word_flags;
document.getElementById('summary').addEventListener('click', summary);
for (const id of ['reviewer', 'overall']) document.getElementById(id).addEventListener('input', summary);
document.getElementById('copy').addEventListener('click', async () => {
  summary(); const result = document.getElementById('result');
  try { await navigator.clipboard.writeText(result.value); status.textContent = 'Verdict copied. Paste it into your reply.'; }
  catch { result.focus(); result.select(); status.textContent = 'Summary selected. Use Copy to copy your verdict.'; }
});
window.addEventListener('pagehide', stop);
summary();
