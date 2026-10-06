# ADR-017: Educational tutoring with accurate source attribution

- **Status**: Accepted
- **Date**: 2026-10-06
- **Related**: ADR-008, ADR-014, ADR-015, ADR-016
- **Supersedes**: ADR-008's blanket prohibition on general knowledge in chat.

## Context

A pupil asked how to express an exact hour in English. The selected page
contained practical clock exercises but no grammar lesson. Generation and
review both refused because the required language rule was not in the page.
More retrieval tools cannot repair a policy that prohibits normal teaching.

## Decision

Guguță acts as an educational tutor as well as a document research assistant.
It may use general knowledge for translations, grammar, vocabulary,
definitions, explanations, new examples, calculations and solution methods,
even when the applicable rule is absent from the selected page or no material
has been retrieved. This is useful for studying the notebook's subjects;
it does not add unrestricted internet or filesystem tools.

Claims about particular documents, exercise statements, quotations, page
contents or visible objects still require original authorized evidence.
The tutor must not invent missing exercise data. It can explain a general
method while requesting the data needed for a particular solution. An explicit
request to answer exclusively from materials still requires source support.

Source-supported facts and general teaching are placed in separate paragraphs.
The existing `paragraphs` / `source_ids` contract is unchanged: general teaching
uses an empty `source_ids` list, including when unrelated fragments were found.
Source IDs remain restricted to current authorized fragments. A document
citation must not imply that an absent language rule came from that document.
Where the distinction matters, the answer briefly identifies the source fact
and the tutor's explanation; simple study answers need no repetitive warning.

Both generation and review follow this policy. Review checks the educational
answer's correctness and attribution rather than removing it merely because
the explanation is absent from the page. The retrieval agent can stop without
tool calls for source-independent teaching questions. Original page inspection
remains required for questions that depend on an actual figure or exercise.

## Validation and limits

Contract tests cover general teaching with zero fragments, uncited translation
with irrelevant page context and review enabled, mixed sourced/general
paragraphs, and persisted HTTP/SSE answers without fabricated citations.
Existing unauthorized-source, revision and original-image tests remain valid.
Live evaluations check educational usefulness as well as source-specific
abstention and visual counting. No example answer is embedded in runtime code.

Source-ID validation cannot prove factual support or the correctness of general
knowledge. These remain model capabilities evaluated with representative study
questions. No model change, schema migration or frontend API change is required.
