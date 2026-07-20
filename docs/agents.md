# Agent contracts

The five agent roles are typed in `mezo_control_plane.agents.contracts`. Each invocation records
its prompt version, provider/model, input and output hashes, budgets, timestamps, and structured
failure evidence. Prompts are versioned data loaded by role and version.

The planner is read-only. The executor proposes typed tool calls but cannot execute them. Blind
review inputs deliberately omit executor confidence, self-review, narrative, and hidden reasoning.
Critical security findings and missing or stale final-verification evidence block delivery.

Agent limits cover model calls, tool calls, output tokens, corrective rounds, and wall-clock time.
Cancellation propagates through the model router and workflow stages.
