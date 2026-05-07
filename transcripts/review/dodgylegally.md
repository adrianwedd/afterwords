# Review: dodgylegally

**Kind:** project  
**Repo:** https://github.com/adrianwedd/dodgylegally  
**URL:** (none)  

---

### A) BLOG POST REVISIONS

CHANGE: "Type a random word. Get a sample pack."
TO: "Type a number. The tool picks two random words from a 5,000-word dictionary, creates an absurd phrase, and generates a sample pack from the results."
REASON: The blog post oversimplified the mechanics; the source repo specifies a number input that generates random phrase pairs, not a single word input.

CHANGE: "dodgylegally generates audio instruments from chaotic search phrases, pulling from YouTube, local files, and a five-thousand-word dictionary with weighted source mixing."
TO: "dodgylegally generates audio samples from chaotic search phrases, pulling from YouTube or your own local audio files, with weighted source mixing based on a five-thousand-word dictionary."
REASON: The dictionary is used for the phrases, not as a source of audio.

CHANGE: "One-shot and loop processing with cross-fading. BPM-aware looping and beat alignment."
TO: "One-shot and loop processing with cross-fading."
REASON: The README does not mention "BPM-aware looping" or "beat alignment," making this an unsupported claim.

CHANGE: "The name is the philosophy: sampling from the wild, with just enough attribution to sleep at night."
TO: "The name is the philosophy: sampling from the wild, while tracking the provenance of every clip."
REASON: The README emphasizes provenance tracking via JSON sidecars, not the "attribution" implication of the name.

---

### B) SYNTHESIS SCRIPT

The best samples often come from the places you are not looking. If you are tired of spending hours scrolling through sample libraries, you are exactly who I built dodgylegally for. The idea is simple. Instead of browsing for a sound that fits, you create it by accident.

Here is how it works. You type a number, and the tool does the rest. It picks two words at random from a five-thousand-word dictionary to form a phrase no human would ever intentionally type. It then searches for that phrase on YouTube or through your own local audio files, downloads a short clip, and turns it into something musical. It processes these clips into one-shots and seamless cross-faded loops.

The magic is in the workflow. You can generate a few samples, or you can run it a hundred times to build an entire instrument. Because every search is unique, no two people will ever get the same results. And for those who need to stay organized, every file comes with a JSON sidecar. This tracks exactly where the sample came from, which original phrase was used, and what transformations were applied. This means your creative chaos is always reproducible.

You can use the full pipeline with a single command, or you can take manual control of the search, download, processing, and combination stages separately. It even supports custom presets for specific moods, like ambient textures, or you can mix your sources with custom weights between YouTube and your local drive. 

Stop scrolling and start generating. You can find the code and start building your own library today at the dodgylegally GitHub repository.
