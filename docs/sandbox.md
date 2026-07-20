# Sandbox boundary

Sandbox records bind a task, repository, immutable base, workspace, evidence directory, expiry, and
resource policy. The local Docker command uses a non-root UID, read-only root, isolated workspace,
network denial, dropped capabilities, `no-new-privileges`, CPU/RAM/PID limits, and no Docker socket.
CI executes the container security contract. The Fly adapter is a typed, mocked-by-default boundary;
live Fly execution requires an owner-triggered credentialed test.

Filesystem resolution rejects absolute paths, traversal, case-insensitive protected paths, escaping
symlinks, and hard-linked files. Network policy denies by default and rejects private, loopback,
link-local, reserved, multicast, and metadata addresses after resolution.
