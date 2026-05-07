# Review: adhdo

**Kind:** project  
**Repo:** https://github.com/adrianwedd/ADHDo  
**URL:** (none)  

---

### A) BLOG POST REVISIONS

CHANGE: "The system runs a three-stage cognitive pipeline. A state gatherer reads physical, temporal, and environmental context — medication windows, sitting duration, task backlog, energy levels. A reasoning engine with confidence gating processes that state; it won't act unless it understands the situation."
TO: "The system is built as an MCP server that integrates with your digital environment. It uses a Claude-powered reasoning engine to act as an ADHD-specific coach, providing task breakdown, hyperfocus management, and gentle, non-judgmental accountability."
REASON: The original description hallucinates a specific "three-stage cognitive pipeline" (state gatherer, confidence gating) not present in the actual repository, which is an MCP (Model Context Protocol) server implementation.

CHANGE: "Then a tools executor orchestrates interventions: focus music, timers, ambient nudges, environment controls. The loop closes in under 450 milliseconds on average..."
TO: "It orchestrates interventions through connected tools like Jellyfin for focus music, Telegram for mobile nudges, and Google Home integrations. The system is optimized for a sub-three-second response time to stay within the limits of ADHD attention spans."
REASON: Corrects the hallucinated "450ms" latency claim to match the repository’s "sub-3-second" design goal.

CHANGE: "The crisis detection system monitors for repetitive questions, frustrated language, task-switching chaos, and negative self-talk, then intervenes with de-escalation — not platitudes. Hyperfocus management detects extended sessions and suggests breaks without breaking flow state."
TO: "The system is designed to detect signs of overwhelm, such as task paralysis or repetitive questioning, and responds with de-escalation strategies and small, actionable steps rather than toxic positivity."
REASON: Matches the provided repository documentation regarding "Overwhelm Detection" without over-promising technical capabilities that aren't evidenced in the current code structure.

---

### B) SYNTHESIS SCRIPT

If you have an ADHD brain, you know that most productivity tools feel like they were designed by people who have never experienced task paralysis. When you get distracted or overwhelmed, standard apps don't fail gracefully. They judge you. They turn your missed reminders into evidence of a character flaw. I got tired of that cycle, so I built an alternative. It is called ADHDo, and it treats executive function as a variable, not a constant.

At its core, this is a personal AI coach that works with your brain rather than against it. It is built as an MCP server, which is just a technical way of saying it connects your AI directly to the tools you actually use, like your calendar, your music library, or your mobile messages. 

The biggest problem with most AI assistants is the lag. If you wait too long for a response, your brain has already moved on to something else. ADHDo is optimized for speed, delivering responses in under three seconds so you can maintain your momentum. It handles the things that usually stop us cold. If you are staring at a massive list of tasks and feeling frozen, it doesn't just tell you to work harder. It helps you break those tasks down into tiny, actionable pieces until the paralysis breaks. 

It also keeps an eye on your hyperfocus. We all know how easy it is to lose track of time when you are in the zone, only to crash later. The system provides gentle, optional nudges to remind you to take a break, but it does so without making you feel guilty. And that is the most important part. There is no shame, no disappointment, and no toxic positivity here. It is just a scaffold for your day. 

You can set it up in a couple of minutes by cloning the repository and connecting your own session keys. It is private, it is fast, and it is finally a tool that understands that your brain is wired differently. If you are ready for an assistant that actually helps you get things done without the judgment, head over to the project repository on GitHub to get started.
