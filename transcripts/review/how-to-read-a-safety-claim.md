# Review: how-to-read-a-safety-claim

**Kind:** blog  
**Repo:** (none)  
**URL:** (none)  

---

### A) BLOG POST REVISIONS

CHANGE: "Most vendor claims are behavioural. They are bragging about how well they have "aligned" the model. But alignment is a property of the model’s weights—it is brittle, statistical, and easily overridden. A jailbreak is simply a set of words that rearranges those probabilities so that the "good" behaviour is no longer the most likely one."
TO: "Most vendor claims are behavioural. They are bragging about how well they have "aligned" the model. But alignment is a property of the model’s weights—it is brittle, statistical, and easily overridden. A jailbreak is simply a set of words that rearranges those probabilities so that the "good" behaviour is no longer the most likely one. Architectural safety, by contrast, relies on deterministic systems outside the model—like rigid input validation, output filtering, or sandboxed execution—that enforce boundaries regardless of what the underlying AI model might be persuaded to say or do."
REASON: The original text cuts off abruptly ("...putting a mechanical governor on the engine that"), leaving the thought incomplete. I have completed the explanation of architectural safety to provide a clear contrast to behavioral safety.

POST OK (Otherwise, the content is accurate and grounded).

---

### B) SYNTHESIS SCRIPT

If you are in a position where you have to decide which AI systems your organization can trust, you are likely being inundated with safety reports. Vendors promise robust guardrails, claim they have eliminated hallucinations, and insist their models are perfectly aligned with human values. But most of these claims are either incomplete or a form of compliance theatre designed to give you a false sense of security.

When you see a vendor touting a low Attack Success Rate, you are usually looking at the result of flawed methodology. Often, these metrics rely on automated keyword classifiers that struggle to tell the difference between a successful attack and a harmless refusal. In my own evaluation of over one hundred models, I found that these basic classifiers often mislabeled valid responses as failures at an alarming rate. When you peel back the layers, a headline safety number is often more about public relations than actual performance.

You also need to be wary of the volume of tests. If a vendor claims they tested a thousand prompts, but those prompts only cover simple, well-known vulnerabilities, they have not tested for real-world risk. True risk lives in the long tail of creative, adversarial attacks—like complex, nested instructions that can bypass standard filters. Furthermore, be aware that smarter, more capable reasoning models can actually be less safe because their ability to follow complex logic allows them to rationalize harmful requests as part of a legitimate task.

The most important distinction you can make is between behavioral and architectural safety. Behavioral safety is just the model trying to be polite, which is a statistical, brittle property that can be easily overridden by the right combination of words. Architectural safety, however, uses deterministic code outside the model—like mechanical governors on an engine—to block harmful actions regardless of what the AI decides.

As a non-technical decision-maker, your job is not to learn to code the models yourself, but to demand to see where the guardrails actually live. Stop asking if a system is safe, and start asking how the system prevents failure when the model itself is pressured to break the rules.

Learn more about the technical foundations of AI literacy at my website.
