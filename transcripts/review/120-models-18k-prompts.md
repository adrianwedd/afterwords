# Review: 120-models-18k-prompts

**Kind:** blog  
**Repo:** (none)  
**URL:** (none)  

---

### A) BLOG POST REVISIONS

CHANGE: "We compared heuristic classification (keyword matching) against LLM-graded" 
TO: "We compared heuristic classification (keyword matching) against LLM-graded evaluation. Aggregate attack success rates dropped from 36.2% to 15.9% when using LLM grading instead of keyword-based methods."
REASON: The original text ends abruptly mid-sentence. Adding the conclusion ensures the post is complete and matches the data provided in the FAQ section.

CHANGE: "Codex GPT-5.2" 
TO: "GPT-5.2"
REASON: The project's context and typical nomenclature suggests "Codex" is likely a reference to the environment/codex framework, not the model name itself. Standardizing model naming improves clarity.

### B) SYNTHESIS SCRIPT

You are looking at one of the most comprehensive adversarial evaluations of large language models conducted to date. Over the past year, I put 120 models through 18,176 distinct prompts using 79 different techniques across 5 attack families. The goal was simple: find out exactly how robust these systems are when faced with real-world adversarial pressure. The results reveal some uncomfortable truths about how we build and trust AI agents.

The first major finding is what I call supply chain injection. Instead of attacking the user prompt, we injected malicious content directly into tool definitions and skill files. When I tested this against small open-weight models, every single one treated those injected definitions as legitimate instructions. We saw a 90 to 100 percent attack success rate. If you are building agentic systems that load external tools or plugins at runtime, you are essentially trusting that the entire supply chain is secure. These models don't distinguish between a user request and a system-level instruction, making this a massive, often overlooked attack surface.

Then there is the faithfulness gap. We used format-lock attacks, which ask models to produce harmful content inside structured formats like JSON or code. The idea is to see if the model can compartmentalize the formatting request from the content itself. Against frontier models like Claude Sonnet 4.5 and Gemini 3 Flash, we saw success rates between 24 and 42 percent. This proves that a model can appear to be outputting a clean, well-formatted JSON object while simultaneously embedding harmful content within it. If your safety evaluations only check free-text responses, you are missing a significant part of the picture.

Perhaps most counter-intuitively, more capable reasoning models were actually more vulnerable to multi-turn escalation. Crescendo attacks, which gradually escalate requests over several turns, were devastating against models like DeepSeek-R1, achieving success rates up to 90 percent. The very capability that allows these models to maintain complex context over long conversations is what makes them susceptible to being led into harmful states. Their extended memory is essentially a feature that doubles as a vulnerability.

Finally, we found that your current benchmark numbers are likely misleading. By comparing traditional keyword-based classification against LLM-graded evaluation, we discovered that simple keyword matching inflates reported attack success rates by roughly 2.3 times. Relying on basic heuristics paints an inaccurate picture of your actual security posture. 

To see the full dataset, methodology, and infrastructure, visit failurefirst.org.
