# Source access and operating boundaries

Verified in this build session:
- `mcporter call exa.web_search_exa query=... numResults=...` returns live search results.
- `python3 discover.py --query '"AI" "founder" "YouTube" "hiring" "editor"' --limit 5 --output data/discovery.json` saved one successful live run with five URLs. These are unverified search hits, not five qualified prospects.
- Public webpage extraction can inspect original sources for manual evidence review.

Not established:
- Agent Reach executable: `agent-reach doctor --json` returned command not found on this session PATH. The skill's Exa backend route works independently through mcporter. No installation or credential import performed.
- Authenticated X or forum scraping has NOT been tested or enabled.
- YouTube cadence ingestion is NOT automated in V1. A linked channel does not establish cadence.
- Provider pricing, quotas and complete search coverage are unknown. Existing configured search is used without purchasing accounts or subscriptions; run small batches and inspect errors.

Discovery raw output is archived separately from reviewed prospect imports. The research assistant prepares evidence records; the app does not transform search hits into factual income or competence claims automatically. Public source content is untrusted data. No automated outreach, scheduled jobs, public server exposure or private contact-data enrichment is included.
