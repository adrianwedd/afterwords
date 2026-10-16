// Non-browser event simulation. Does not establish decoding, layout or mobile acceptance.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const output = process.argv[2];
if (!output) throw new Error('usage: node tests/check_acceptance_controls.cjs OUTPUT_DIRECTORY');
const data = JSON.parse(fs.readFileSync(path.join(output, 'manifest.json'), 'utf8'));
const elements = [], ids = new Map(), windowEvents = {};
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.events = {}; this.textContent = ''; this.value = ''; this.paused = true; elements.push(this); }
  append(...children) {
    this.children.push(...children);
    if (this.tag === 'select' && !this.value) this.value = children[0].textContent;
  }
  setAttribute(name, value) { this[name] = value; }
  addEventListener(name, fn) { this.events[name] = fn; }
  fire(name) { return this.events[name]?.({target: this}); }
  pause() { this.paused = true; }
  async play() { if (this.rejectPlay) throw new Error('simulated decode rejection'); this.paused = false; this.fire('play'); }
  focus() { this.focused = true; }
  select() { this.selected = true; }
}
for (const id of ['manifest', 'status', 'parts', 'reviewer', 'overall', 'result', 'pause', 'mute', 'summary', 'copy', 'word-flags']) ids.set(id, new Element('div'));
ids.get('manifest').textContent = JSON.stringify(data);
vm.runInNewContext(fs.readFileSync(path.join(output, 'acceptance.js'), 'utf8'), {
  document: {getElementById: id => ids.get(id), createElement: tag => new Element(tag)},
  window: {addEventListener: (name, fn) => { windowEvents[name] = fn; }}, navigator: {},
});
const audios = elements.filter(e => e.tag === 'audio');
const findButton = text => elements.find(e => e.tag === 'button' && e.textContent === text);
const settle = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  assert.equal(audios.length, data.clips.length);
  assert(audios.every(a => a.paused && a.preload === 'none'));
  await findButton('Play A → B').fire('click'); await settle();
  assert.equal(audios[0].paused, false); assert.equal(audios[1].paused, true);
  audios[0].pause(); audios[0].fire('ended'); await settle();
  assert.equal(audios[1].paused, false);
  await ids.get('pause').fire('click'); audios[1].fire('ended');
  assert(audios.every(a => a.paused));
  await findButton('Play complete request → answer').fire('click'); await settle();
  const prompt = data.clips.findIndex(c => c.id === 'exchange-prompt');
  const answer = data.clips.findIndex(c => c.id === 'exchange-answer');
  assert.equal(audios[prompt].paused, false);
  audios[prompt].pause(); audios[prompt].fire('ended'); await settle();
  assert.equal(audios[answer].paused, false);
  await findButton('25.4s · shape / shaped').fire('click'); await settle();
  assert.equal(audios[answer].paused, true);
  assert.equal(audios[data.clips.findIndex(c => c.id === 'hugo-public')].currentTime, 25.38);
  ids.get('mute').fire('click'); assert(audios.every(a => a.muted));
  ids.get('mute').fire('click'); assert(audios.every(a => !a.muted));
  windowEvents.pagehide(); assert(audios.every(a => a.paused));
  const selects = elements.filter(e => e.tag === 'select');
  selects[0].value = 'pass'; selects[1].value = 'partial'; selects[0].fire('input');
  assert(ids.get('result').value.includes('PARTIAL COVERAGE'));
  assert(ids.get('result').value.includes('Unmentioned recordings remain pending'));
  await ids.get('copy').fire('click'); assert(ids.get('result').selected);
  audios[0].rejectPlay = true;
  await findButton('Play A → B').fire('click'); await settle();
  assert(ids.get('status').textContent.includes('Playback unavailable'));
  audios[0].fire('ended'); assert(audios[1].paused);
  console.log('PASS: no autoplay; A/B and exchange order; one active player; pause cancellation; timestamp seek assignment; mute; pagehide; partial-coverage warning; clipboard fallback; playback rejection. Event simulation only.');
})().catch(error => { console.error(error); process.exitCode = 1; });
