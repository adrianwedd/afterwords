# Review: rlm-mcp

**Kind:** project  
**Repo:** https://github.com/adrianwedd/rlm-mcp  
**URL:** (none)  

---

### A) BLOG POST REVISIONS

CHANGE: `date: 2025-11-01`
TO: `date: 2026-05-07`
REASON: The date in the metadata is set in the future relative to today's date (May 7, 2026).

CHANGE: `rlm-mcp implements the Recursive Language Model pattern as an MCP server`
TO: `rlm-mcp implements the Recursive Language Model pattern (Zhang et al., 2025) as an MCP server`
REASON: Adds necessary context and attribution to the academic framework the project is based on, as noted in the repo.

CHANGE: `I built this for the workflow where context windows aren't enough: long-form research, multi-chapter manuscripts, regulatory documents that run to hundreds of pages.`
TO: `I built this for the workflow where context windows aren't enough: long-form research, multi-chapter manuscripts, and regulatory documents. It supports batch loading with memory-bounded semaphores and concurrent session safety for team environments.`
REASON: The original text omits the key technical features (concurrency and batch efficiency) that distinguish the current production-ready version (v0.2.x).

CHANGE: `[Read the deep dive →](/blog/beyond-context-windows/)`
TO: `[Read the deep dive →](/blog/beyond-context-windows/) (See the README for the v0.2.x migration guide)`
REASON: Providing a direct pointer to the migration guide adds value for users who might already be using the library.

---

### B) SYNTHESIS SCRIPT

You are looking at a problem everyone who builds with LLMs eventually hits. Even with the largest context windows available, documents themselves have no limits. When your project exceeds what a model can hold in a single pass, you are stuck choosing between chunking strategies that lose coherence or simple summarization that bleeds detail.

I created rlm-mcp to solve this by treating long prompts not as a static feed for the neural network, but as an external environment that the model can symbolically interact with. Based on the recursive language model pattern from recent research, this is an MCP server that brings production-grade document management directly to Claude Code.

Under the hood, this is built for real-world reliability. It uses persistent BM25 search indexes that survive server restarts, allowing for sub-second queries even across massive corpora. If you are working in a team environment, you get concurrent session safety with per-session locks, so multiple users can access the same data without stepping on each other. Loading large batches of documents is also handled through memory-bounded semaphores, making it two to three times faster than standard approaches.

I have included complete artifact provenance tracking, so you can see exactly which document and which section produced every piece of output. It has been tested against a comprehensive suite of over one hundred tests covering everything from concurrency and storage to performance under heavy load. If you need to process hundreds of pages or manage multi-chapter research manuscripts while keeping your model's reasoning sharp, this is for you.

You can find the documentation, installation guide, and the full technical breakdown at the link in the description.
