# Review: zero-build-web-development

**Kind:** blog  
**Repo:** (none)  
**URL:** (none)  

---

### A) BLOG POST REVISIONS

CHANGE: "I built a complete operations platform for my Zen Do Kai club."
TO: "I built a complete operations platform for my Wolf Clan martial arts club."
REASON: Accuracy (correcting club name as per QA notes).

CHANGE: "The middleware is 480 lines."
TO: "The core routing logic is 480 lines."
REASON: Correctness (aligning with context from QA notes to avoid implying the *entire* application is only 480 lines).

CHANGE: "Not always. Probably not most of t"
TO: "Not always. Probably not most of the time. But for a project like this, it feels like the right move."
REASON: Incomplete text in source.

---

### B) SYNTHESIS SCRIPT

I built a complete operations platform for my Wolf Clan martial arts club, and I did it with no framework, no build step, and no npm. You're looking at a site with a public marketing page, a password-gated operations hub, and a member portal that handles attendance tracking, grading, and Stripe billing. It features over twenty API endpoints, a D1 database, and security-hardened middleware, all running on vanilla HTML, CSS, and JavaScript.

This wasn't a protest against modern frameworks, but rather an experiment to see what happens when you strip them away from a real project. I needed a simple, predictable deployment story. With Cloudflare Pages, I can just push files to GitHub. There is no build cache to debug and no complex dependency tree to audit. The mental model is straightforward: files go up, site comes down.

The architecture relies on path-based authentication gating within a single middleware file. Every request hits this file, which dictates access. The public site is open, the operations hub is protected by a timing-safe password check, and the member portal uses JWT session validation to inject member data into the request context. By writing the security logic myself, I gain total visibility into the boundary. I am using crypto.subtle.timingSafeEqual to prevent side-channel attacks during password comparisons and hardcoded allowlists to secure markdown document serving.

Instead of generic page views, I implemented a heartbeat model. The portal sends a signal every thirty seconds during an active session, which allows me to track meaningful engagement metrics. I can spot members who are drifting—those who logged in frequently last month but are trailing off now—and check in with them before they cancel.

Of course, there are tradeoffs. Without a component model, I have to manage shared UI elements manually. Without TypeScript, I lose some compile-time safety, leaving room for runtime typos in database queries. And without a build pipeline, I don't get automated minification or dead code elimination for my CSS.

These are real costs, but for this project, they are significantly smaller than the overhead of a framework. If you're looking for a simpler, more transparent way to build and deploy, consider taking a look at this project at the link below.
