# Skills runtime

The skills loader accepts only an approved repository and immutable commit. It verifies a canonical
manifest hash, every listed file hash, skill name/version frontmatter, reference confinement, and the
allowed `SKILL.md` plus `references/` surface. It never imports or executes skill scripts.

Skill text is untrusted. Known authority-changing prompt-injection patterns fail closed. Missing
required skills, hash mismatches, invalid frontmatter, unmanifested references, and path escapes stop
the workflow. Routing combines repository profile, changed paths, task type, risk, and corrective-edit
status. Receipts are immutable typed records with a canonical receipt hash.
