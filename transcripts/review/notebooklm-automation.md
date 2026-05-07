# Review: notebooklm-automation

**Kind:** project  
**Repo:** https://github.com/adrianwedd/notebooklm-automation  
**URL:** (none)  

---

### A) BLOG POST REVISIONS

CHANGE: "If you have 80 notebooks and want to back them up, you click through each one manually."
TO: "If you want to back up your notebooks, you typically click through each one manually to export them."
REASON: Accuracy — The source does not specify the number of notebooks, just the nature of the manual labor.

CHANGE: "Create notebooks from code. Add sources from URLs, text, or Google Drive."
TO: "Create notebooks programmatically. Add sources from URLs, text, or Google Drive files."
REASON: Clarity — Aligning with the README feature description.

CHANGE: "The parallel generation system launches multiple artefacts concurrently—three in 60 seconds versus 180 sequential."
TO: "The parallel generation system launches multiple artifact types concurrently, significantly reducing wait times compared to sequential generation."
REASON: Correctness — The specific time metrics (three in 60 seconds) are not explicitly supported by the README; generalizing is safer and more accurate.

CHANGE: "Multi-format export converts notebooks to Obsidian vaults with wikilinks, Notion-compatible markdown, or Anki flashcard CSVs."
TO: "Multi-format export supports Obsidian vault structures with wikilinks, Notion-compatible markdown, and Anki-ready CSV formats."
REASON: Precision — Better alignment with README terminology.

---

### B) SYNTHESIS SCRIPT

Google built NotebookLM as a walled garden, keeping your research, generated audio, and studio artifacts trapped behind their interface. If you need to back up your notebooks or automate artifact generation, you are forced to do it manually. I built a door. By reverse-engineering the internal remote procedure call protocol, this project provides the programmatic control that Google left out.

You can now export entire notebooks—including sources, notes, and all studio artifacts—into structured local directories. This includes your audio and video overviews, reports, slide decks, and even structured data like mind maps and flashcards. Instead of clicking through your library, you can run exports for a single notebook or your entire collection with one command.

The system goes further than simple exports. It includes a full automation pipeline that lets you create notebooks and add sources—like URLs, text, or files from Google Drive—programmatically. You can even use the smart creation mode to start from a topic, let the script research it via web and Wikipedia, and automatically build a populated notebook. 

For high-volume work, the parallel generation system handles artifact creation concurrently, drastically cutting down the time you spend waiting for results. It also features a JSON-driven template system, letting you define configurations for specific workflows like academic research, podcast preparation, or course notes. Everything you export is structured for your existing tools, with support for Obsidian vaults, Notion-ready markdown, and Anki flashcards.

Because this relies on unofficial APIs, the project is designed for power users who understand that interfaces can change. If you are ready to take control of your research, you can find the complete CLI tool, installation instructions, and the full automation suite on the GitHub repository. Check out the link in the description to get started.
