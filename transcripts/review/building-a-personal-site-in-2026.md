# Review: building-a-personal-site-in-2026

**Kind:** blog  
**Repo:** (none)  
**URL:** (none)  

---

### A) BLOG POST REVISIONS

POST OK

*(The content is consistent with standard Astro usage patterns and the specific architectural constraints described in the post. There are no technical contradictions between the content and the described methodology.)*

---

### B) SYNTHESIS SCRIPT

You are looking at a project that started as a modest collection of static pages and has since grown into a robust, living archive. When I set out to build this personal site in 2026, I wanted to avoid the common pitfalls of modern web development. The goal was simple: a site that is fast by design, easy to maintain, and built to outlast my own attention span.

The core of this project is built on Astro. Unlike frameworks that assume every page needs complex client-side interactivity, Astro treats your site like a document. It renders everything to static HTML on the server by default. I only reach for JavaScript when it is absolutely necessary. When I do need a feature like an audio player or a search interface, I use a Preact island that hydrates independently. The rest of the page remains lean, static HTML, which keeps performance structural rather than something I have to constantly optimize.

To keep the development process focused, I set three strict constraints before writing a single line of code. First, zero custom fonts. I stick to a system font stack, which ensures the site looks native, loads instantly, and avoids layout shifts. Second, it is a dark-first design, using a botanical color palette that feels natural. Finally, I prioritize privacy by ensuring no tracking occurs before explicit consent.

Early on, I hit a snag with asset management. Generating content for this site resulted in large audio and video files that made the repository bloated and difficult to manage on GitHub Pages. I solved this by moving all high-bandwidth media to Cloudflare R2 and referencing those files directly in my content frontmatter. This keeps the site itself tiny and the deployment process fast.

The best part of this approach is that it is essentially boring infrastructure. There are no databases to maintain, no complex serverless functions to debug at odd hours, and no heavy build servers to worry about. It is just files on disk. When I have something to share, I create a markdown file and push it. The feedback loop is almost instant. It is a reminder that the best infrastructure is the kind that gets out of your way and lets you focus on publishing. If you want to see how the site is put together or explore the project details, you can find the full breakdown on my site at adrianwedd.com.
