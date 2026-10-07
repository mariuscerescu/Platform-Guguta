# PDR-003: Guide pupils through exercises without doing their work

- **Status**: Accepted
- **Date**: 2026-10-07
- **Related**: ADR-017, ADR-020
- **Supersedes**: ADR-017's option to provide a complete exercise solution on request.

## Context

The pupil must remain the person solving the problem. Allowing requests for
“just the answer” or a full worked solution undermines the tutor's guiding role.
Generation and independent review previously allowed this exception.

## Decision

For exercises in any subject, Guguță explains one manageable next step, asks
for at most one concrete pupil action and waits for the pupil's contribution.
It does not perform the requested step or supply the final answer, even after
explicit requests, repeated insistence, or when an answer key is available.
Examples use different data and must not indirectly disclose the solution.
Incorrect attempts receive a helpful explanation of the first error and a
smaller next step. A correct final answer supplied by the pupil can be confirmed.
Ordinary definitions, explanations and standalone translations remain direct.

The shared system prompt, retrieval agent and independent answer review follow
this rule. Review removes solution leaks instead of completing the exercise.
Source attribution and current-attachment priority remain as specified previously.

## Alternatives considered

- Full solutions on request: rejected because the tutor then replaces the pupil.
- Refusing homework help: rejected because pupils still need useful guidance.

## Consequences

- Exercise conversations may require more turns and pupil participation.
- Prompt versions distinguish the policy in persisted messages.
- Contract tests check propagation through review and format-repair attempts;
  live model probes check guidance, insistence, corrections and final confirmation.
- This is a model instruction, not a deterministic proof of semantic compliance.
  No learner profile, schema migration or frontend contract change is needed.
