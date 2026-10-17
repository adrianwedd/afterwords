// Event simulation only: never opens a browser or claims rendered/mobile acceptance.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict'), path = require('node:path');
const out = process.argv[2];
if (!out) throw Error('usage: node tests/check_casting_controls.cjs OUTPUT_DIRECTORY');
const data = JSON.parse(fs.readFileSync(path.join(out, 'manifest.json'), 'utf8'));
const nodes = [], ids = new Map(), events = {};
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.events = {}; this.attributes = {}; this.paused = true; nodes.push(this); }
  append(...children) { this.children.push(...children); }
  setAttribute(k, v) { this.attributes[k] = v; }
  getAttribute(k) { return this.attributes[k]; }
  addEventListener(k, fn) { this.events[k] = fn; }
  fire(k) { return this.events[k]?.({target: this}); }
  pause() { this.paused = true; }
  async play() { if (this.reject) throw Error('fixture media error'); this.paused = false; this.fire('play'); }
}
for (const id of ['manifest', 'status', 'pairs', 'pause', 'mute']) ids.set(id, new Element('div'));
ids.get('manifest').textContent = JSON.stringify(data); ids.get('mute').setAttribute('aria-pressed', 'false');
vm.runInNewContext(fs.readFileSync(path.join(out, 'casting.js'), 'utf8'), {
  document: {getElementById: id => ids.get(id), createElement: tag => new Element(tag)},
  window: {addEventListener: (k, fn) => { events[k] = fn; }},
});
const audio = nodes.filter(n => n.tag === 'audio');
const pairs = nodes.filter(n => n.tag === 'button' && n.textContent === 'Play A → B');
const settle = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  assert.equal(data.performances.length, 4); assert.equal(audio.length, 10); assert.equal(pairs.length, 5);
  assert(!nodes.some(n => ['input', 'select', 'textarea', 'form'].includes(n.tag)));
  assert(audio.every(a => a.paused && a.preload === 'none'));
  for (let i = 0; i < pairs.length; i++) {
    pairs[i].fire('click'); await settle();
    assert.equal(audio.filter(a => !a.paused).length, 1); assert(!audio[i*2].paused);
    audio[i*2].pause(); audio[i*2].fire('ended'); await settle();
    assert(!audio[i*2+1].paused); assert.equal(audio.filter(a => !a.paused).length, 1);
    ids.get('pause').fire('click'); audio[i*2+1].fire('ended'); assert(audio.every(a => a.paused));
  }
  ids.get('mute').fire('click'); assert(audio.every(a => a.muted));
  ids.get('mute').fire('click'); assert(audio.every(a => !a.muted));
  pairs[0].fire('click'); await settle(); events.pagehide(); assert(audio.every(a => a.paused));
  audio[0].reject = true; pairs[0].fire('click'); await settle();
  audio[0].fire('ended'); assert(audio.every(a => a.paused));
  assert(ids.get('status').textContent.includes('Playback unavailable'));
  console.log('PASS: exactly four performance pairs plus Vixen; no forms; no autoplay; A/B order; one player; pause cancels continuation; mute; pagehide; media-error cancellation. Simulation only.');
})().catch(error => { console.error(error); process.exitCode = 1; });
