# Security Policy

Report vulnerabilities privately to the repository owner. Do not open a public issue containing credentials, exploit payloads, private repository content, or customer data.

## Security boundaries

- Model output is untrusted input.
- Tool calls are proposals until validated by policy.
- Repository tokens are never sent to a model provider.
- GitHub writes must use installation-scoped credentials.
- Commands execute only in an isolated worker with resource and network limits.
- Protected paths and destructive commands require explicit approval.

## Secret handling

Secrets belong in Fly secrets or the deployment platform's secret manager. They must not appear in commits, workflow logs, exception traces, or task evidence.
