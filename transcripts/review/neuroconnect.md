# Review: neuroconnect

**Kind:** project  
**Repo:** https://github.com/adrianwedd/neuroconnect  
**URL:** (none)  

---

### A) BLOG POST REVISIONS

CHANGE: "The voice pipeline streams from Twilio through Deepgram to the cognitive loop and back through ElevenLabs."
TO: "The voice pipeline streams from Twilio through Deepgram to the cognitive loop and back through ElevenLabs, with filler phrases masking processing latency to ensure no dead air."
REASON: Missing detail; the README highlights the critical role of filler phrases in the voice pipeline, which is only mentioned later in the post as a general feature.

CHANGE: "Conversations are mined for NDIS functional capacity indicators—with consent—and mapped to support domains for plan reviews. Without consent, nothing is stored. 254 of 257 tests pass. The three that do not require a local PostgreSQL instance."
TO: "Conversations are mined for NDIS functional capacity indicators—with consent—and mapped to support domains for plan reviews. Without consent, nothing is stored."
REASON: Correctness/Context; the mention of test pass rates and PostgreSQL requirements is irrelevant technical "noise" for a general blog post and distracts from the project's purpose.

---

### B) SYNTHESIS SCRIPT

You are looking at a 24/7 voice and text helpline engineered specifically for Australians with ADHD. People with neurodivergent communication patterns often face unique barriers when calling support lines. Traditional systems, with their rigid menus and long delays, can be overwhelming. NeuroConnect solves this by functioning as a safety-first cognitive support system that thinks the way its callers do.

The problem is clear. When someone is in distress, they might trail off mid-sentence while searching for a word. A standard system might interpret that silence as the end of the turn and cut them off. NeuroConnect uses adaptive silence detection, waiting up to two seconds to respect those natural pauses. If the system needs a moment to process, it plays a warm filler phrase instead of leaving you in dead air. Every response is kept under 40 words to respect finite working memory, and because delay aversion is a real neurological experience, the system targets a total mouth-to-ear latency of under 800 milliseconds.

Safety is handled deterministically. There is no machine learning or probability assessment when it comes to danger. The system uses regex patterns, calibrated against common ADHD speech markers like hyperbole and intense burnout language, to run checks in under 10 milliseconds. If you are in immediate danger, the AI is locked out entirely, and a pre-written emergency script takes over to read lifeline numbers and notify human responders.

Beyond crisis support, the system provides practical assistance for executive function and can map conversations to NDIS functional capacity indicators for your plan reviews, but only ever with your explicit consent. It is built on a robust streaming pipeline using Twilio, Deepgram, and ElevenLabs, ensuring that even if an internal component fails, you still hear a supportive voice.

This isn't just another chatbot. It is a research-backed tool designed to scaffold your day without pathologizing your experience. You can find the full technical architecture and project details at the link provided below.
