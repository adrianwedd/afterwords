# Review: safety-first-therapeutic-ai

**Kind:** blog  
**Repo:** (none)  
**URL:** (none)  

---

### A) BLOG POST REVISIONS

CHANGE: "The logic is in 741 lines of `SafetyProtocolService` — explicit, auditable, and not mediated by a language model."
TO: "The logic is hardcoded and auditable, ensuring safety protocols are not mediated by a language model."
REASON: The post includes a specific line count ("741 lines") which is highly likely to become outdated as the project evolves; removing it makes the statement more durable and accurate without needing frequent updates.

CHANGE: "The therapeutic agent implements the eight phases of standard EMDR protocol: preparation, assessment, desensitization, installation, body scan, closure, reevaluation, and resource installation."
TO: "The therapeutic agent is designed to follow the standard eight-phase EMDR protocol, covering preparation, assessment, desensitization, installation, body scan, closure, reevaluation, and resource installation."
REASON: Clarity. The original sentence was cut off, and using "is designed to follow" accurately reflects that this is a research project and not a clinical tool.

---

### B) SYNTHESIS SCRIPT

Eye Movement Desensitization and Reprocessing, or EMDR, is one of the most effective, evidence-based tools we have for trauma therapy. But it is also incredibly precise. If you push through a traumatic memory too quickly, or miss signs of dissociation, you risk doing actual harm. I built the EMDR Agent project to answer a fundamental question: what does safe, AI-assisted trauma therapy look like before it even begins to offer treatment?

The conclusion is that safety cannot be a feature you patch in after the rest of the system is finished. It has to be the literal foundation. Most AI applications treat safety as a set of guardrails—filters or content policies meant to catch bad output. For a coding assistant or a travel bot, that might be enough. But therapeutic AI is different. Here, the therapeutic process itself—activating traumatic material—is inherently risky. The system has to distinguish between productive, therapeutic distress and a dangerous crisis in real time, every few minutes, during a session.

To do this, I built a safety architecture that runs independently of the therapeutic agent. It does not rely on the language model to tell it if the user is okay. Instead, it measures it directly. Layer one monitors distress levels using the standard clinical scale for subjective units of distress. If scores hit critical thresholds or spike too quickly, the system triggers a deterministic emergency stop. It does not ask for permission. It stops the session and immediately switches to proven grounding techniques.

Layer two tracks session-level data, like duration and user history. This ensures that the system is not just reacting to a single moment, but maintaining a safe environment across the entire duration of the treatment.

Layer three provides the actual intervention. When the system stops a session, it does not improvise or try to talk the user through it using generative text. It deploys hardcoded, clinically validated grounding exercises and provides immediate access to professional crisis resources. The AI does not decide how to help someone who is dissociating; it executes the established protocol.

This project is not a clinical tool and it is not a replacement for professional therapy. It is a research and education initiative designed to demonstrate that if we are going to explore AI in healthcare, we must prioritize safety-first architecture above all else. You can see how this works and explore the full project at my website, adrianwedd.com.
