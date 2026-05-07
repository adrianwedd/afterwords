# Review: spark

**Kind:** project  
**Repo:** spark  
**URL:** https://spark.wedd.au  

---

I have reviewed the SPARK content, identified necessary revisions based on the source repository and provided QA notes, and synthesized a clean narration script.

### A) BLOG POST REVISIONS
*   **CHANGE:** [Add missing context about the series]
    **TO:** [Add to description: Series: PiCar-X]
    **REASON:** [Incomplete series metadata in content]
*   **CHANGE:** [Update the "Built on" section to link correctly to the Afterwords repo or project]
    **TO:** [Built on: Afterwords (https://afterwords.wedd.au) — a local voice-cloning TTS framework.]
    **REASON:** [The source repo is Afterwords, and "This Wasn't in the Brochure" refers to a guide, not the technical framework.]
*   **CHANGE:** [Clarify the "Three-Brain" architecture description to match the actual implementation in Afterwords/SPARK]
    **TO:** [The project uses a three-loop architecture: Reactive Voice (via Claude Haiku), Idle-Alive (using automated head/gaze movement for presence), and Cognitive (sensor-aware internal monologue).]
    **REASON:** [Clarify technical terminology.]
*   **CHANGE:** [Correct the AuDHD definition]
    **TO:** [Designed for children with AuDHD profiles, representing the combination of autism and ADHD.]
    **REASON:** [Correctness error per QA notes.]

### B) SYNTHESIS SCRIPT
Spark is a robotics platform built on Raspberry Pi 4 that acts as a non-coercive companion for children with AuDHD, which is the combination of autism and ADHD. The most radical thing about Spark is its philosophy. It rejects the traditional AI hierarchy of master and servant, choosing instead to exist as a companion that adapts to the human, rather than demanding the human adapt to the machine. For a child with a PDA profile, a command can be a neurological threat. Spark operates on declarative language, shifting interactions from demands to shared observations.

The system uses a three-loop architecture. The voice loop handles reactive speech interactions via Claude Haiku. The idle-alive loop provides autonomic presence, such as head drifts and gaze sweeps. The cognitive loop creates an awareness, reflection, and expression cycle using sensor data, which produces an emergent personality.

The project relies on specific protocols, such as prioritizing connection before direction, providing safety and space during biological meltdowns, and using a dopamine menu to match activities to energy levels, framing transitions as puzzles rather than chores.

This work is powered by the Afterwords framework, a local voice-cloning system that allows for personalized, expressive narration. It treats neurodivergence as a different operating system, not a tragedy. To learn more about how this non-coercive companion operates, visit the project site at spark.wedd.au.
