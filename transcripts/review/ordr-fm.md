# Review: ordr-fm

**Kind:** project  
**Repo:** https://github.com/adrianwedd/ordr.fm  
**URL:** (none)  

---

### A) BLOG POST REVISIONS

CHANGE: `description: 'Precision-engineered CLI for intelligent music library organisation. EXIF metadata, lossless prioritisation, zero-overwrite safety.'`
TO: `description: 'Precision-engineered CLI for intelligent music library organisation. Intelligent tag enrichment, lossless prioritisation, zero-overwrite safety.'`
REASON: Correction. Music files do not use EXIF metadata (which is for images); the system uses audio-specific metadata and database lookups (Discogs/MusicBrainz).

CHANGE: `tags: ['music', 'cli', 'node', 'audio']`
TO: `tags: ['music', 'cli', 'bash', 'audio']`
REASON: Correction. While the dashboard is a Node.js PWA, the core engine described in the post and README is a bash-based CLI tool.

CHANGE: `It processes ten thousand albums in twenty to forty-five minutes.`
TO: `Remove this sentence.`
REASON: Inaccuracy. This specific performance claim is not supported by the README, and performance benchmarks were not provided.

CHANGE: `ordr.fm sorts chaos into harmony. It organises music libraries using EXIF metadata, MusicBrainz and Discogs lookups...`
TO: `ordr.fm sorts chaos into harmony. It organises music libraries using advanced tag enrichment, MusicBrainz and Discogs lookups...`
REASON: Correction. EXIF is image metadata.

---

### B) SYNTHESIS SCRIPT

If you have spent years carefully curating your music library, you know the frustration of watching a bulk organizer mangle your metadata or silently overwrite your high-fidelity files with lossy duplicates. I built ordr.fm because I had a collection that was too valuable to trust to standard tools. It is a precision-engineered system designed to transform a chaotic music archive into an organized, media-server-ready library without ever sacrificing the integrity of your source files.

At its heart, ordr.fm is a robust bash-based command-line tool that prioritizes safety above all else. It uses a comprehensive dry-run mode and atomic file operations to ensure that your music is never altered until you are ready. The system integrates directly with Discogs and MusicBrainz to perform intelligent, album-centric metadata enrichment. It understands the nuances of electronic music labels, catalog numbers, and complex artist collaborations, ensuring your files are tagged and sorted with professional-grade accuracy.

While the core engine handles the heavy lifting of organization, the system includes a modern, interactive web dashboard built as a progressive web application. This gives you a clear window into your collection, complete with waveform visualization, advanced search presets, and real-time statistics. It also manages automated, resumable backups to Google Drive, so your hard work is always protected. Whether you are dealing with thousands of albums or just cleaning up your primary listening folder, ordr.fm provides the control and transparency needed to manage your library with confidence. You can see how the system works and get started with your own library by visiting the project repository at github.com/adrianwedd/ordr.fm.
