# Typed tools

Tool registration binds a unique name/version to a Pydantic input schema, risk, permission, approval
requirement, network requirement, and executor. Model output is only a proposal; the registry checks
every boundary before calling an executor and hashes both validated input and output evidence.

Commands use an executable plus argument vector and never a shell. The runner validates executable,
working directory, environment, network need, timeout, cancellation, output size, and redaction. It
terminates the process group on timeout. Structured patches validate path, base hash, file/byte limits,
protected paths, binary content, and all contexts before applying. Failures restore original content.
