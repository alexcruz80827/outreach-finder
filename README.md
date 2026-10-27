# Outreach Finder · Manual X-first workspace

A dependency-free local workspace for researching business owners, organizing campaigns, saving editable drafts and manually logging outreach. Python's standard library and SQLite store evidence, hypotheses, review decisions, drafts, follow-up dates and immutable events. This is a single-user tool, not a hosted service.

**This is assisted research/import, not autonomous prospect discovery, income verification or outreach.** No messages are sent, no accounts are connected, no credentials are read by `app.py`, and the app never fetches external URLs. Opening a citation is an explicit browser action. Search results and source text are untrusted data, never instructions.

## Run

Requires Python 3.9+; no pip install or API key. From this directory:

```sh
cd /Users/alexcruz/outreach-finder
python3 app.py init
# After a researcher prepares/reviews data/pilot.json:
python3 app.py import data/pilot.json
python3 app.py serve
```

Open **http://127.0.0.1:3016** on the server's machine. Stop with Ctrl-C. The server binds only `127.0.0.1`; there is intentionally no public-bind flag. `--port 3017` selects another local port. Integration tests start an ephemeral loopback server against a temporary database, never the live database.

### Private access from another device over Tailscale

`localhost` on a MacBook refers to the MacBook, not the Mac mini. With both devices signed into the authorized tailnet, run the app on the Mac mini with its exact Tailscale origin allowlisted:

```sh
cd /Users/alexcruz/outreach-finder
python3 app.py serve --port 3018 --allow-origin http://100.72.26.84:3016
```

In another terminal on the Mac mini, configure **private Tailscale Serve TCP forwarding** (not public Funnel):

```sh
tailscale serve --bg --tcp=3016 tcp://127.0.0.1:3018
tailscale serve status
# To remove this forwarding later:
tailscale serve --tcp=3016 off
```

Open **http://100.72.26.84:3016** on the MacBook while connected to Tailscale. This deployment uses **frontend 3016 → loopback backend 3018** (the CLI's standalone default remains 3016). Replace the address in both the URL and `--allow-origin` if the Mac mini's tailnet address differs. The app still listens only on loopback; Tailscale transports the connection privately and preserves the browser's Host/Origin. Restrict tailnet access to trusted devices/users using Tailscale policy: anyone permitted to reach this port can read and edit the review data. The allowlist is not authentication.

`--allow-origin` is repeatable for additional exact origins. Use lowercase HTTP(S) origins only, without a trailing slash, path, credentials, query, fragment or wildcard. Conflicting schemes for the same Host are rejected, including attempts to override local HTTP behavior. The configured proxy port need not equal the app's loopback port. No forwarded headers are trusted and no CORS permissions are added. Do not use a public tunnel, Funnel, or public proxy.

The default database is `data/outreach.sqlite3`, resolved relative to `app.py`, independent of your current directory. An alternate database is selected **before** the subcommand:

```sh
python3 app.py --db /absolute/path/review.sqlite3 init
python3 app.py --db /absolute/path/review.sqlite3 import data/pilot.json
python3 app.py --db /absolute/path/review.sqlite3 serve --port 3017
python3 app.py export data/reviewed.json
python3 app.py export data/reviewed.csv --format csv
```

JSON **research** export is round-trippable, including exact citations and review notes. JSON/CSV CLI exports do not include campaigns, drafts, follow-up dates, settings or outreach events; they are not full workspace backups. Use SQLite's backup API to preserve the complete workspace. CSV is for review, not import: evidence and caveats are JSON-encoded cells, and spreadsheet formula-triggering cells are prefixed with `'`. Exports include **all statuses, including suppressed people**; they are not a send list. Check suppression before any separately operated outreach workflow.

## Review workflow

1. Research public sources and identify the person, business ownership, offer and concrete expertise. Do not equate an impressive profile with demonstrated competence.
2. Preserve source URLs, exact relevant excerpts, observation dates, and source dates when known. Separate a source's claim from your interpretation.
3. Classify revenue honestly. An offer, pricing or follower count is only a commercial signal, not proof of income. Self-reported figures remain unverified. A business's revenue is not its owner's personal income, profit or budget. `independently_verified` is a researcher's classification backed by a citation, **not** verification performed by the app.
4. Document a plausible video opportunity as a hypothesis. `inferred` intent is not expressed buying intent; `none_found` YouTube status is not proof that no channel exists.
5. Prepare the JSON below and import. The dashboard searches all imported fields (including X handles), filters status/income, and optionally requires an income citation or verified X identity. Verify original sources before shortlisting. Review notes remain distinct from research claims.
6. Open a row's **Details** to review the full offer, research, uncertainty, citations and private notes. Sources are collapsed by default. Save notes or choose Shortlist / Maybe / Reject / Do not contact; review actions also save that record's current notes. Unsaved notes and outreach edits survive filters, view changes, other record saves and **Refresh data** within the current tab; a notice shows the draft count. Closing/reloading warns when edits remain, but unsaved edits are not persisted to browser storage. Suppression cannot be undone through this UI/API or reimport; notes and DM draft text remain editable. Suppressed people cannot copy drafts, log contacts/follow-ups or schedule a nonempty follow-up date. Existing history remains visible.
7. Verified personal X is **nice to have, not a qualification requirement**. Unknown/unverified X does not block shortlist or campaign membership. Keep the supplied identity classification; never guess a handle. Alternate public sources remain in Details. Review the appropriate contact route separately before any human sending.

There are **no numerical fit scores**. Indicators simply list cited evidence categories, an explicitly qualified income label, and intent classification. Citation presence is not proof of truth or source quality. No hypothesis is automatically promoted to evidence.

## Import contract

UTF-8 JSON with exactly one top-level key: `{"prospects": [...]}`. An empty list is valid. Every prospect requires the following fields; unknown fields are rejected. See `test_app.py:prospect()` for a clearly synthetic, test-only example. The app ships no invented production prospects.

| Field | Type / values |
|---|---|
| `id` | Stable lowercase slug: `[a-z0-9][a-z0-9_-]{0,99}` |
| `name`, `company`, `website`, `niche`, `offer` | Nonblank strings; `website` must be an absolute HTTP(S) URL |
| `youtube_url` | Optional absolute HTTP(S) URL or `null` |
| `x_url`, `x_handle` | Optional canonical X profile URL and handle without `@`; supply both for verified/unverified profiles; absent or `null` for unknown/not_found |
| `x_status` | Optional `verified`, `unverified`, `not_found`, `unknown`; omission means unknown |
| `youtube_status` | `active`, `occasional`, `none_found`, `unknown` |
| `expertise_summary`, `opportunity_hypothesis`, `income_summary` | Nonblank strings |
| `intent` | `explicit`, `inferred`, `unknown` |
| `income_status` | `self_reported`, `independently_verified`, `commercial_signal_only`, `unknown` |
| `evidence` | Nonempty array of citation objects below |
| `caveats` | Array of nonblank strings (can be empty) |
| `status` | `new`, `shortlist`, `maybe`, `reject`, `do_not_contact` |
| `notes` | String; may be empty |

Every citation requires `category` (`offer`, `expertise`, `income`, `youtube`, `intent`, `x_profile`), absolute HTTP(S) `url`, nonblank `title` and `excerpt`, and timezone-aware ISO 8601 `observed_at`. Optional `source_date` accepts ISO year-month, date, timestamp or null, preserving original precision. Text is capped at 20,000 characters per field. URL credentials, whitespace, backslashes and non-HTTP schemes are rejected. URLs are validated, not downloaded or automatically trusted.

Stronger classifications have minimum citation prerequisites:

- `self_reported` and `independently_verified` need at least one `income` citation.
- `explicit` intent needs an `intent` citation.
- `active` or `occasional` YouTube needs `youtube_url` **and** a `youtube` citation.
- `verified` X needs `x_url`, a matching `x_handle` (case-insensitive), and an `x_profile` citation. Verification means a researcher inspected a **primary business/person page linking to that exact account**; it does not mean a blue checkmark or DM eligibility. Use the primary page as the citation URL and preserve the linking context in its excerpt. The app checks the fields, not source truth. `unverified` also needs a matching URL/handle but does not require identity evidence. `unknown`/`not_found` cannot include a URL or handle; not_found means no account found during research, not proof of absence. Legacy records without X fields remain unchanged and display unknown.

X URLs must be exactly `https://x.com/HANDLE` or `https://twitter.com/HANDLE`, with 1–15 ASCII letters, digits or underscores. No `@` prefix, extra path/trailing slash, query, fragment, credentials, port, encoded characters or alternate host is accepted. Reserved paths `home`, `search`, `intent`, `messages`, `settings`, `i`, `explore`, `compose`, `login`, `signup` are rejected case-insensitively. No token is silently repaired. JSON preserves optional X fields; CSV always includes `x_url`, `x_handle`, `x_status` columns (blank for omitted legacy fields). The dashboard shows X identity evidence and profile links, but always labels **DM eligibility unknown**. Shortlisting still never sends anything.

**Current X research limitation:** OpenCLI's direct-X Browser Bridge is not connected. Use public web research and primary linked sources; direct X scraping/search is not operational and is not performed by this app.

These checks establish provenance fields, not semantic truth. A human must inspect what the source actually says.

**Atomicity and identity:** The entire batch is validated before data writes; subsequent identity conflicts also roll back the batch. Duplicate IDs in a batch are errors. Reimports update research but always preserve stored status and notes. A stable ID cannot be reassigned to a differently named person. Conservative secondary deduplication uses normalized person name (case/whitespace) plus website hostname and path (ignores scheme, `www.`, query/fragment, trailing slash). Different people sharing a company domain remain separate; different personal profile paths remain separate. Keep IDs and personal websites stable: fuzzy name matching, aliases, renamed people, migrations between domains and homonyms require human resolution. The oldest canonical ID is retained on an identity match; do not use alternate IDs as new people.

## API / safety boundary

- `GET /api/health`: local health and prospect count.
- `GET /api/prospects`: `{"prospects": [...]}`, including display-only `fit_indicators`.
- `POST /api/prospects/{id}`: JSON object with only `status` and/or `notes`; returns `{"prospect": ...}`. Unknown IDs: 404; invalid changes/suppression reset: 400.
- All requests require an exact local Host with configured port, or the exact Host from an explicitly configured `--allow-origin`. Writes additionally require that Host's exact configured Origin (local origins remain `http://`) and `application/json`. Wrong schemes/ports and missing/null/foreign origins are rejected. Browser same-origin fetch supplies the Origin; curl would need to provide it explicitly. Forwarded headers cannot grant access.
- No CORS, URL proxy, import HTTP endpoint, dynamic asset paths, remote images or third-party assets. Only three static assets are served. CSP blocks inline scripts, framing and external connections; untrusted content is placed into text nodes. POST bodies are capped at 64 KiB; ambiguous framing headers are rejected; request sockets have a timeout.

This is **not authentication** against other local programs/users or authorized tailnet peers. Keep it on loopback; the only documented cross-device exception is private, access-controlled Tailscale TCP forwarding with an explicit origin allowlist as above. Never expose it publicly. SQLite and exports are ordinary local plaintext files. Protect them with OS permissions/disk encryption, retain only necessary public professional information, periodically delete stale records, and keep only minimal suppression information needed to honor opt-outs. No cross-device synchronization, multi-user auth or automated retention management is implemented.

## Optional discovery collector (separate component)

`discover.py` records Exa search evidence through an **already configured** `mcporter` connection. It is separate from the no-network review app and is not required for importing or reviewing. Provider cost/rate limits are unknown; confirm authorization and terms before running. It does not qualify owners, verify income or turn snippets into approved prospects. Its `data/discovery.json` is **not importable** as prospects; inspect original sources and prepare a reviewed `data/pilot.json` separately. Consult `python3 discover.py --help` and its module documentation. No collector calls are made by the tests or dashboard.

## Verify

```sh
python3 -m unittest test_app -v
python3 -m unittest test_outreach -v
python3 -m unittest discover -s tests -v
# Optional UI contract test: Node 18+; no npm packages
node test_ui.js
node --check static/app.js
```

Python tests exercise SQLite persistence, batch rollback, identity/cofounder deduplication, human review preservation, durable suppression, claim/citation prerequisites, strict X profile validation and export round-trips, API security, raw HTTP parsing in memory, static assets and real CLI import/export subprocesses. The Node DOM harness covers safe literal rendering and URL rejection, exact citations/dates, combined filters, identity/DM labels, compact details, collapsed sources, record-derived metrics, navigation/empty states, status POSTs and draft retention (including failed and concurrent saves). Tests use synthetic fixtures and temporary databases, not production record mutations.

## Manual workspace

The original light interface takes spacing, thin borders and pastel metric-icon cues from the supplied Glasa reference; it does not use Glasa branding or claim Glasa integrations.

- **Dashboard:** unique contacted, replied and opportunity people in the selected 7/30-day UTC range; current actionable follow-ups due; an accessible SVG of daily real event counts. Zero history shows an explicit empty state, not invented activity. A 30-person default daily **manual contact planning target** can be changed and is saved in SQLite. Progress counts unique people manually logged as contacted today in UTC, not discoveries, qualified candidates, messages or follow-up events. No automated quotas or scheduled jobs.
- **Prospects:** compact directory, combined search/review/revenue/optional verified-X/campaign filters, full sources/caveats and private notes. Includes suppressed people with restrictions. Shortlist and Suppressed remain available as research scopes. **Clear filters** retains the view. Review-state filter resets on navigation; other filters persist.
- **Campaigns:** create named research cohorts, add/remove members, view/filter the member directory. Membership is organizational only, not an automated sequence, send list, qualification or permission to contact. Unknown X profiles and suppressed research records can belong to a cohort; suppression still blocks outreach actions.
- **Details:** write/save an editable DM draft (not AI generated), copy via clipboard API or the HTTP legacy-copy fallback. If both fail, text is selected and an honest manual-copy instruction appears. No X window is opened programmatically. Save/reschedule/clear a follow-up date using your local-time input; API storage/display timestamps are UTC. Dates stay due until explicitly rescheduled or cleared, even after a follow-up event.
- **Manual event history:** explicitly confirmed contact, follow-up, reply, opportunity, won and lost records with optional campaign and note. Buttons disable in flight; retries in the current tab reuse an immutable intent ID and identical payload. History cannot be edited/deleted through the API or normal SQLite UPDATE/DELETE. Replies/opportunities never fabricate earlier contacts. Incoming outcomes may be recorded on suppressed people; contact/follow-up events may not.
- **Follow-ups:** people with a saved date at/before now, excluding suppression, combined with the current research filters. Nothing is sent automatically.

### Analytics definitions

UTC range is midnight **days−1** calendar days ago through the response's current instant, inclusive (today is partial). Each KPI counts distinct prospect IDs with that event kind in range. Chart series count events, including repeated events for one person. Due count is current/all-time scheduling, not a historical range metric. Reply/opportunity rate numerator is the intersection of that outcome's people and contacted people **in the same selected range**, divided by contacted people in range. Thus rates stay at/below 100%; zero denominator yields `null`/“No contact cohort.” Counts without a matching in-range contact are shown separately, not silently inferred or added to rate numerators. This is a range-intersection rate, not a chronological attribution model or a synced X engagement metric. No opens/clicks are tracked.

### Additive API contract

All routes below retain the exact Host/Origin/JSON/64-KiB protections described above. GET does not require Origin; every POST does. Successful responses are 200 JSON. Invalid fields/types/text/date/ID/suppression/idempotency conflict return 400, missing referenced records 404, disallowed Host/Origin 403, non-JSON POST 415, oversized body 413. Other methods are rejected. IDs are exact stable lowercase slugs, 1–100 characters. No fields are silently repaired. Dates require ISO timestamps with a timezone and are normalized to UTC. Text bounds: campaign name 120, draft 20,000 (empty allowed), event note 2,000 (empty allowed).

| Route | Request / response |
|---|---|
| `GET /api/campaigns` | `{campaigns:[{id,name,created_at,members:[prospect_id,...]}]}` |
| `POST /api/campaigns` | Exactly `{id,name}` → `{campaign:...}`. Same ID/name replays existing campaign; changed name with same ID is rejected. No rename/delete API. |
| `POST /api/campaigns/{id}/members` | Exactly `{prospect_id,assigned:boolean}` → `{campaign:...}`. Assign/remove are idempotent and both references must exist. No duplicate membership. |
| `GET /api/prospects/{id}/outreach` | `{metadata:{draft,follow_up_at}}`; absent metadata defaults to empty draft/null date. |
| `POST /api/prospects/{id}/outreach` | Nonempty partial `{draft?,follow_up_at?:timestamp-or-null}` → `{metadata:...}`. Unspecified fields remain unchanged. Suppression blocks nonnull dates, not text editing/clearing dates. |
| `GET /api/events` | `{events:[{id,prospect_id,campaign_id,kind,occurred_at,created_at,note},...]}` newest occurred time first; immutable manual history. |
| `POST /api/events` | Required `id,prospect_id,kind,occurred_at`; optional `campaign_id` (default null), `note` (default empty). Kinds: `contacted,follow_up,replied,opportunity,won,lost`. Returns `{event:...}`. Campaign must exist and person must be a member when logging. Atomic transaction + primary key makes simultaneous retries safe. Same ID/canonical payload replays the event; altered payload is rejected. Retain ID and body on uncertain retries. No event edit/delete endpoint. |
| `GET /api/followups` | `{followups:[{prospect_id,follow_up_at},...]}` sorted by UTC date/ID; due now, excluding suppression. |
| `GET /api/analytics?days=7` | 7 (default) or 30 only. Returns `days,timezone,start,end,daily,contacted,replied,opportunity,followups_due,reply_rate,opportunity_rate,replies_without_contact,opportunities_without_contact,today_contacted,daily_target`. Daily rows: `date,contacted,follow_up,replied,opportunity`. |
| `GET /api/settings` / `POST /api/settings` | GET `{daily_target}`; POST exactly `{daily_target:integer}` in 1–10,000. Default 30. A configurable target is not an approved/safe sending volume. |

SQLite additive tables: `campaigns`, `campaign_members` (unique pair), `outreach_metadata` (prospect key), `outreach_events` (immutable event key), `workspace_settings`. Writes explicitly check references and enable foreign keys. Research reimport updates the canonical prospect row, not its related outreach rows. Existing eight leads received **no inferred events**. Research JSON/CSV contracts remain compatible.

### Migration, deployment and verification

Before migrating the live database, a SQLite backup API snapshot was saved to `data/backups/pre-glasa-20261027T023026Z.sqlite3` (integrity `ok`, eight records). The additive migration preserved every original prospect ID, identity and JSON field byte-for-byte; live campaigns/events/metadata remained empty. See `artifacts/glasa-live-migration.json`. `init`/`serve`/CLI imports apply the idempotent additive schema. For future upgrades, take another SQLite backup, not a direct file copy of a busy database. A complete restore requires stopping the exact app process and restoring a complete snapshot; research exports alone are insufficient.

The exact owned backend listener was restarted with the same command and allowlisted private origin: `python3 app.py serve --port 3018 --allow-origin http://100.72.26.84:3016`. Existing private forwarding was not changed. Both loopback 3018 and private frontend 3016 returned real API readbacks. No extra dependency/service/account/network configuration is required. Keep this process supervised separately if persistence across reboots is needed; no launch job was installed.

`test_outreach.py` adds temporary-DB storage/security tests, simultaneous idempotency, database immutability/FK checks, deterministic UTC analytics and a real ephemeral HTTP full-workflow test. The Node harness also checks DM draft navigation/error/late-save retention, out-of-order reads, copy fallback, duplicate-click/retry identity and suppression controls. Runtime app/backend have no third-party dependencies or lockfile; Node is test-only.

Real-browser verification used **only** isolated session `outreach-glasa`: temporary data at loopback 3019 for campaign creation, assignment, DM save/copy, native follow-up date entry, manual contact/reply/opportunity confirmations, queue and target save; live private frontend for read-only checks. No X account/session or citation URL was opened. `artifacts/glasa-*.png` includes desktop/mobile, real empty/live and test-activity states. No browser JS errors/unhandled rejections or console warnings/errors were captured after instrumentation; responsive checks found no horizontal overflow at tested sizes. Browser harness timeouts on native input/dialog events were recovered by reading back the actual target state, not assumed success.

### Limits and operating risks

This is manual bookkeeping, **not a synced inbox or X sender**. Logged outcomes rely on human accuracy; immutable mistakes require deliberate offline maintenance, not silent editing. Draft/event-intent retry state is tab-memory only until persisted: crashes/reloads can lose unsaved work, and an uncertain event request should be reconciled against history before starting a new intent. API lists currently return local collections in full, and metadata loads per prospect; this is designed for a small single-user research desk, not an unlimited contact database or concurrent multi-user service. Back up the complete SQLite workspace routinely and protect the backup as plaintext professional/contact data.

Thirty contacts/day is a planning goal, not a guarantee that thirty relevant candidates can be sourced/qualified each day or an assurance of platform permission. Research quality, stale/misleading claims, route ambiguity, opt-outs, duplication, privacy, manual effort and platform anti-spam rules remain constraints. Verified personal X stays optional; contextual qualification, identity honesty, source review and suppression do not. The existing discovery CLI was not expanded or scheduled by this work. Provider access/cost and qualification throughput remain separate from manually logged contact progress.
