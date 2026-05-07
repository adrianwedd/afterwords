# Review: modelatlas

**Kind:** project  
**Repo:** https://github.com/adrianwedd/ModelAtlas  
**URL:** (none)  

---

### A) BLOG POST REVISIONS

CHANGE: "Most metadata about them is incomplete, inconsistent, or wrong. Context lengths are missing. Base model lineage is ambiguous. Quantisation details are buried in config blobs that nobody parses."
TO: "Most metadata is incomplete, inconsistent, or incorrect. Critical details like context lengths, base model lineage, and quantization specifics are often buried in configuration blobs."
REASON: Clarification and professional tone; "nobody parses" is slightly hyperbolic.

CHANGE: "I built ModelAtlas to make that process systematic. It is a framework for parsing, enriching, auditing, and visualising the foundation model landscape. It starts with raw scrapes from Ollama's registry, then runs a recursive enrichment agent—RECURSOR-1—that normalises fields, infers missing data, decodes manifests, and uses LLMs to fill gaps that heuristics cannot."
TO: "ModelAtlas makes this process systematic. It is a forensic-grade, modular intelligence framework designed for parsing, enriching, auditing, and visualizing the foundation model landscape. It ingests raw metadata from the Ollama registry and employs RECURSOR-1—a recursive enrichment agent—to normalize fields, infer missing data, decode manifests, and leverage LLMs to bridge gaps heuristics cannot fill."
REASON: Alignment with README's description of the project as a "forensic-grade, modular intelligence framework."

CHANGE: "TrustForge computes a trust score for each model by fusing metrics across dimensions: licence compliance, download statistics, upstream lineage, and LLM-inferred risk."
TO: "TrustForge computes a trust score by fusing metrics including license compliance, download statistics, upstream lineage, and LLM-inferred risk assessments."
REASON: Consistency with README components.

CHANGE: "A CLI provides semantic search. A React dashboard is in development for visual analytics. The whole pipeline runs from a single command."
TO: "The framework includes a semantic search CLI, an automated enrichment trace, and a React-based dashboard, AtlasView, for visual analytics."
REASON: Accurate reflection of current status; README indicates `AtlasView` is a core component.

---

### B) SYNTHESIS SCRIPT

The foundation model landscape has exploded, with thousands of new entries appearing constantly. The problem is that metadata is often incomplete, inconsistent, or simply wrong. If you are trying to select a model for a production system, you are essentially forced to piece together the truth from fragmented and opaque configuration files. ModelAtlas was created to make this process systematic.

It is a forensic-grade intelligence framework designed to parse, enrich, audit, and visualize the model landscape. The system starts by harvesting raw metadata from the Ollama registry. From there, it hands off the data to RECURSOR-1, a recursive enrichment agent that normalizes fields, decodes manifests, and uses large language models to fill in the technical gaps that standard heuristics cannot reach.

What you get is structured, versioned metadata with full provenance tracking. The framework includes TrustForge, which computes a quantifiable trust score by fusing metrics like license compliance, download statistics, and lineage. You also get TracePoint, a lineage debugger that lets you inspect any model's journey from the raw scrape through every enrichment decision, including the specific prompts that drove those inferences.

This architecture ensures that when you need to select a model, you can trace exactly why it exists, what it was built from, and whether the claims about it hold up. The project provides a semantic search CLI for quick queries and includes AtlasView, a web-based dashboard for interactive visual analytics. You can install the framework and begin auditing your model landscape immediately by checking out the project on GitHub.
