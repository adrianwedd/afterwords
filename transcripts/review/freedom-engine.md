# Review: freedom-engine

**Kind:** project  
**Repo:** https://github.com/adrianwedd/freedom-engine  
**URL:** (none)  

---

### A) BLOG POST REVISIONS

CHANGE: "264,000 people can't afford that gap."
TO: "264,000+ federal inmates are potentially eligible for these credits."
REASON: Correctness/Precision; reflects the source data provided in the README regarding the eligible population.

CHANGE: "I built the Freedom Engine to bridge that gap. It is an AI-assisted Q&A service that takes questions about FSA time credits—submitted through prison email systems like CorrLinks and JPay—and returns accurate, plain-language answers grounded in federal statutes, Bureau of Prisons policy statements, and relevant case law."
TO: "I built the Freedom Engine to bridge that gap. It is a secure, human-in-the-loop Q&A service that helps federal inmates understand and apply the First Step Act (FSA) Time Credit system. By providing accurate, plain-language answers grounded in federal statutes, BOP policies, and case law, we aim to reduce confusion and facilitate potential sentence reductions."
REASON: Correctness; the current implementation roadmap prioritizes a "fully manual response service" with AI assistance coming in later phases.

CHANGE: "The phased roadmap starts with a fully manual response service, builds a training corpus from real questions, and only introduces RAG-assisted drafting once accuracy has been validated by legal experts on real data."
TO: "The phased roadmap starts with a fully manual response service, builds a training corpus from real questions, and reserves RAG-assisted drafting for future phases, strictly after accuracy has been validated by legal experts."
REASON: Clarity; improves the distinction between current operations and the future roadmap.

---

### B) SYNTHESIS SCRIPT

Over two hundred sixty-four thousand people are currently held in the federal prison system. Many of them are eligible for reduced sentences under the First Step Act. While the information is public, the legal complexity makes it incredibly difficult for inmates to navigate without outside help. That is why I built the Freedom Engine. It is a secure, human-in-the-loop service designed to bridge the gap between complex legal statutes and the people who need that information most.

When an inmate submits a question about their time credits through systems like CorrLinks or JPay, they are looking for clear, accurate, and actionable information. My approach prioritizes security above everything else. Because I am handling sensitive data, I have implemented a three-layer privacy redaction quorum to strip personal information before it ever reaches a language model. HSM tokenization vaults then handle what remains. 

To ensure the highest level of accuracy, every response currently undergoes one hundred percent human review. AI exists here to assist our legal experts, never to decide alone. In a situation where a wrong answer directly affects someone's liberty, confidence scores and human validation are not optional features; they are absolute requirements.

The legal landscape is constantly changing, so I have built a version-controlled knowledge base that uses versioned interpretations of federal statutes, Bureau of Prisons policy statements, and evolving case law. This ensures that the information we provide remains grounded and accurate even as the law shifts. 

The project follows a careful, phased roadmap. We are currently operating a fully manual response service to build a robust training corpus based on real questions. Only after our legal experts have validated our accuracy on this real-world data will we introduce RAG-assisted drafting to scale our support. 

I care about this because those who need these services the most often have the least ability to advocate for themselves. Technology should be a tool that closes that gap, not one that widens it. If you want to learn more about how this is being built or follow the project’s progress, you can find the repository and more information at the link below.

https://github.com/adrianwedd/freedom-engine
