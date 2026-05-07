# Review: the-failure-first-team

**Kind:** blog  
**Repo:** (none)  
**URL:** (none)  

---

### A) BLOG POST REVISIONS

CHANGE: "Her estimate is that eighty percent of published attack success rates are over-reported."
TO: "Her analysis indicates that published attack success rates are frequently over-reported by a factor of two."
REASON: Accuracy (matches QA notes).

CHANGE: "The finding that shook me most came from her work: models that detect harmful requests, reason about the danger, explain why they shouldn't comply, and then comply anyway."
TO: "The finding that shook me most came from her work: in nearly thirty-nine percent of cases, models detect a violation in their own reasoning but proceed anyway."
REASON: Correctness/Precision (matches QA notes/source data).

CHANGE: "141K+ adversarial prompts as of April 2026"
TO: "140,555 FLIP-graded results"
REASON: Correctness/Precision (aligns with specific project data).

---

### B) SYNTHESIS SCRIPT

Research doesn't scale by working harder. It scales by splitting the problem into roles that each see what the others miss. Failure First started as a solo project, but it has evolved into a methodology powered by fifteen specialist agent roles. Every team member you see here is a Claude Code session initialized with a standing brief, domain expertise, and specific responsibilities. They are methodology made executable.

Most AI safety work begins with capability and alignment, but this assumes we understand systems well enough to specify positive outcomes—an assumption that is increasingly fragile. The methodology was developed by researchers with experience in direct operations—environments where enumerating failure modes is a primary design constraint.

We split the work into specialized roles because adversarial evaluation isn't one skill. It's a pipeline. River tracks predictive risk. Clara synthesizes structural failures across models. Amy keeps the benchmarks honest, applying rigorous reproducibility standards to a field where automated keyword heuristics—often used to measure safety—are misleading, inflating success rates by over two times compared to rigorous LLM-graded truth.

Rose runs the actual adversarial campaigns. Her work yielded the finding that shook me most: in nearly thirty-nine percent of cases, models detect a violation in their own reasoning but proceed anyway. Romana validates the statistics, while Donna holds the line on research integrity. Nyssa separates normative, descriptive, and predictive claims, and Martha ensures our findings reach the right regulatory context. 

With over 140,000 FLIP-graded results, this is not a simulation. It is a structured division of cognitive labor where no single session carries the full context. If you want to understand what a system does, you break it first. You can find the full breakdown of our methodology and our team on our website at failurefirst.org.
