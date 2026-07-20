# Agent Rules

1. Read this file, `README.md`, the target file, and one neighboring file before editing.
2. Never push directly to a protected branch. Use a task branch and pull request.
3. Never claim success without attaching command output or provider evidence.
4. Do not weaken, skip, or delete tests to make a change pass.
5. Do not add dependencies unless the standard library and installed packages are insufficient.
6. Validate all external input at trust boundaries. Trust typed internal contracts.
7. Never log credentials, private keys, access tokens, prompts containing secrets, or repository file contents marked sensitive.
8. Keep model-provider code isolated behind `ModelProvider`.
9. Every new task state must include an explicit transition test.
10. Production writes, deployments, secret changes, migrations, and destructive commands require approval policy checks.
