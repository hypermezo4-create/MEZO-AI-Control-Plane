# Resumable workflow

`ResumableWorkflowEngine` executes the ordered stages from receive through Draft PR preparation.
Each completed stage writes an idempotent checkpoint with its sequence, input/output hashes, prompt
version, model evidence, and tool evidence. A restarted worker resumes after the latest checkpoint.

Approval requests pause without advancing. Denial, cancellation, deadlines, repeated normalized
finding fingerprints, missing handlers, and corrective-round limits terminate deterministically.
Corrective rounds return through tests and skills before review. Draft PR preparation is unreachable
when verification raises or returns a blocking result.
