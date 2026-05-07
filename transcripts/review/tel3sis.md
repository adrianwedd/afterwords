# Review: tel3sis

**Kind:** project  
**Repo:** https://github.com/adrianwedd/TEL3SIS  
**URL:** (none)  

---

### A) BLOG POST REVISIONS

CHANGE: "The entire architecture—speech-to-text, LLM reasoning, text-to-speech—is optimised to complete the full loop in under three seconds. Not as a benchmark. As a survival threshold."
TO: "The entire architecture—speech-to-text, LLM reasoning, text-to-speech—is optimized to complete the full loop in under three seconds. Not as a benchmark, but as a survival threshold."
REASON: Grammar and style polish.

CHANGE: "Tri-layer memory across Redis, SQLite, and vector storage gives the agent conversational persistence without the hallucination risk of stuffing everything into a single context window."
TO: "Tri-layer memory across Redis, SQLite, and vector storage provides session, mid-term, and long-term context, reducing the hallucination risk associated with stuffing everything into a single context window."
REASON: Clarification based on source README (Session / Mid-term / Long-term structure).

CHANGE: "status: 'active'"
TO: "status: 'in-development'"
REASON: README explicitly lists almost all core features (memory, tools, safety, metrics) as "In Progress".

CHANGE: "The name is an acronym: Telephony-Linked Embedded LLM System for Interactive Support."
TO: "The name is an acronym: Telephony-Linked Embedded LLM System."
REASON: Matches official README header title; "for Interactive Support" appears to be an addition not present in the primary repo identity.

---

### B) SYNTHESIS SCRIPT

The phone call is the oldest real-time interface we have, yet it remains one of the hardest for AI to handle. In a chat interface, latency is invisible, and the system can take its time to think. On a phone call, three seconds of silence is an eternity. It is the exact moment a caller decides the system is broken.

TEL3SIS is a voice-first agentic platform built specifically to solve that problem. It is designed to keep the entire loop—speech-to-text, LLM reasoning, and text-to-speech—running in under three seconds. We treat that latency not just as a benchmark, but as a survival threshold for maintaining natural conversation.

To achieve this while remaining reliable, the architecture focuses on three core challenges. First, it ensures presence by minimizing latency. Second, it tackles the risk of hallucination. Instead of stuffing every piece of information into a single context window, TEL3SIS uses tri-layer memory, managing data across Redis, SQLite, and vector storage to keep track of the conversation at session, mid-term, and long-term levels.

Finally, the system respects safety boundaries. It includes a safety oracle that performs pre-execution filtering on every action, and it is explicitly built to handle context-aware call forwarding to humans when a conversation exceeds what an agent should safely attempt. This isn't an admission of defeat; it is the responsible way to deploy AI on a phone line.

TEL3SIS is currently under active development. You can see the architecture and contribute to the roadmap on the GitHub repository. To learn more or get started, visit the link in the description.
