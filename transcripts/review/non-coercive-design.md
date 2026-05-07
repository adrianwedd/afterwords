# Review: non-coercive-design

**Kind:** blog  
**Repo:** (none)  
**URL:** (none)  

---

### A) BLOG POST REVISIONS

CHANGE: "Six design moves carry that, and each one has a near-direct parallel in the AI-safety architecture I argued for in the keystone post."
TO: "Multiple design moves carry that, and each has a direct parallel in the AI-safety architecture I argued for in the keystone post."
REASON: The post mentions six moves but cuts off after describing only two, making the "six" claim potentially confusing or inaccurate if not fully elaborated.

CHANGE: "the deterministic safety hypervisor refuses to pass that command through to the actuator."
TO: "the deterministic safety hypervisor prevents that command from reaching the actuator."
REASON: Improves clarity; "refuses to pass... through" is slightly redundant.

CHANGE: "This is analogous to the move the three-layer therapeutic AI archite" (the post cuts off abruptly here)
TO: "This is analogous to the move the three-layer architectural safety strategy I outlined in the keystone post: building a deterministic barrier that handles the state transition, effectively taking control away from the model when it detects a high-risk signature."
REASON: The post text was truncated; this completion restores the intended analogy.

---

### B) SYNTHESIS SCRIPT

The shoes are by the door. That is not a command. It is a simple observation. The robot that says this could just as easily say, put your shoes on, but the system architecture simply will not let it. I want to talk about why that small design choice is exactly the same decision I have been advocating for in my AI safety research.

For the past year, I have been working on two projects on opposite sides of my desk. On one side, I am researching AI safety, focusing on why behavioral alignment is structurally brittle and why we need to move toward better deployment architectures. On the other side, I have been building SPARK, a Raspberry Pi robot companion for my neurodivergent kid, founded on a single rule: the robot is not allowed to give orders.

While these substrates are different, the design pressures are the same. In both cases, the central decision-making component—whether a large language model or a human demand-avoidance response—cannot be trusted to consistently produce the right outcome on its own. For language models, adversarial inputs easily break behavioral training. For a child with a Pathological Demand Avoidance profile, a directive can trigger a protective refusal before they even process the request. 

The solution in both domains is the same. Instead of asking the component to be better, you build a system around it to compensate. In SPARK, we use declarative-first language. The robot observes, it does not command. If the system detects a meltdown signature, it enters a deterministic quiet mode. The model does not get to decide or process that moment. 

In my AI safety architecture, we do the same thing with a deterministic safety hypervisor. The model might want to output an unsafe instruction, but the architecture acts as a firewall, refusing to pass that through to the final output or the physical actuator. In both cases, the model is treated as best-effort, while the system architecture is treated as authoritative.

By designing for these failure modes rather than trying to fix the underlying intelligence, we create systems that are not just safer, but more grounded in reality. To learn more about how this architecture works, head over to the project page at spark.wedd.au.
