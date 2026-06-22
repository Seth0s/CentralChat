# CentralChat — Sidebar Fields Reference

> Last updated: 2026-06-22

## SOLO mode

| Section | Field | Source | Description |
|---------|-------|--------|-------------|
| **Title** | Session title | Local model | First user message or default |
| **Agent** | Active agent | `m.activeAgentName` | From `~/.config/central/agents/` |
| **Skills** | Active skills | `m.sessionSkillNames` | From `~/.config/central/skills/` |
| **Model** | Model name | `m.activeModelDisplay()` | Provider model (e.g. `openai/gpt-4o-mini`) |
| | Provider + tier | SOLO status | Kind (openrouter, ollama, etc.) |
| **Usage** | Context bar | `m.contextPct` | Context window usage % |
| | Tokens | `m.tokensIn + m.tokensOut` | Current turn |
| | Turn time | `m.lastTurnDuration` | Last turn duration |
| | Session time | `m.sessionElapsed()` | Total session time |
| | Cost | `m.usageTotalCost` | Estimated cost (provider-dependent) |
| **Runtime** | CPU / MEM | `soloStatus.Collect()` | Via gopsutil, refreshed every 3s |
| | Active tools | `runtimeSnap.ActiveTools` | Tools currently executing |
| | Recent tools | `runtimeSnap.RecentTools` | Last completed tools (✓/✗) |
| | Background commands | `runtimeSnap.Background` | Commands running in background |
| | Provider status | `soloAgent.Provider` | Kind + model, or "not configured" |
| | Workspace | `m.runtime.WorkspacePath` | Local working directory |
| | Sessions | `solo.ListSessions()` | Count of local sessions |
| **Badges** | online | Always true in SOLO | Connector status |
| | version | Version string | Build version |

## TEAM mode

| Section | Field | Source | Description |
|---------|-------|--------|-------------|
| **Title** | Session title | VPS session | From server |
| **Agent** | Active agent | `m.activeAgentName` | From team catalog |
| **Skills** | Active skills | `m.sessionSkillNames` | From team skills |
| **Model** | Model name | `m.activeModelDisplay()` | Server-side model |
| | Provider + tier + routing | VPS preferences | Inference destination, auto tier, routing strategy |
| | Temperature + effort + thinking | VPS preferences | Model parameters |
| **Usage** | Context bar | `m.contextPct` | Context window usage % |
| | Tokens | `m.tokensIn + m.tokensOut` | Current turn |
| | Turn time | `m.lastTurnDuration` | Last turn duration |
| | Session time | `m.sessionElapsed()` | Total session time |
| | Cost | `m.usageTotalCost` | From provider billing |
| **Workspace** | Path + branch | VPS connector | Git branch + dirty count |
| **Badges** | online | `m.connectorOnline` | Connector health |
| | pending | `m.pendingCount` | Pending approvals |
| | version | Version string | Build version |
| **Reasoning** | Thinking tokens | `m.thinking` | Count + toggle (Ctrl+T) |

## Key differences

| Feature | SOLO | TEAM |
|---------|------|------|
| Runtime metrics (CPU/MEM) | ✅ Always visible | ❌ |
| Active/recent tools | ✅ | ❌ |
| Background commands | ✅ | ❌ |
| Provider status | ✅ Local provider | ❌ (in model section) |
| Workspace path | ✅ Local directory | ✅ Git branch + remote |
| Sessions count | ✅ Local SQLite | ❌ (in Hub) |
| Pending approvals | ❌ | ✅ |
| Connector status | Always "online" | VPS health check |
| Model parameters | ❌ | ✅ temp, effort, thinking, etc. |
| Git branch + dirty count | ❌ | ✅ |
