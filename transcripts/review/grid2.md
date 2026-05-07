# Review: grid2

**Kind:** project  
**Repo:** https://github.com/adrianwedd/grid2_repo  
**URL:** (none)  

---

### A) BLOG POST REVISIONS

CHANGE: [the tags list]
TO: `tags: ['ai', 'web', 'typescript', 'nextjs', 'tailwind']`
REASON: [The readme explicitly mentions Next.js and Tailwind CSS; these are important technical descriptors missing from the initial tags.]

CHANGE: ["The real-time editor lets you see changes as you make them, with full undo/redo history."]
TO: ["The real-time editor provides immediate visual feedback using a dedicated preview API and hook system, complete with full undo/redo history."]
REASON: [The original text was slightly generic; the revision aligns with the technical architecture mentioned in the repository (preview API and hook system).]

CHANGE: ["Right now it uses regex. You could layer an LLM classifier on top."]
TO: ["It currently utilizes a regex-based parser, providing a robust foundation for more advanced natural language processing layers."]
REASON: [The phrasing "Right now it uses" sounded unnecessarily informal and slightly dismissive of the architectural choice; the revision maintains the professional, technical tone.]

---

### B) SYNTHESIS SCRIPT

You’re looking at a major shift in how AI-powered websites are built. If you have ever used an LLM to generate a full webpage, you know the frustration: broken layouts, hallucinated components, and inconsistent styling. You end up with a probabilistic mess rather than a reliable build system. That is exactly what Grid 2.0 solves by separating AI for understanding from algorithms for execution.

Here is how it works. Instead of asking a language model to generate raw HTML or React code, you use it solely for intent extraction. A large language model interprets what you actually want—your tone, your content structure, and your goals. But when it comes time to build the page, the model is sidelined. The actual assembly is handled by a deterministic beam search algorithm that pulls from a verified library of React components. 

Because the system is deterministic, you get the same reliable page every time you input the same instructions. The component library itself is tone-aware. Whether you need a minimal, bold, playful, or corporate look, the brand identity propagates throughout the entire site automatically.

You are not just looking at a static generator, either. The project includes a pure transform system. These are predictable, reproducible functions that modify your page state, giving you surgical control over the assembly. You can see these changes happen in real-time through the built-in editor, which supports a full undo and redo history.

The entire architecture is built on a foundation of TypeScript, Next.js, and Tailwind CSS. It is designed to be developer-friendly, offering features like code export to static HTML or full Next.js applications, and includes a comprehensive suite of unit and end-to-end tests to ensure the pipeline stays stable. 

If you are tired of fighting with unpredictable AI outputs and want a web building tool that is as reliable as it is smart, check out the source code at the repository linked on this page.
