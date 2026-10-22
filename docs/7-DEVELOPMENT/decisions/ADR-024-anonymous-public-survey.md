# ADR-024: Anonymous school feedback with public results

The school presentation needs a public, twenty-question feedback form under
`/sondaj`, with results under `/sondaj/rezultate`. This is a voluntary opinion
survey, not a graded quiz or a validated psychometric instrument.

The questionnaire `guguta-schools-2026-v1` is defined once in the backend and
served to the frontend. Questions 1–18 offer fixed choices (including abstention
or not-tried choices where relevant); 19–20 are optional, public free text.
Future substantive wording/option changes must introduce a new version rather
than silently combining different questionnaires.

Survey requests omit cookies and bypass session resolution on an exact route
allowlist. Stored rows have a random submission UUID for retry deduplication,
the questionnaire version, a date (not an exact timestamp), and the answers.
They have no user/account foreign keys, email, school, IP address, user agent,
session identifiers, or browser fingerprints. Technical web-server logs remain
separate from questionnaire data. Browser session storage retains an unfinished
form in its tab and removes its answers after confirmed submission.

A signed, expiring submission token, same-origin POST header/origin check,
strict answer validation, and an atomic unique key protect submission integrity.
Retries do not add votes or alter a stored response. This does not establish one
response per person; a shared device can intentionally start another response.

Raw database rows are unavailable to API/worker roles. Restricted SECURITY
DEFINER functions permit insertion, aggregate counts, and independent lists of
public comments. Results never expose UUIDs, dates, complete individual response
profiles, or cross-filtering. Rating means exclude not-tried answers; multiple
choice percentages use completed questionnaires and can sum above 100%.

All comments are public, as requested, without sentiment filtering. Before
submission the UI explains publication and asks pupils not to include personal
details. Obvious email/telephone strings are rejected for correction; this is
not a guarantee that every identifying phrase can be detected. Comments are
rendered as text; CSV exports neutralize formula prefixes. No AI provider or
third-party form/analytics service receives survey responses.

Migration 0025_survey only adds the isolated survey table/functions. Its unique
revision ID avoids colliding with the pending PlayQuiz migration on a separate
branch; that branch must be rebased and its migration parent updated before release.
Existing notebooks,
users, materials, chat, voice and PlayQuiz are unchanged.
