# Review: scraping-linkedin-without-getting-blocked

**Kind:** blog  
**Repo:** (none)  
**URL:** (none)  

---

### A) BLOG POST REVISIONS

CHANGE: "The pattern that makes sense here is a two-workflow split:"
TO: "The pattern that makes sense here involves a two-part approach to secret management:"
REASON: Clarification; "workflow" implies GitHub Actions specifically, but the principle applies to any CI/CD environment.

CHANGE: "Workflow 1 (manual, triggered when credentials expire): Opens a browser, completes authentication interactively including MFA, captures the new session values, encrypts them with GPG, and stores the result as a GitHub Actions secret via the API."
TO: "Local Helper (manual, triggered when credentials expire): Opens a browser, completes authentication interactively including MFA, captures the session cookies, and updates the local or CI secret store."
REASON: Correctness; automating the *writing* of GitHub Actions secrets via API from a workflow is complex and generally discouraged compared to local management or using dedicated tools like HashiCorp Vault or GitHub CLI (`gh secret set`).

CHANGE: "Workflow 2 (scheduled, daily): Fetches the encrypted session state, decrypts it at runtime using a key stored as a separate secret, runs the scraper, commits results."
TO: "CI Job (scheduled, daily): Pulls the session cookies from the secret store as environment variables, runs the scraper, and processes the results."
REASON: Simplification; decrypting at runtime is standard, but the primary architectural insight is the separation of the *auth-gated* session capture from the *execution* environment.

CHANGE: "I haven't shipped this yet — the local setup is sufficient for my use case — but it's" (trailing sentence)
TO: "I haven't shipped this yet — the local setup is sufficient for my use case."
REASON: Completeness; the original sentence was truncated.

---

### B) SYNTHESIS SCRIPT

If you have ever tried to automate your job search, you have probably spent more time fighting anti-scraping protections than actually finding roles. You go to a guide, it tells you to use a headless browser, rotate proxies, and move your mouse in perfect curves. And half the time, you still get blocked.

The truth is, most of those guides are leading you in the wrong direction.

The first mistake most people make is assuming they need a browser at all. Many professional networks and job platforms are just front-ends for internal JSON APIs. If you are already logged in, you can often just grab your session cookies and call those APIs directly. No headless browser, no mouse emulation, and no fragile stealth patches. You are just sending a standard request with your authentication header. It is faster, cleaner, and far less likely to trigger a block.

Now, for sites that sit behind aggressive protections like Cloudflare, you do need a browser. But even then, keep it simple. Do not use a patched headless build that screams bot. Use a real, standard browser build. Use a persistent profile so you don't look like a fresh instance with zero history. And focus on human-like behavior, like randomizing your timing, rather than complex mouse physics that rarely matter.

But the biggest piece of advice is about your behavior over time. Even a perfectly crafted request will get you flagged if you hit the same endpoint at the same second every day, or if you immediately start scraping every result in a sequence. Add jitter, cap your requests, and act like a human.

Finally, there is the CI/CD problem. How do you automate this on a schedule when your session cookies expire every few weeks? Do not try to automate the login itself. Instead, use a two-part pattern. Keep the authentication manual. When your cookies expire, use a local script to log in, grab the fresh cookies, and update your CI secrets. Then, let your automated job simply pull those credentials and run. By separating the sensitive, human-gated authentication from your scheduled scraping, you keep your setup robust, secure, and above all, reliable.

If you are tired of the cat-and-mouse game, stop fighting the tools and start understanding the architecture of the sites you are actually targeting. Check out the project code at the link below to see how I implemented this locally.
