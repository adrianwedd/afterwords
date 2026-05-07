# Review: veritas

**Kind:** project  
**Repo:** https://github.com/adrianwedd/VERITAS  
**URL:** (none)  

---

### A) BLOG POST REVISIONS

CHANGE: "Conflict detection runs before any analysis begins."
TO: "Conflict detection protocols verify no conflicting interests exist before any analysis begins."
REASON: Clarifies the procedural nature of the conflict checks without implying a specific cryptographic implementation not supported by the source.

CHANGE: "An immutable audit trail with seven-year retention, because that is what the law requires."
TO: "An immutable audit trail with seven-year retention to meet strict compliance and evidence chain-of-custody requirements."
REASON: Improves technical accuracy and aligns with the source repo's focus on evidence and compliance.

CHANGE: "These are not features. They are the minimum requirements for a system that a lawyer could use without professional liability exposure."
TO: "These are not optional features; they are the fundamental requirements for any system operating in a high-liability legal environment."
REASON: Strengthens the tone and corrects the implication that these are simply "not features" to "fundamental requirements."

---

### B) SYNTHESIS SCRIPT

Legal AI has an integrity problem. Most tools optimize for speed, treating accuracy as a negotiable trade-off. But in a profession where a single hallucinated citation can end a career, that approach is fundamentally backwards. 

I built VERITAS as an AI-native legal intelligence framework designed specifically for the Australian legal system. It bridges the efficiency-trust deficit—the dangerous gap between what AI can do quickly and what a lawyer can actually trust it to do correctly. 

The architecture is built for the realities of Australian practice. It integrates a comprehensive legal corpus, precision RAG, and an IRAC-based legal reasoning engine. Everything is structured around the Australian court hierarchy, with automated AGLC4-compliant citation validation. 

Trust is engineered into every layer. We utilize a production-ready microservices architecture, which includes dedicated services for attorney-client privilege, matter segregation, and conflict detection. Before any analysis begins, the system verifies there are no conflicting interests. We also maintain an immutable audit trail with seven-year retention to satisfy the Evidence Act and strict chain-of-custody requirements.

This isn't just another chatbot with a legal database. We have built-in observability with distributed tracing using Jaeger and performance monitoring with Prometheus and Grafana. The legal knowledge graph, built on Neo4j, calculates precedent strength based on actual case relationships, not just keyword proximity.

These are not optional add-ons or premium enterprise features. They are the fundamental requirements for any system operating in a high-liability legal environment where professional reputation is on the line. 

You can explore the full technical documentation, architecture, and deployment guides at the link provided below.
