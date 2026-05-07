# Review: giving-a-robot-three-voices

**Kind:** blog  
**Repo:** (none)  
**URL:** (none)  

---

### A) BLOG POST REVISIONS

CHANGE: "Qwen3-TTS's Base model does zero-shot voice cloning. You give it a reference audio clip, a transcript of what's said in the clip, and the text you want spoken. It generates new s"
TO: "Qwen3-TTS's Base model excels at zero-shot voice cloning. You simply provide a reference audio clip, a highly accurate transcript of that clip, and your target text. It then synthesizes the target text in the persona's voice, maintaining the emotional cadence of the reference."
REASON: The original text was cut off abruptly ("new s") and the added detail regarding transcript accuracy reflects the requirement for high-fidelity cloning.

CHANGE: "The 0.6B model looked promising. It looked promising until we checked the requirements."
TO: "The 0.6B model looked promising, at least until we looked at the system requirements."
REASON: Improves flow and removes repetitive phrasing.

POST OK (With the above edits applied, the content is accurate, technically sound based on the provided data, and complete.)

---

### B) SYNTHESIS SCRIPT

You are looking at a project that finally gives my PiCar-X robot the voice it deserves. For a long time, my robot used espeak, which essentially sounds like a nineties GPS navigator trying to recite poetry. It was functional, sure, but it lacked any sense of personality. I needed to move beyond that and give my three robot personas distinct voices, all while operating under the strict constraints of a Raspberry Pi 4.

The challenge was that the Pi just didn't have the overhead to run modern text-to-speech models, and running them on my M1 Mac with standard tools wasn't much better. My initial attempts with PyTorch were a disaster. It treated the Mac’s unified memory like traditional VRAM, aggressively allocating and fragmenting memory until the system ground to a halt.

The breakthrough came with Apple's MLX framework. Because MLX was built specifically for Apple Silicon, it uses memory efficiently with zero-copy operations and lazy evaluation. By using an eight-bit quantized version of the Qwen3-TTS model, I managed to get the peak memory usage down to six gigabytes. This allows the model to run smoothly on the Mac without crashing or triggering heavy swap usage, keeping the rest of my services responsive.

The results are striking. By using fifteen seconds of clean reference audio and a highly accurate transcript for each persona, I can now clone their voices with impressive fidelity. It has completely transformed the robot’s interaction style from a robotic monotone into something much more grounded and expressive.

If you are interested in the technical details of how I implemented this pipeline or want to see how these voices sound in action, head over to the project page at spark.wedd.au to read the full breakdown.
