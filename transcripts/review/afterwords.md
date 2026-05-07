# Review: afterwords

**Kind:** blog  
**Repo:** (none)  
**URL:** (none)  

---

### A) BLOG POST REVISIONS

CHANGE: [Replace the description: '17 cloned voices' in the frontmatter]
TO: 'over 100 cloned voices'
REASON: The project now supports 110+ voices as stated in the updated repository README.

CHANGE: [Replace the section '17 Voices, Zero Extra Memory' with '110+ Voices, Zero Extra Memory']
TO: 'The voice library ships with over 110 cloned voices, all extracted from public audio using the clone-voice.sh pipeline.'
REASON: Accurate count update.

CHANGE: [Replace "Afterwords is not a voice assistant..."]
TO: 'Afterwords is not a voice assistant. It doesn't listen for wake words, doesn't maintain conversation state — it is a local bridge between Claude Code's text output and your speakers. It hooks into Claude Code, ensuring your code base stays entirely local. Traditionally, high-quality voice synthesis required cloud-based infrastructure and an internet connection, which introduced latency and privacy concerns. This dynamic changes with Apple Silicon. Afterwords leverages this by running the Qwen3-TTS engine on Apple's MLX framework, utilizing the unified memory architecture of the M1 chip, at the exact moment Claude Code finishes a thought.'
REASON: Incorporates corrections from the QA notes to replace inaccurate statements and hallucinations.

---

### B) SYNTHESIS SCRIPT

Claude Code already transcribes your spoken words. But until now, it always responded as silent characters on a dark terminal. You speak to it, and it types back. Afterwords was built to close this loop. It intercepts every Claude Code response, sends the text to a local text-to-speech server, and plays it through your speakers, creating a real two-way voice conversation that runs entirely on your machine.

Traditionally, high-quality voice synthesis required cloud-based infrastructure and an internet connection, which introduced latency and privacy concerns. This dynamic changes with Apple Silicon. Afterwords leverages this by running the Qwen-3-TTS engine on Apple's MLX framework, utilizing the unified memory architecture of the M1 chip, at the exact moment Claude Code finishes a thought.

You get over one hundred cloned voices, ranging from famous actors and characters to science communicators, all extracted from fifteen-second clips. Because it uses zero-shot cloning, adding a new voice just takes a small reference file, costing zero additional memory regardless of how many voices you have.

The architecture is simple. A stop hook in Claude Code intercepts the assistant’s output, strips the formatting, and queues the text. A background worker then processes the queue, converts it to audio, and plays it locally. Everything remains on your machine, ensuring your proprietary code stays private.

You can customize the experience by dropping a configuration file in any repository to choose a specific voice for that project, making the coding assistant feel like part of the team's personality. If you want to get started, just clone the repository and run the setup script. It takes care of hardware checks, model weights, and wiring everything together. Hear your code reviews in a new way by visiting the project link on the site.
