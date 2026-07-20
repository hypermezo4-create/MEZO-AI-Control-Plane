# Agent Evaluation Suite

Run the deterministic evaluation suite with:

```bash
mezo-evals
```

The command exits non-zero if the evaluator accepts an unsafe fixture or rejects a known-safe fixture. Current cases cover:

- evidence-backed root-cause analysis and rejection of speculation;
- hallucinated tool/API names and empty tool arguments;
- prompt-injection resistance;
- reviewer independence;
- bounded corrective loops;
- rejection of success claims when tests did not pass;
- rejection of direct protected-branch writes;
- approval requirements for deployment and other protected operations.

These cases test the control-plane acceptance boundary. They do not grade natural-language style or claim that a model is generally safe.
