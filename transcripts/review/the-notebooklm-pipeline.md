# Review: the-notebooklm-pipeline

**Kind:** blog  
**Repo:** (none)  
**URL:** (none)  

---

### A) BLOG POST REVISIONS

CHANGE: "The automation layer is a set of shell scripts wrapping that CLI: 1. automate-notebook.sh — Creates a notebook, adds sources, generates artifacts, exports results 2. generate-parallel.sh — Runs multiple artifact generations concurrently (3x faster) 3. research-topic.sh — Discovers and adds relevant web sources automatically"
TO: "The automation layer is a set of shell scripts that wrap the CLI to manage notebook creation, source ingestion, artifact generation, and results export. These scripts support parallel artifact generation for efficiency and can automate the discovery and inclusion of relevant web sources."
REASON: Accuracy. The source material does not explicitly list those three file names as the only components of the automation layer; summarizing their function is safer and more accurate.

CHANGE: "A full run across 32 projects takes about 2–5 hours, mostly waiting for audio generation (2–10 minutes per asset)."
TO: "A full run across 32 projects takes several hours, depending largely on the time required for audio generation, which takes 2–10 minutes per asset."
REASON: Completeness/Refinement. "2-5 hours" is a bit anecdotal; framing it as "several hours" is more professional and less prone to becoming outdated.

CHANGE: "The [pipeline documentation](https://github.com/adrianwedd/adrianwedd.com/blob/main/docs/NOTEBOOKLM_PIPELINE.md) and [automation toolkit](https://github.com/adrianwedd/adrianwedd.com/tree/main/scripts/notebooklm) are both open source."
TO: POST OK (Assuming these links are valid).
REASON: The links themselves are fine as long as they exist.

---

### B) SYNTHESIS SCRIPT

You’re looking at an automated system that turns structured markdown files into a library of multimedia assets. I found myself with thirty-two project pages, all with detailed descriptions, but no way for visitors to engage with the material beyond reading. Audio, visual summaries, and interactive quizzes are much more effective for retention and accessibility, but creating that content by hand for every page would take weeks.

To solve this, I built a pipeline around Google’s NotebookLM. It takes my source documents and generates studio-quality artifacts, including audio overviews, quizzes, mind maps, and infographics. Since NotebookLM doesn't provide an official public API, I drive it using an unofficial CLI that relies on authenticated, reverse-engineered RPCs. The entire process is managed through a JSON configuration file for each project, which tells my local shell scripts exactly which assets to generate.

When I run the batch process, the system iterates through every project, checks for missing assets, and fills the gaps. The workflow is entirely dependent on the markdown file as the single source of truth; everything else is just a derived view.

The results have been eye-opening. The AI-generated audio overviews are surprisingly effective at making dry technical content listenable, and I’ve seen a clear increase in engagement on pages where the audio player is prominent. I also optimized the process by running generation tasks in parallel, which saves hours of waiting.

However, it isn't perfect. Infographic generation is unreliable and fails on about ten percent of attempts due to service-side issues. Video summaries are also incredibly bulky, often exceeding one hundred megabytes, which makes them difficult to host on a static site. Additionally, you have to be mindful of daily quotas; NotebookLM limits audio generation, so batching thirty-two projects requires careful scheduling.

This project taught me that the pipeline itself is more valuable than any single asset it produces. It establishes a repeatable pattern: take structured content, route it through an AI service, and produce multiple accessible representations of that same material. This approach means you can provide a variety of multimedia assets without the burden of manual creation, all while maintaining a single source of truth in one place.

If you want to see how the automation works or use the toolkit for your own projects, check out the source code on my site.
