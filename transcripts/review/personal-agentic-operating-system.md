# Review: personal-agentic-operating-system

**Kind:** project  
**Repo:** https://github.com/adrianwedd/personal-agentic-operating-system  
**URL:** (none)  

---

### A) BLOG POST REVISIONS

CHANGE: `PAOS`
TO: `The Personal Agentic Operating System (PAOS)`
REASON: Introduce the full name for clarity, aligning with repo naming conventions.

CHANGE: `Ollamma for local inference`
TO: `Ollama for local inference`
REASON: Typo in original content (double 'm').

CHANGE: `no external API calls required unless you choose them`
TO: `no external API calls are required unless explicitly configured`
REASON: More precise phrasing given the configuration-based nature of the backends.

CHANGE: `The Mermaid graph re-renders on each build`
TO: `The Mermaid architecture diagram is maintained alongside the code`
REASON: Clarification. The README mentions a live diagram in `docs/architecture/langgraph_flow.md` rather than a dynamic build-time render of the graph structure itself.

CHANGE: `Neither graph traversal nor embedding similarity alone captures how humans organise knowledge. Together they get closer.`
TO: `Neither graph traversal nor embedding similarity alone captures how humans organize knowledge; together, they complement each other to get closer to human-like retrieval.`
REASON: Improves flow and aligns with the corrected QA synthesis notes.

---

### B) SYNTHESIS SCRIPT

Most agentic systems are built for the cloud, but I designed PAOS, the Personal Agentic Operating System, to run entirely on your own machine. It is a local-first platform for LLM agents where everything operates inside Docker on your hardware. You do not need external API calls unless you explicitly choose to configure them.

The system is highly flexible with its backend. You can use Ollama for local inference or plug in services like OpenAI, Gemini, or DeepSeek whenever you need extra power. The core of the system is a LangGraph workflow that manages the entire lifecycle of a task, including planning, prioritization, retrieval, execution, and human-in-the-loop checkpoints.

For knowledge retrieval, PAOS uses a hybrid approach. It combines Neo4j entity lookups with Qdrant vector search filtered by metadata. Neither method on its own perfectly captures how humans organize information, but by combining them, the system gets much closer to that goal. Because autonomy without oversight can be risky, every consequential action requires a human-in-the-loop checkpoint, ensuring the system remains debuggable.

What I find most interesting is the self-improvement loop. A meta-agent runs on a daily schedule, reading your reflection logs and updating system guidelines that are injected at runtime. This isn't about reaching some abstract AGI milestone, but about traceable adaptation—you can see exactly what changed, why it changed, and what it affected. Every trace flows through Langfuse, and every node and tool call remains fully observable.

I built this because I wanted an agentic system I could actually reason about. I didn't want a black box. I wanted a system with legible state, explicit checkpoints, and a memory architecture I could inspect and trust. If you are looking for an agentic framework that puts you in control, you can find the project repository at github.com/adrianwedd/personal-agentic-operating-system.
