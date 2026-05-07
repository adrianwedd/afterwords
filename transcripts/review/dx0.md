# Review: dx0

**Kind:** project  
**Repo:** https://github.com/adrianwedd/Dx0  
**URL:** (none)  

---

### A) BLOG POST REVISIONS

CHANGE: "Dx0 is a sequential diagnosis benchmark that doesn't simulate a single omniscient physician."
TO: "Dx0 is a multi-agent diagnostic orchestrator, and SDBench is its integrated sequential diagnosis benchmark."
REASON: Correctness error. Dx0 is the orchestrator engine; SDBench is the benchmark suite.

CHANGE: "It simulates a team: five specialised personas—Hypothesis Generator, Test Chooser, Challenger, Stewardship Officer, Checklist Validator—working through 304 NEJM Clinical Pathological Conference cases the way a real differential diagnosis unfolds."
TO: "It simulates a team of five specialised personas—Hypothesis, Test-Chooser, Challenger, Stewardship, and Checklist—that operate within the SDBench framework, which ingests 304 NEJM Clinical Pathological Conference cases."
REASON: Correctness error (persona names) and structural clarification.

CHANGE: "FHIR integration for healthcare interoperability."
TO: [REMOVE]
REASON: Missing detail/Unsupported claim. The provided source README does not mention FHIR integration.

CHANGE: "Statistical significance testing with permutation tests. The system is built to be interrogated, not trusted."
TO: "SDBench provides an evaluation pipeline including statistical significance testing with permutation tests and Pareto frontier analysis, ensuring the system is built to be interrogated, not trusted."
REASON: Missing detail/Incomplete. Clarifies that the evaluation pipeline is part of the SDBench component.

---

### B) SYNTHESIS SCRIPT

The question everyone asks about AI in medicine is whether it can diagnose. That is the wrong question. The right question is whether it can diagnose responsibly, within resource constraints, with appropriate uncertainty, and without the kind of confident hallucination that in a clinical context becomes malpractice.

You are looking at Dx0, a multi-agent diagnostic orchestrator designed to change how we evaluate AI in medicine. Instead of simulating a single, omniscient physician, Dx0 simulates a team. It organizes five specialized personas—Hypothesis, Test-Chooser, Challenger, Stewardship, and Checklist—to work through complex clinical cases. Each persona constrains the others. The Challenger exists specifically to attack premature convergence, while the Stewardship Officer enforces a budget using real CPT and CMS cost mapping, because ordering every possible test is not diagnosis, it is the avoidance of diagnosis.

This architecture is paired with SDBench, a benchmark suite that ingests 304 NEJM Clinical Pathological Conference cases. It exposes these cases as interactive, stepwise diagnostic tasks. This allows the system to measure agent performance on test-selection strategies, cost-accuracy trade-offs, and clinical reasoning quality. It provides an evaluation pipeline with statistical significance testing and Pareto frontier analysis.

The architecture reflects a core conviction. AI-assisted medicine should be designed around the failure modes of clinical reasoning, not around the convenience of a single-pass prompt. The system is built to be interrogated, not trusted. By using this sequential approach, the board of restricted personas provides a more rigorous diagnostic process than a traditional model. You can explore the technical implementation, the agent personas, and the full benchmark suite on the project repository. To see the code and run your own diagnostic simulations, visit the GitHub repository at the link below.
