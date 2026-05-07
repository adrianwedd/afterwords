# Review: emdr-agent

**Kind:** project  
**Repo:** https://github.com/adrianwedd/emdr-agent  
**URL:** (none)  

---

### A) BLOG POST REVISIONS

CHANGE: [the tags: `tags: ['ai', 'ai-safety', 'health', 'typescript']`]
TO: [the tags: `tags: ['ai', 'ai-safety', 'health']`]
REASON: The repo is primarily focused on the architecture of an agentic system; explicitly listing 'typescript' as a tag is redundant given the tech stack is an implementation detail mentioned in the post.

CHANGE: [repo: `repo: 'https://github.com/adrianwedd/emdr-agent'`]
TO: [repo: `repo: 'https://github.com/adrianwedd/emdr-agent'` (Note: Verify the actual repository existence if necessary, though as an editor I am basing this on your provided text.)]
REASON: POST OK (The repo link is provided in the header, which is correct).

CHANGE: [In the "Safety First" section: "Crisis intervention protocols exist as hard stops—not suggestions the model might ignore, but deterministic gates that lock the AI out entirely and hand control to pre-written safety scripts and human referral pathways."]
TO: [Crisis intervention protocols exist as hard stops; these are deterministic gates that prioritize human safety and professional referral pathways over generative output, ensuring the AI cannot override critical intervention steps.]
REASON: Improves clarity regarding the deterministic nature of the safety gates and avoids the potentially misleading "lock the AI out" phrasing, aligning better with the source README's emphasis on safety integration.

---

### B) SYNTHESIS SCRIPT

You are looking at an experimental project built to explore a fundamental question: what safety architecture must an AI-assisted trauma therapy system possess before it can be ethically or practically useful? EMDR, or Eye Movement Desensitization and Reprocessing, is one of the most effective, evidence-based trauma therapies, but it is also highly precise. If the timing of bilateral stimulation is wrong, or if a system pushes too quickly through a traumatic memory, the potential for harm is significant. This project addresses that challenge by prioritizing safety architecture as the foundation, rather than as an afterthought.

The system is built on a modular, agentic framework that treats safety as a primary constraint. Three layers of distress monitoring run continuously throughout every session. When physiological arousal crosses defined thresholds, the system triggers automatic grounding techniques. These are not merely suggestions that the model might interpret or ignore; they are deterministic gates. When safety thresholds are met, these gates can override the AI's flow, handing control to pre-written safety scripts and established human referral pathways.

The adaptive protocol engine within the application dynamically adjusts the phases of EMDR—moving between desensitization, installation, and the body scan—based on that real-time distress monitoring. To support the therapeutic process, the system coordinates multi-modal bilateral stimulation, which includes visual tracking, auditory tones, and tactile pulses. Every session generates a legible record, providing transparency for both the user and any supervising clinician.

It is important to emphasize that this is a research-based prototype. It is not, and cannot be, a replacement for a human therapist. However, in scenarios where the alternative is a complete lack of access to care, exploring what responsible, safety-first therapeutic tooling looks like is a necessary endeavor. By building in hard, deterministic safety limits, this project seeks to define the baseline requirements for responsible AI in sensitive health contexts.

To see the technical documentation and explore the safety architecture, head over to the project repository at github.com/adrianwedd/emdr-agent.
