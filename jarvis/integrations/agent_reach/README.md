# Agent Reach integration

Optional research layer. Jarvis starts without it.

## Retrieval

`retrieve(channel, action, query)` and `research(url)` call the documented CLI:

- channels: github, youtube, web, v2ex
- actions: search, read, hot, subtitle
- `agent-reach read <url>`

Allowlist only. No arbitrary shell. Results are untrusted.

Live verification (2026-11-02): `retrieve("github", "search", "python requests")` returned `https://github.com/psf/requests`. `research("https://example.com")` returned OK.

Jina web read can 401. V2EX topic read can timeout. Optional channels are not added.
