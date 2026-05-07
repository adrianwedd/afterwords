# Review: cv

**Kind:** project  
**Repo:** cv  
**URL:** (none)  

---

### A) BLOG POST REVISIONS

CHANGE: "An activity tracker collects real commit data, language statistics, and contribution metrics from the live work."
TO: "An activity tracker collects real commit data, language statistics, and contribution metrics from live activity."
REASON: Clarification of source material; the term "live activity" is more precise than "live work" in the context of a pipeline.

CHANGE: "When the work shifts, the CV shifts with it — not in six months when you remember to update a Word file, but on the next scheduled run, as a natural consequence of the work itself."
TO: "When the work shifts, the CV shifts with it — not in six months when you remember to update a file, but during the next twice-daily scheduled run, as a natural consequence of the work itself."
REASON: Correctness; the pipeline runs twice daily, not continuously.

CHANGE: "The multi-locale architecture matters because translation isn't just about changing words — it's about how competence is signalled across cultures. The same experience presented to a Japanese employer needs different emphasis than when presented to an Australian one. Not dishonesty. Contextual framing."
TO: "The multi-locale architecture matters because translation isn't just about changing words — it's about how competence is signalled across cultures. The same experience presented to a Japanese employer may require different framing than when presented to an Australian one. Not dishonesty. Contextual framing."
REASON: Correctness; the source does not detail *how* the framing changes, only that it is necessary.

---

### B) SYNTHESIS SCRIPT

You are looking at a CV that functions less like a static document and more like a live data pipeline. Most professional résumés operate on a flawed premise. They treat a career as a linear progression where skills accumulate neatly and the most recent role is automatically the most significant. This approach ignores the reality that static documents begin to decay the moment they are exported.

My solution shifts this paradigm. I have built a pipeline that treats your career history as a stream of live activity data. Twice a day, a GitHub Action triggers, pulling in your actual commit history, language statistics, and contribution metrics. A Claude AI pipeline then processes this raw data and regenerates your profile.

Crucially, this system is built with safety as its primary constraint. Before any deployment, the content passes through two distinct gates. A hallucination detector validates every claim against your hard GitHub metrics, while a content guardian maintains a registry of verified facts, actively blocking any generated text that tries to fabricate an achievement. This pipeline will not ship an invention because it is architecturally prevented from doing so.

This is not just about automation, but about contextual framing. The pipeline handles multi-locale requirements because the signals of competence vary significantly across cultures. An experience that requires one type of emphasis for an Australian employer might require a different framing for a Japanese one. The system automates this translation while maintaining the underlying truth of the data.

Your professional history should be as alive as the work you actually perform, and it should be able to provide proof that it isn't lying. When your work shifts, your CV evolves with it, not weeks or months later, but as a direct result of your activity during the next scheduled run.

See how the pipeline operates and view the current live deployment at my website.
