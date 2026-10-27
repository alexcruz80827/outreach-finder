# V1 acceptance checks

## Functional
- Run whole unittest suite (app tests and tests/ discovery tests).
- Run discover.py against live Exa, persist raw source results and verify output has nonempty discovered URLs. These are unverified candidates, never qualified lead claims.
- Validate real data/pilot.json with app importer, query SQLite back and compare exact distinct count.
- Reimport same pilot, verify no duplicate identities and manual status/notes survive.
- Start loopback server on3016, HTTP GET health and prospects and compare database count.
- Browser renders real prospect names and source URLs; no script errors, filters work, status/notes update persists through reload.
- Export CSV opens as parseable rows matching distinct database count, spreadsheet formulas escaped.

## Evidence
- Check exact primary evidence at least for strongest explicit-intent candidate and revenue-supported candidate.
- No followers/pricing equated with personal income. Business revenue claims labeled self_reported unless independently verified.
- No claimed channel cadence from channel existence alone, no guest appearance treated as channel ownership.
- Show caveats, source dates and opportunity hypotheses.

## Security and scope
- Reject nonlocal Host, cross-origin writes, unknown API fields, invalid enums and malicious URL schemes.
- Do_not_contact survives reimport and no sending feature exists.
- Untrusted names/excerpts/notes are rendered as text, not HTML.
- No public listening interface, automated outreach, scheduled jobs, credential access or provider subscriptions.

## Review
Independent spec review before independent code quality/security review; fix important findings before final delivery. Browser and live HTTP checks required in addition to unit tests. Clearly report discovery coverage and any blockers.
