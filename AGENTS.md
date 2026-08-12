# Agent Instructions

<!-- zaxy-memory-activation:start -->
## Zaxy Memory Activation

Before roadmap, implementation, release, review, resume, or high-context work:
- Start Codex through Zaxy when opening a new session: `zaxy activate codex --eventloom-path /home/cheapseatsecon/Projects/Personal/slackarcaide/.eventloom --session-id slackarcaide-default --current-task '<task>' --workspace-root /home/cheapseatsecon/Projects/Personal/slackarcaide --launch`.
- After `/resume`, Codex update, or MCP/tool reload, record the boundary: `zaxy hook-event resume --eventloom-path /home/cheapseatsecon/Projects/Personal/slackarcaide/.eventloom --session-id slackarcaide-default --source codex --summary "<task>"`.
- If Zaxy MCP tools are unavailable, run CLI checkout before substantial work: `zaxy memory checkout "<task>" --eventloom-path /home/cheapseatsecon/Projects/Personal/slackarcaide/.eventloom --session-id slackarcaide-default`.
- If no fresh activation packet or cited checkout is available, treat memory as degraded and pause substantial work until checkout succeeds.
- Do not rely only on ordinary Codex summaries when Zaxy activation is missing.
<!-- zaxy-memory-activation:end -->
