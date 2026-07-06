# Sidebar Panel V2 + Inference Params — Implementation Plan

> **For Hermes:** Execute task-by-task. Each task is self-contained. Build + test after each Go task.

**Goal:** Redesign the right sidebar panel (renderRightPanel) with #232 background, English labels, provider-aware params, reasoning moved to chat, plus 4 new slash commands to change inference params at runtime.

**Architecture:** New `renderRightPanelV2()` replaces the current 140-line function. Helper functions `panelSection()`, `panelRow()` encapsulate label+value rendering with consistent backgrounds. Four new slash commands (`/tier`, `/route`, `/temp`, `/effort`) follow the `/thinking` pattern — fire-and-forget state mutation. Backend gets `provider_routing` in the preferences snapshot.

**Tech Stack:** Go + Bubble Tea + Lipgloss (CLI), Python/FastAPI (backend)

---

## Phase 0 — Backend: expose provider_routing

### Task 0.1: Add provider_routing to sidebar refresh snapshot

**Objective:** The CLI `sidebarRefreshMsg` needs the `provider_routing` preference to display it in the panel.

**Files:**
- Modify: `CentralChat_Backend/app/inference.py` — `_ui_inference_snapshot()`

**Step 1: Add provider_routing to the snapshot dict**

In `_ui_inference_snapshot()`, add after `auto_tier`:

```python
"provider_routing": str(prefs.get("provider_routing") or ""),
```

**Step 2: Verify import**

```bash
cd /home/lucas/Workplace/Projects/CentralChat/vhosts/CentralChat_Backend
python -c "from app.inference import _ui_inference_snapshot; s = _ui_inference_snapshot(); print('provider_routing' in s)"
```

Expected: `True`

---

## Phase 1 — Model struct additions

### Task 1.1: Add providerRouting field to model and sidebarRefreshMsg

**Objective:** Store the provider_routing preference received from backend.

**Files:**
- Modify: `internal/ui/app.go` — `sidebarRefreshMsg` struct, `model` struct, refresh handler

**Step 1: Add to sidebarRefreshMsg**

```go
type sidebarRefreshMsg struct {
    // ... existing fields ...
    ProviderRouting string  // openrouter routing: cheapest|fastest|throughput
}
```

**Step 2: Parse in refreshSidebarCmd**

In the func that reads preferences from `GetPreferences()`, add after `AutoTier`:
```go
if pr, ok := prRaw["provider_routing"].(string); ok {
    out.ProviderRouting = pr
}
```

**Step 3: Add to model struct**

```go
type model struct {
    // ... existing fields ...
    providerRouting string  // OpenRouter routing strategy
}
```

**Step 4: Store in sidebarRefreshMsg handler**

```go
case sidebarRefreshMsg:
    // ... existing assignments ...
    if msg.ProviderRouting != "" {
        m.providerRouting = msg.ProviderRouting
    }
```

**Step 5: Build + test**

```bash
go build -o ~/.local/bin/central ./cmd/central/
go test ./internal/ui/
```

---

## Phase 2 — New slash commands

### Task 2.1: Add /tier command

**Objective:** Change auto_tier at runtime, persistable via /prefs.

**Files:**
- Modify: `internal/ui/slash_palette.go` — add to catalog
- Modify: `internal/ui/app.go` — handleSlash case

**Step 1: Add to slashCatalog**

```go
{Name: "/tier", Description: "Auto model tier: economy|balanced|premium"},
```

**Step 2: Add handler in handleSlash**

```go
case "/tier":
    if len(fields) < 2 {
        m.messages = append(m.messages, chatLine{role: "system", content: "Usage: /tier economy|balanced|premium. Current: " + m.autoTier})
    } else {
        val := strings.ToLower(fields[1])
        if val == "economy" || val == "balanced" || val == "premium" {
            m.autoTier = val
            m.messages = append(m.messages, chatLine{role: "system", content: "Auto tier set to " + val})
        } else {
            m.messages = append(m.messages, chatLine{role: "system", content: "Invalid tier. Use: economy, balanced, premium"})
        }
    }
```

**Step 3: Build + test**

### Task 2.2: Add /route command

**Objective:** Change provider_routing at runtime.

**Files:** Same as above.

**Step 1: Add to slashCatalog**

```go
{Name: "/route", Description: "OpenRouter routing: cheapest|fastest|throughput"},
```

**Step 2: Add handler**

```go
case "/route":
    if len(fields) < 2 {
        m.messages = append(m.messages, chatLine{role: "system", content: "Usage: /route cheapest|fastest|throughput. Current: " + m.providerRouting})
    } else {
        val := strings.ToLower(fields[1])
        if val == "cheapest" || val == "fastest" || val == "throughput" {
            m.providerRouting = val
            m.messages = append(m.messages, chatLine{role: "system", content: "Provider routing set to " + val})
        } else {
            m.messages = append(m.messages, chatLine{role: "system", content: "Invalid route. Use: cheapest, fastest, throughput"})
        }
    }
```

**Step 3: Build + test**

### Task 2.3: Add /temp command

**Objective:** Change temperature at runtime.

**Step 1: Add to slashCatalog**

```go
{Name: "/temp", Description: "Temperature 0.0–2.0"},
```

**Step 2: Add handler**

```go
case "/temp":
    if len(fields) < 2 {
        m.messages = append(m.messages, chatLine{role: "system", content: fmt.Sprintf("Usage: /temp 0.0-2.0. Current: %.1f", m.temperature)})
    } else {
        if t, err := strconv.ParseFloat(fields[1], 64); err == nil && t >= 0 && t <= 2.0 {
            m.temperature = t
            m.messages = append(m.messages, chatLine{role: "system", content: fmt.Sprintf("Temperature set to %.1f", t)})
        } else {
            m.messages = append(m.messages, chatLine{role: "system", content: "Invalid. Use a number between 0.0 and 2.0"})
        }
    }
```

Need to add `"strconv"` import if not present.

**Step 3: Build + test**

### Task 2.4: Add /effort command

**Objective:** Change reasoning effort at runtime (OpenRouter).

**Step 1: Add to slashCatalog**

```go
{Name: "/effort", Description: "Reasoning effort: low|medium|high"},
```

**Step 2: Add handler**

```go
case "/effort":
    if len(fields) < 2 {
        m.messages = append(m.messages, chatLine{role: "system", content: "Usage: /effort low|medium|high. Current: " + m.effort})
    } else {
        val := strings.ToLower(fields[1])
        if val == "low" || val == "medium" || val == "high" {
            m.effort = val
            m.messages = append(m.messages, chatLine{role: "system", content: "Effort set to " + val})
        } else {
            m.messages = append(m.messages, chatLine{role: "system", content: "Invalid effort. Use: low, medium, high"})
        }
    }
```

**Step 3: Build + test**

### Task 2.5: Add /params command

**Objective:** Display all current inference params.

**Step 1: Add to slashCatalog**

```go
{Name: "/params", Description: "Show current inference params"},
```

**Step 2: Add handler**

```go
case "/params":
    var lines []string
    lines = append(lines, "Inference Parameters:")
    if m.autoTier != "" {
        lines = append(lines, "  tier    "+m.autoTier)
    }
    if m.providerRouting != "" {
        lines = append(lines, "  route   "+m.providerRouting)
    }
    if m.temperature > 0 {
        lines = append(lines, fmt.Sprintf("  temp    %.1f", m.temperature))
    }
    if m.effort != "" {
        lines = append(lines, "  effort  "+m.effort)
    }
    lines = append(lines, "  tools   "+fmt.Sprintf("%d", len(m.sessionToolNames)))
    lines = append(lines, "  skills  "+fmt.Sprintf("%d", len(m.sessionSkillNames)))
    if m.activeAgentName != "" {
        lines = append(lines, "  agent   "+m.activeAgentName)
    }
    lines = append(lines, "Save with /prefs for new sessions.")
    m.messages = append(m.messages, chatLine{role: "system", content: strings.Join(lines, "\n")})
```

**Step 3: Build + test**

### Task 2.6: Update /prefs to include new params

**Objective:** Save tier, route, temp, effort via /prefs.

**Step 1: Extend the /prefs handler**

Add to the `prefs` map in the `/prefs` handler:
```go
if m.autoTier != "" {
    prefs["auto_tier"] = m.autoTier
}
if m.providerRouting != "" {
    prefs["provider_routing"] = m.providerRouting
}
if m.temperature > 0 {
    prefs["temperature"] = m.temperature
}
if m.effort != "" {
    prefs["effort"] = m.effort
}
```

**Step 2: Build + test**

---

## Phase 3 — Sidebar panel V2

### Task 3.1: Create panel helper functions

**Objective:** Extract reusable rendering primitives with consistent #232 background.

**Files:**
- Modify: `internal/ui/session_layout.go`

**Step 1: Add helpers before renderRightPanel**

```go
const panelBg = "#232"

func panelAccent() lipgloss.Style {
    return Theme().StyleAccent.Copy().Background(lipgloss.Color(panelBg))
}

func panelLabel() lipgloss.Style {
    return Theme().StyleLabel.Copy().Background(lipgloss.Color(panelBg))
}

func panelDim() lipgloss.Style {
    return Theme().StyleDim.Copy().Background(lipgloss.Color(panelBg))
}

func panelSeparator() lipgloss.Style {
    return Theme().StyleSeparator.Copy().Background(lipgloss.Color(panelBg))
}

// panelRow renders "LABEL  value" with consistent backgrounds.
func panelRow(label, value string) string {
    return panelLabel().Render(label) + "  " + panelDim().Render(value)
}

// panelSection renders a section header with separator.
func panelSection(lines []string, title string) []string {
    lines = append(lines, "")
    lines = append(lines, panelSeparator().Render(strings.Repeat("─", 28))+" "+panelLabel().Render(title))
    return lines
}
```

**Step 2: Build**

### Task 3.2: Write renderRightPanelV2

**Objective:** Complete panel function with all sections.

**Files:**
- Modify: `internal/ui/session_layout.go` — new function `renderRightPanelV2`

**Step 1: Implement the full function**

```go
func (m model) renderRightPanelV2(contentH int) string {
    pw := m.rightPanelWidth()
    _ = contentInset(sessionInnerWidth(m.width)) // gutter preserved for API compat

    title := trim(m.displayTurnTitle(), pw-4)
    if title == "" {
        title = "Session"
    }
    provider := extractProvider(m.activeModelDisplay())

    var lines []string

    // Title
    lines = append(lines, "")
    lines = append(lines, panelAccent().Render(title))
    lines = append(lines, panelSeparator().Render(strings.Repeat("─", pw)))

    // Agent
    if m.activeAgentName != "" {
        lines = append(lines, panelRow("Agent", m.activeAgentName))
    }

    // Skills
    if len(m.sessionSkillNames) > 0 {
        skills := strings.Join(m.sessionSkillNames, ", ")
        lines = append(lines, panelRow("Skills", trim(skills, pw-10)))
    }

    lines = panelSection(lines, "Model")

    // Model name
    modelDisplay := m.activeModelDisplay()
    if modelDisplay == "" {
        modelDisplay = "(none)"
    }
    lines = append(lines, panelAccent().Bold(true).Render(trim(modelDisplay, pw-2)))

    // Provider + tier or routing
    var metaParts []string
    if provider != "" {
        metaParts = append(metaParts, provider)
    }
    // Show tier only if no manual model selected (auto-tier active)
    if m.autoTier != "" && m.sessionModelOverride == "" {
        metaParts = append(metaParts, "tier "+m.autoTier)
    }
    // Show routing only for OpenRouter
    if m.providerRouting != "" && strings.EqualFold(provider, "openrouter") {
        metaParts = append(metaParts, "route "+m.providerRouting)
    }
    if len(metaParts) > 0 {
        lines = append(lines, panelDim().Render(strings.Join(metaParts, " · ")))
    }

    // Params
    var paramParts []string
    if m.temperature > 0 {
        paramParts = append(paramParts, fmt.Sprintf("temp %.1f", m.temperature))
    }
    if m.effort != "" {
        paramParts = append(paramParts, "effort "+m.effort)
    }
    if len(paramParts) > 0 {
        lines = append(lines, panelDim().Render(strings.Join(paramParts, " · ")))
    }

    lines = panelSection(lines, "Usage")

    // Context
    ctxBarW := 10
    ctxLine := panelLabel().Render("Context") + "  " + renderContextBar(m.contextPct, ctxBarW)
    ctxLine += "  " + panelDim().Render(fmt.Sprintf("%d%%", m.contextPct))
    lines = append(lines, ctxLine)

    tokenStr := formatTokensK(m.tokensIn+m.tokensOut) + " / " + formatTokensK(m.contextLimitTokens())
    lines = append(lines, panelDim().Render("  "+tokenStr+" tokens"))

    // Timing
    lines = append(lines, panelRow("Turn", renderDuration(m.lastTurnDuration)))
    lines = append(lines, panelRow("Session", renderDuration(m.sessionElapsed())))

    // Cost
    costStr := formatCost(m.usageTotalCost)
    lines = append(lines, panelRow("Cost", costStr))

    // Workspace
    if m.workspace != "" {
        lines = append(lines, "")
        wsLine := formatWorkspacePath(m.workspace, m.branch)
        lines = append(lines, panelDim().Render(trim(wsLine, pw-2)))
    }

    // Badges
    var badges []string
    if m.connectorOnline {
        badges = append(badges, panelAccent().Render("online"))
    }
    if m.pendingCount > 0 {
        badges = append(badges, fmt.Sprintf("%d pending", m.pendingCount))
    }
    badges = append(badges, "v"+version.Version)
    if len(badges) > 0 {
        lines = append(lines, panelDim().Render(strings.Join(badges, " · ")))
    }

    // Reasoning indicator
    if m.reasoningPanel != "hidden" {
        lines = append(lines, "")
        tokCount := len(strings.Fields(m.thinking))
        label := "Reasoning"
        if m.reasoningPanel == "open" {
            label = "Reasoning  ▼"
        } else {
            label = "Reasoning  ▸"
        }
        lines = append(lines, panelRow(label, fmt.Sprintf("%d tok  Ctrl+T", tokCount)))
    }

    // Fit to height
    if len(lines) > contentH {
        lines = lines[:contentH]
    }
    for len(lines) < contentH {
        lines = append(lines, "")
    }

    return renderPlainColumn(strings.Join(lines, "\n"), pw, contentH, 0)
}
```

**Step 2: Wire up — replace renderRightPanel call**

In `renderSessionBody`, change:
```go
sidebar := m.renderRightPanel(bodyH)
```
to:
```go
sidebar := m.renderRightPanelV2(bodyH)
```

**Step 3: Build + test**

```bash
go build -o ~/.local/bin/central ./cmd/central/
go test ./internal/ui/
```

---

## Phase 4 — Polish

### Task 4.1: Translate remaining Portuguese in session_empty_state.go

**Objective:** `"(nenhuma skill publicada)"` → `"(no published skills)"`

**Files:**
- Modify: `internal/ui/session_empty_state.go:128`

**Step 1:** Replace the string.

**Step 2:** Build.

### Task 4.2: Translate remaining Portuguese in session_layout.go sidebar

**Objective:** Verify no Portuguese remains in `renderRightPanel`. The old function stays for reference until V2 is stable.

**Step 1:** Check `renderRightPanel` for PT strings — all removed in V2.

### Task 4.3: Remove reasoning content from chat column (future)

**Objective:** Move reasoning inline into chat as a collapsible block below assistant messages.

**Note:** This is a larger change affecting `session_chat_scroll.go`. Defer to a separate plan — the panel now only shows an indicator.

---

## Execution Order

```
Phase 0  → Task 0.1 (backend snapshot)
Phase 1  → Task 1.1 (model fields)
Phase 2  → Tasks 2.1–2.6 (slash commands)
Phase 3  → Tasks 3.1–3.2 (panel V2)
Phase 4  → Tasks 4.1–4.2 (polish)
```

Each phase builds on the previous. Phase 2 can be done before Phase 3 safely.

---

## Verification Checklist

- [ ] `/tier economy` — message confirms change
- [ ] `/route fastest` — message confirms change
- [ ] `/temp 0.7` — message confirms change
- [ ] `/effort high` — message confirms change
- [ ] `/params` — shows all current values
- [ ] `/prefs` — saves new params, message confirms
- [ ] Panel shows provider + tier/route on separate line from model
- [ ] Panel shows temp + effort when non-default
- [ ] Panel background is #232 throughout
- [ ] All labels in English
- [ ] Reasoning shows token count, not raw text
- [ ] Build passes, tests pass
- [ ] Crash test: open/close panel with Ctrl+B
