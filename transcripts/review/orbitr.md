# Review: orbitr

**Kind:** project  
**Repo:** https://github.com/adrianwedd/orbitr  
**URL:** (none)  

---

### A) BLOG POST REVISIONS

CHANGE: `heroImage: '/notebook-assets/orbitr/infographic.webp'`
TO: Remove this line.
REASON: The provided content slug and context do not specify an image file, and relying on it may be incorrect based on the repo structure provided.

CHANGE: `Traditional sequencers are grids. Rows and columns. Time moves left to right. It works, but it enforces a particular relationship with rhythm—one that privileges linearity and makes polyrhythm feel like a special case rather than the natural state of things.`
TO: `Traditional sequencers are linear grids. Time moves from left to right, which privileges linear patterns and makes polyrhythm feel like a special case. orbitr reimagines the sequencer as four concentric rings—inspired by Playtronica's Orbita—where rhythm becomes spatial geometry and polymetric relationships are immediately visible.`
REASON: Consolidation for better flow and clarity, aligning with the "what it solves" requirement.

CHANGE: `This is an experiment. It works well enough to be interesting and unevenly enough to be honest about that.`
TO: `This is an experimental project that combines a polyphonic circular step sequencer with AI-powered sample generation. You can run it locally with the Python backend or as a static site on GitHub Pages.`
REASON: Adds missing functional context (local vs. static) from the README.

---

### B) SYNTHESIS SCRIPT

Traditional music sequencers are built on rigid grids where time moves in a straight line. That works for basic beats, but it makes complex polyrhythms feel like a struggle. orbitr changes that by reimagining the sequencer as a set of concentric rings. Inspired by Playtronica's Orbita, this project uses four tracks that rotate around a shared center, with each track running its own sixteen-step pattern at its own tempo. Suddenly, rhythm isn't just something you hear in a sequence; it is something you see as geometry.

But orbitr goes further by adding a real-time AI layer. By integrating Meta's MusicGen, you can generate custom samples just by typing a text prompt. Whether you need a specific type of kick drum or a unique synth texture, you just describe the sound, and the sequencer generates and drops it into a ring instantly. It comes pre-configured with genre packs for styles like Detroit techno, Berlin nineties, and UK garage, but the engine is designed for you to build your own sonic palette from scratch.

Technically, orbitr is built with Next.js and TypeScript, using the Web Audio API for polyphonic playback. You can run the full version locally with a Python backend to handle the AI generation, or use the static version on GitHub Pages, which features smart caching and sample packs to get you started immediately. 

If you want to move beyond the linear grid and start experimenting with spatial polyrhythms and AI-driven sound design, check out the source code and documentation at the link below.
