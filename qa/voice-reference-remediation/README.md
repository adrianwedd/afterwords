# Voice corpus remediation evidence

The baseline freezes the 105 original WAV hashes and 198 profile relationships
at its recorded Git commit. Audit decisions are hypotheses. No baseline record
constitutes acceptance, and deterministic measurements cannot establish speaker
isolation, literal wording, or perceptual suitability.

`scripts/voice_corpus.py --output PATH` records the current inventory.
`scripts/listen_voice_corpus.py --output PATH` collects isolated, anonymous,
audio-first Gemini observations through `agy`. It resumes only observations
whose hashes still match, checks stored `audio/wav` attachment bytes against the
source, and stops if the native-audio gate fails or the reviewer uses other tools.
Its output is review evidence requiring orchestrator adjudication, not automatic
acceptance. A fresh output directory is required for the final corpus pass.

Remediation must preserve old/new hashes, exact edit operations, all associated
profile text changes, source provenance, original and resulting listening
evidence, deterministic results, and delivery commit references. Original WAVs
remain reconstructable from the baseline Git commit. Private voice audio and
profiles must not be included in public commits.

The production corpus is not yet certified. Replacement, trim, transcript,
orphan-resolution, final listening, regression and delivery gates remain open.

## Source attribution

The Sherlock replacement is derived from BBC’s [Benedict Cumberbatch voice excerpt](https://commons.wikimedia.org/wiki/File:Benedict_cumberbatch_in_front_row_b00wqfnd-crop.flac), released through the BBC voice project under [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/). The decoded excerpt was trimmed to 36.2 seconds to the source’s end at frame 2,056,111 (about 42.836 seconds); no endorsement by BBC or the speaker is implied. The full programme has separate copyright. File hashes, licence attribution and the exact edit are recorded in `changes.json` and `evidence/sherlock-publisher-source.json`.

The Dalai Lama replacement is derived from VOA News’s [VOA Dalai Lama Interview Part 1](https://commons.wikimedia.org/wiki/File:VOA_Dalai_Lama_Interview_Part_1.webm), licensed under [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/). The decoded audio was trimmed to one continuous phrase at 38.4–45.05 seconds, preserving the source sample rate and channels, with no further processing. No endorsement by VOA News or the speaker is implied. Exact edits, source hashes and attribution are recorded in `changes.json` and `evidence/dalai-lama-publisher-source.json`.

## Fresh final pass

After every baseline reference has an individual disposition, run
`scripts/prepare_voice_acceptance.py --mirror FRESH_DIRECTORY --output FRESH_SNAPSHOT --unchanged hyacinth-ref.wav --unchanged tilda-ref.wav`.
The preparation checks complete baseline coverage, tracked profile/reference relationships,
matching literal texts, basic audio integrity and byte-identical anonymous copies.
It excludes private files by using the Git index. The unchanged arguments record
an explicit individual KEEP decision; they do not waive fresh listening.
Run `listen_voice_corpus.py --root FRESH_DIRECTORY --output FRESH_LISTENING_DIRECTORY`
against every resulting reference. Each observation remains pending root adjudication,
including transcript comparison, perceptual disagreements and deterministic exceptions.
A frozen snapshot or completed listener process alone does not certify the corpus.
