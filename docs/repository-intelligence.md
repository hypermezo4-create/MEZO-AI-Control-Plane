# Repository intelligence

Repository acquisition requires an allowlisted repository and an immutable 40-character base SHA.
Git prompts, submodule execution, hooks, and LFS smudging are disabled. Checkout validation enforces
file and byte limits and rejects symlinks that escape the isolated repository root.

The scanner discovers root and subtree rules, languages, entry-point signals, tests, documentation,
workflows, deployment files, and practical Python symbols/imports. Conflicting rules are returned as
structured conflicts. Context selection ranks task terms, rules, tests, and changed paths; removes
duplicate chunks; excludes sensitive, generated, and vendor content; respects token budgets; and
attaches repository, immutable SHA, path, line range, analyzer version, and content hash citations.

Cache keys include repository, commit, analyzer version, and configuration hash. A base change is a
cache miss and requires analysis again.
