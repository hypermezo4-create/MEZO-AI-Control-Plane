# Operator Dashboard

The dashboard is served at `/dashboard` as a dependency-free HTML application. The shell is public so a browser can load it, but every data and control request is authenticated by the existing `x-api-key` middleware.

The API key is kept only in page memory and is cleared on reload or tab close. It is never persisted in browser storage, embedded in HTML, sent to another origin, or written to application logs. A nonce-based Content Security Policy blocks external scripts, frames, forms, and arbitrary inline execution.

The interface supports:

- task list and state inspection;
- task detail and evidence report inspection;
- alert inspection;
- cancel, approve, and reject controls using the same application service as other clients.

The dashboard has no database access, no provider credentials, no GitHub credentials, and no execution path that bypasses policy or approval checks.
