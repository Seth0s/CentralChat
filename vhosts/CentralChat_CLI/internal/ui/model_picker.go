package ui

import (
	"fmt"
	"sort"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/bubbles/textarea"
	"github.com/charmbracelet/lipgloss"
	"github.com/centralchurch/central-cli/internal/config"
)

const modelPickerPageSize = 15

type cloudModelRow struct {
	ID       string
	Label    string
	Enabled  bool
	Scope    string
	Provider string
}

type providerInfo struct {
	ID         string
	Label      string
	Configured bool
	ModelCount int
	SetupHint  string
}

type modelPickerLoadedMsg struct {
	Models          []cloudModelRow
	Providers       []providerInfo
	ActiveModelID   string
	UserDefault     string
	InferenceDest   string
	AllowlistOK     bool
	Err             error
}

type modelPickerAppliedMsg struct {
	ModelID string
	Scope   string
	Err     error
}

var (
	mpBg = lipgloss.Color(ColorCanvas)

	mpOuter = lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(lipgloss.Color(ColorBorder)).
		Background(mpBg).Padding(0, 1)

	mpProviderFocused = lipgloss.NewStyle().Foreground(lipgloss.Color("255")).Background(lipgloss.Color("33")).Bold(true)
	mpProviderSelected = lipgloss.NewStyle().Foreground(lipgloss.Color("39")).Background(mpBg)
	mpProviderNormal   = lipgloss.NewStyle().Foreground(lipgloss.Color(ColorText)).Background(mpBg)
	mpModelFocused     = lipgloss.NewStyle().Foreground(lipgloss.Color("255")).Background(lipgloss.Color("24")).Bold(true)
	mpModelNormal      = lipgloss.NewStyle().Foreground(lipgloss.Color(ColorText)).Background(mpBg)
	mpModelDisabled    = lipgloss.NewStyle().Foreground(lipgloss.Color(ColorTextDim)).Background(mpBg)
	mpDim              = lipgloss.NewStyle().Foreground(lipgloss.Color(ColorTextDim)).Background(mpBg)

	mpSearchStyle = textarea.Style{
		Base:        lipgloss.NewStyle().Foreground(lipgloss.Color(ColorText)).Background(mpBg),
		Text:        lipgloss.NewStyle().Foreground(lipgloss.Color(ColorText)).Background(mpBg),
		Placeholder: lipgloss.NewStyle().Foreground(lipgloss.Color(ColorTextDim)).Background(mpBg),
		CursorLine:  lipgloss.NewStyle().Foreground(lipgloss.Color(ColorText)).Background(mpBg),
	}
)

func newModelPickerSearch() textarea.Model {
	ti := textarea.New()
	ti.Placeholder = "filter models..."
	ti.CharLimit = 80
	ti.SetHeight(1)
	ti.ShowLineNumbers = false
	ti.Prompt = ""
	ti.FocusedStyle = mpSearchStyle
	ti.BlurredStyle = mpSearchStyle
	ti.Focus()
	return ti
}

func (m model) modelPickerFilterText() string { return strings.TrimSpace(m.modelPickerSearch.Value()) }

func (m *model) modelPickerProviders() []string {
	if len(m.modelPickerProvidersCache) > 0 { return m.modelPickerProvidersCache }
	if len(m.modelPickerProvidersAPI) > 0 {
		var out []string
		out = append(out, "Todos")
		for _, p := range m.modelPickerProvidersAPI {
			if p.ID != "openrouter" || p.Configured { out = append(out, p.ID) }
		}
		out = append(out, "⚙ presets")
		m.modelPickerProvidersCache = out
		return out
	}
	counts := map[string]int{}
	for _, row := range m.modelPickerItems {
		p := row.Provider; if p == "" { p = extractProvider(row.ID) }; counts[p]++
	}
	type pv struct{ name string; count int }
	var sorted []pv
	for n, c := range counts { sorted = append(sorted, pv{n, c}) }
	sort.Slice(sorted, func(i, j int) bool { return sorted[i].count > sorted[j].count })
	out := []string{"Todos"}
	for _, p := range sorted { out = append(out, p.name) }
	out = append(out, "⚙ presets")
	m.modelPickerProvidersCache = out
	return out
}

func (m model) providerDisplayName(pid string) string {
	for _, p := range m.modelPickerProvidersAPI {
		if p.ID == pid { l := p.Label; if !p.Configured && pid != "openrouter" { l += " ✗" }; return l }
	}
	return pid
}

func (m model) providerIsConfigured(pid string) bool {
	if pid == "Todos" || pid == "⚙ presets" || pid == "openrouter" { return true }
	for _, p := range m.modelPickerProvidersAPI { if p.ID == pid { return p.Configured } }
	return true
}

func (m model) providerModelCount(pid string) int {
	if pid == "Todos" { return len(m.modelPickerItems) }
	for _, p := range m.modelPickerProvidersAPI { if p.ID == pid { return p.ModelCount } }
	return 0
}

func (m model) providerSetupHint(pid string) string {
	for _, p := range m.modelPickerProvidersAPI { if p.ID == pid { return p.SetupHint } }
	return ""
}

func (m model) providerModels(provider string) []cloudModelRow {
	if provider == "" || provider == "Todos" || provider == "⚙ presets" { return m.modelPickerItems }
	var out []cloudModelRow
	for _, row := range m.modelPickerItems {
		p := row.Provider; if p == "" { p = extractProvider(row.ID) }
		if p == provider { out = append(out, row) }
	}
	return out
}

func (m model) filteredProviderModels() []cloudModelRow {
	base := m.providerModels(m.modelPickerProvider)
	f := strings.ToLower(m.modelPickerFilterText())
	if f == "" { return base }
	var out []cloudModelRow
	for _, row := range base {
		if strings.Contains(strings.ToLower(row.ID), f) || strings.Contains(strings.ToLower(row.Label), f) {
			out = append(out, row)
		}
	}
	return out
}

func modelDisplayName(id string) string {
	parts := strings.Split(id, "/")
	if len(parts) >= 2 {
		first := strings.ToLower(parts[0])
		if first == "openrouter" && len(parts) >= 3 { return strings.Join(parts[2:], "/") }
		return strings.Join(parts[1:], "/")
	}
	return id
}

func (m model) loadModelPickerCmd() tea.Cmd {
	client := m.client
	sessionOverride := m.sessionModelOverride

	// SOLO mode: build model list from local provider
	if m.runtime.Runtime == config.ModeSolo {
		return m.loadSoloModelPickerCmd(sessionOverride)
	}

	return func() tea.Msg {
		if client == nil { return modelPickerLoadedMsg{Err: fmt.Errorf("no client")} }
		activeID := sessionOverride; dest := "local"; userDefault := ""
		if prefs, err := client.GetPreferences(); err == nil {
			if ap, ok := prefs["assistant_preferences"].(map[string]any); ok {
				if mid, ok := ap["llm_model_id"].(string); ok { userDefault = mid; if activeID == "" { activeID = mid } }
				if d, ok := ap["inference_destination"].(string); ok && d != "" { dest = d }
			}
		}
		out, err := client.GetCloudModels()
		if err != nil { return modelPickerLoadedMsg{Err: err} }
		raw, _ := out["models"].([]any)
		var rows []cloudModelRow
		for _, item := range raw {
			row, ok := item.(map[string]any); if !ok { continue }
			id, _ := row["id"].(string); if id == "" { continue }
			label, _ := row["label"].(string); if label == "" { label = id }
			enabled, _ := row["enabled"].(bool)
			scope, _ := row["scope"].(string)
			provider, _ := row["provider"].(string); if provider == "" { provider = extractProvider(id) }
			rows = append(rows, cloudModelRow{ID: id, Label: label, Enabled: enabled, Scope: scope, Provider: provider})
		}
		allowOK := true
		if g, ok := out["governance"].(map[string]any); ok { if n, _ := g["catalog_count"].(float64); ok && n == 0 { allowOK = false } }
		var apiProviders []providerInfo
		if rawProvs, ok := out["providers"].([]any); ok {
			for _, rp := range rawProvs {
				p, ok := rp.(map[string]any); if !ok { continue }
				pid, _ := p["id"].(string); label, _ := p["label"].(string)
				cfg, _ := p["configured"].(bool); mc, _ := p["model_count"].(float64); hint, _ := p["setup_hint"].(string)
				apiProviders = append(apiProviders, providerInfo{ID: pid, Label: label, Configured: cfg, ModelCount: int(mc), SetupHint: hint})
			}
		}
		return modelPickerLoadedMsg{Models: rows, Providers: apiProviders, ActiveModelID: activeID, InferenceDest: dest, AllowlistOK: allowOK, UserDefault: userDefault}
	}
}

func (m model) applyModelUserCmd(modelID string) tea.Cmd {
	client := m.client
	return func() tea.Msg {
		if client == nil { return modelPickerAppliedMsg{Err: fmt.Errorf("no client")} }
		_, err := client.SetPreferences(map[string]any{"inference_destination": "api", "llm_model_id": modelID})
		return modelPickerAppliedMsg{ModelID: modelID, Scope: "user", Err: err}
	}
}

func (m model) applyModelSessionMsg(modelID string) tea.Msg { return modelPickerAppliedMsg{ModelID: modelID, Scope: "session"} }

func (m model) applyPresetCmd(idx int) tea.Cmd {
	client := m.client
	return func() tea.Msg {
		if client == nil { return modelPickerAppliedMsg{Err: fmt.Errorf("no client")} }
		switch idx {
		case 0: _, err := client.SetProfile("A"); return modelPickerAppliedMsg{ModelID: "eco (profile A)", Scope: "user", Err: err}
		case 1: _, err := client.SetProfile("B"); return modelPickerAppliedMsg{ModelID: "balanced (profile B)", Scope: "user", Err: err}
		case 2: _, err := client.SetProfile("C"); return modelPickerAppliedMsg{ModelID: "quality (profile C)", Scope: "user", Err: err}
		case 3: _, err := client.SetPreferences(map[string]any{"inference_destination":"api","auto_tier":"economy","llm_model_id":""}); return modelPickerAppliedMsg{ModelID:"auto-tier economy",Scope:"user",Err:err}
		case 4: _, err := client.SetPreferences(map[string]any{"inference_destination":"api","auto_tier":"balanced","llm_model_id":""}); return modelPickerAppliedMsg{ModelID:"auto-tier balanced",Scope:"user",Err:err}
		case 5: _, err := client.SetPreferences(map[string]any{"inference_destination":"api","auto_tier":"premium","llm_model_id":""}); return modelPickerAppliedMsg{ModelID:"auto-tier premium",Scope:"user",Err:err}
		case 6: _, err := client.SetPreferences(map[string]any{"inference_destination":"local"}); return modelPickerAppliedMsg{ModelID:"local",Scope:"user",Err:err}
		case 7: _, err := client.SetPreferences(map[string]any{"inference_destination":"api"}); return modelPickerAppliedMsg{ModelID:"api",Scope:"user",Err:err}
		default: return modelPickerAppliedMsg{Err: fmt.Errorf("preset_invalid")}
		}
	}
}

func (m model) applySelectedModel(scope string) (tea.Model, tea.Cmd) {
	if m.modelPickerProvider == "⚙ presets" { return m, m.applyPresetCmd(m.modelPanel.Cursor) }
	items := m.filteredProviderModels()
	idx := m.modelPanel.Cursor
	if idx < 0 || idx >= len(items) { return m, nil }
	chosen := items[idx]
	if !chosen.Enabled { m.errBar = "Model not active in your allowlist — activate on web or contact admin."; return m, nil }
	m.modelPickerOpen = false; m.input.Focus()
	if scope == "session" { m.sessionModelOverride = chosen.ID; return m, func() tea.Msg { return m.applyModelSessionMsg(chosen.ID) } }
	m.sessionModelOverride = ""
	return m, m.applyModelUserCmd(chosen.ID)
}

func (m model) updateModelPicker(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	if msg.String() == "esc" || msg.String() == "ctrl+c" { m.modelPickerOpen = false; m.modelPickerSearch.SetValue(""); m.input.Focus(); return m, nil }
	if isTypingKey(msg) { var cmd tea.Cmd; m.modelPickerSearch, cmd = m.modelPickerSearch.Update(msg); m.modelPanel.Reset(); return m, cmd }
	switch m.modelPickerFocus {
	case "provider": return m.updatePickerProviderPanel(msg)
	default: return m.updatePickerModelPanel(msg)
	}
}

func isTypingKey(msg tea.KeyMsg) bool {
	if len(msg.Runes) > 0 { return true }
	return msg.Type == tea.KeyBackspace || msg.Type == tea.KeyDelete || msg.String() == "backspace" || msg.String() == "delete" || msg.Type == tea.KeySpace
}

func (m model) updatePickerProviderPanel(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	providers := m.modelPickerProviders(); total := len(providers)
	switch msg.String() {
	case "up","k": m.providerPanel.Navigate(total, -1); m.applyProviderChange(providers)
	case "down","j": m.providerPanel.Navigate(total, 1); m.applyProviderChange(providers)
	case "enter","right":
		if m.modelPickerProvider == "⚙ presets" { m.modelPickerFocus = "model"; return m, nil }
		m.modelPickerFocus = "model"; return m, nil
	case "s": if m.modelPickerProvider == "⚙ presets" { return m.applySelectedModel("session") }
	case "d": if m.modelPickerProvider == "⚙ presets" { return m.applySelectedModel("user") }
	}
	return m, nil
}

func (m *model) applyProviderChange(providers []string) {
	idx := m.providerPanel.Cursor
	if idx >= 0 && idx < len(providers) { m.modelPickerProvider = providers[idx]; m.modelPanel.Reset(); m.modelPickerSearch.SetValue("") }
}

func (m model) updatePickerModelPanel(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	allItems := m.filteredProviderModels(); total := len(allItems)
	if m.modelPickerProvider == "⚙ presets" {
		switch msg.String() {
		case "up","k": m.modelPanel.Navigate(8, -1)
		case "down","j": m.modelPanel.Navigate(8, 1)
		case "enter": return m.applySelectedModel("session")
		case "left": m.modelPickerFocus = "provider"; return m, nil
		}
		return m, nil
	}
	switch msg.String() {
	case "up","k":
		if m.modelPanel.Cursor > 0 { m.modelPanel.Navigate(total, -1) } else { m.modelPickerFocus = "provider"; return m, nil }
	case "down","j":
		if m.modelPanel.Cursor < total-1 { m.modelPanel.Navigate(total, 1) } else { m.modelPickerFocus = "provider"; return m, nil }
	case "pgup": m.modelPanel.PageUp(total)
	case "pgdown": m.modelPanel.PageDown(total)
	case "enter": return m.applySelectedModel("session")
	case "left": m.modelPickerFocus = "provider"; return m, nil
	}
	return m, nil
}

func (m model) viewModelPicker(maxW int) string {
	if maxW <= 0 { maxW = m.width }
	providers := m.modelPickerProviders()
	modalW := min(maxW, 74); if modalW < 52 { modalW = maxW }
	leftW := 18; rightW := modalW - leftW - 1 - 4
	if rightW < 30 { rightW = 30; leftW = modalW - rightW - 1 - 4; if leftW < 8 { leftW = 8 } }
	const panelRows = 12

	totalP := len(providers)
	var provLines []string
	start, end := m.providerPanel.VisibleRange(totalP)
	for i := start; i < end; i++ {
		p := providers[i]
		displayName := m.providerDisplayName(p)
		if p != "Todos" && p != "⚙ presets" { if c := m.providerModelCount(p); c > 0 { displayName += fmt.Sprintf(" (%d)", c) } }
		label := truncateToWidth(displayName, leftW-3)
		isSel := i == m.providerPanel.Cursor; isFoc := m.modelPickerFocus == "provider"
		cfg := m.providerIsConfigured(p)
		style := mpProviderNormal
		if isFoc && isSel { style = mpProviderFocused } else if isSel && !isFoc { style = mpProviderSelected } else if !cfg && p != "Todos" && p != "⚙ presets" { style = mpModelDisabled }
		provLines = append(provLines, style.Render(" "+padOrTrunc(label, leftW-1)))
	}
	leftLines := PanelView(provLines, m.providerPanel, totalP, leftW, mpProviderNormal, mpDim)
	leftLines = PanelPad(leftLines, panelRows, leftW, mpProviderNormal)

	contentW := rightW - 2; if contentW < 14 { contentW = 14 }
	var rightLines []string

	if m.modelPickerProvider == "⚙ presets" {
		presets := []string{"Eco / A (profile)","Equilibrado / B","Performance / C","Auto-tier economy","Auto-tier balanced","Auto-tier premium","Destino: local","Destino: api"}
		var presetLines []string
		start, end := m.modelPanel.VisibleRange(8)
		for i := start; i < end && i < 8; i++ {
			l := truncateToWidth(presets[i], contentW-4)
			if i == m.modelPanel.Cursor { presetLines = append(presetLines, mpModelFocused.Render("▸ "+padOrTrunc(l, contentW-2))) } else { presetLines = append(presetLines, mpModelNormal.Render("  "+padOrTrunc(l, contentW-2))) }
		}
		rightLines = PanelView(presetLines, m.modelPanel, 8, contentW, mpModelNormal, mpDim)
	} else {
		s := m.modelPickerSearch; searchW := contentW - 1; if searchW < 8 { searchW = 8 }
		s.SetWidth(searchW); searchView := strings.TrimRight(s.View(), "\n")
		if idx := strings.LastIndex(searchView, "\x1b[0m"); idx >= 0 { searchView = searchView[:idx+4] + "\x1b[48;5;232m" + searchView[idx+4:] }
		if m.modelPickerFocus == "model" { rightLines = append(rightLines, mpModelFocused.Render(searchView)) } else { rightLines = append(rightLines, mpBgStyled(searchView)) }
		rightLines = append(rightLines, mpDim.Render(strings.Repeat("─", contentW)))
		if !m.providerIsConfigured(m.modelPickerProvider) && m.modelPickerProvider != "" && m.modelPickerProvider != "Todos" {
			if h := m.providerSetupHint(m.modelPickerProvider); h != "" { rightLines = append(rightLines, mpDim.Render(padOrTrunc("⚠ "+truncateToWidth(h, contentW-4), contentW))) }
		}
		allItems := m.filteredProviderModels(); total := len(allItems)
		maxNameW := contentW - 4; if maxNameW < 8 { maxNameW = 8 }
		if total == 0 {
			msg := "  (no models)"; if m.modelPickerFilterText() != "" { msg = "  (no results)" }
			rightLines = append(rightLines, mpDim.Render(padOrTrunc(msg, contentW)))
			for len(rightLines) < 2+9+1 { rightLines = append(rightLines, mpModelNormal.Render(strings.Repeat(" ", contentW))) }
		} else {
			var modelLines []string
			start, end := m.modelPanel.VisibleRange(total)
			for i := start; i < end; i++ {
				row := allItems[i]; name := modelDisplayName(row.ID)
				if row.Label != "" && row.Label != row.ID { name += " · " + modelDisplayName(row.Label) }
				name = truncateToWidth(name, maxNameW); if !row.Enabled { name = "(✗) " + name }
				if i == m.modelPanel.Cursor && m.modelPickerFocus == "model" { modelLines = append(modelLines, mpModelFocused.Render("▸ "+padOrTrunc(name, contentW-2))) } else if !row.Enabled { modelLines = append(modelLines, mpModelDisabled.Render("  "+padOrTrunc(name, contentW-2))) } else { modelLines = append(modelLines, mpModelNormal.Render("  "+padOrTrunc(name, contentW-2))) }
			}
			extra := PanelView(modelLines, m.modelPanel, total, contentW, mpModelNormal, mpDim)
			rightLines = append(rightLines, extra[1:]...)
		}
	}
	rightLines = PanelPad(rightLines, panelRows, contentW, mpModelNormal)

	leftBlock := strings.Join(leftLines, "\n"); rightBlock := strings.Join(rightLines, "\n")
	gapCol := GapColumn(panelRows, mpBg)
	inner := lipgloss.JoinHorizontal(lipgloss.Top, leftBlock, gapCol, rightBlock)
	header := fmt.Sprintf("/model — active: %s", truncateToWidth(modelDisplayName(m.activeModelDisplay()), modalW-22))
	footer := "[Enter] apply  [←→] panels  [Esc] close"
	return mpOuter.Render(header + "\n" + inner + "\n\n" + mpDim.Render(footer))
}

func (m model) activeModelDisplay() string {
	if m.sessionModelOverride != "" { return m.sessionModelOverride + " (session)" }
	if m.userDefaultModel != "" { return m.userDefaultModel }
	return m.modelName
}

func modelPickerPolicyMessage(err error) string {
	if err == nil { return "" }
	msg := err.Error()
	switch {
	case strings.Contains(msg, "policy_model_denied"): return "Model denied by policy (no bypass)."
	case strings.Contains(msg, "model_not_in_tenant_catalog"): return "Model not in tenant catalog."
	case strings.Contains(msg, "provider_not_configured"): return "Provider missing credentials — contact admin."
	default: return msg
	}
}

// ── SOLO model picker ───────────────────────────────────────────

func (m model) loadSoloModelPickerCmd(sessionOverride string) tea.Cmd {
	return func() tea.Msg {
		if m.soloAgent == nil || m.soloAgent.Provider == nil {
			return modelPickerLoadedMsg{Err: fmt.Errorf("no provider configured. Set OPENROUTER_API_KEY or OLLAMA_URL")}
		}
		provider := m.soloAgent.Provider

		var rows []cloudModelRow
		activeID := sessionOverride
		if activeID == "" {
			activeID = m.modelName
		}

		// Try to list models from provider
		models, err := provider.ListModels()
		if err != nil {
			// API error — show current model with error note
			rows = append(rows, cloudModelRow{
				ID:       provider.Model,
				Label:    displayModelLabel(provider.Model) + " (API error: " + err.Error() + ")",
				Enabled:  true,
				Provider: string(provider.Kind),
			})
		} else if len(models) == 0 {
			// No models returned — show current as single entry
			rows = append(rows, cloudModelRow{
				ID:       provider.Model,
				Label:    displayModelLabel(provider.Model),
				Enabled:  true,
				Provider: string(provider.Kind),
			})
		} else {
			for _, name := range models {
				rows = append(rows, cloudModelRow{
					ID:       name,
					Label:    displayModelLabel(name),
					Enabled:  true,
					Provider: string(provider.Kind),
				})
			}
		}

		return modelPickerLoadedMsg{
			Models:       rows,
			ActiveModelID: activeID,
			InferenceDest: "local",
			AllowlistOK:   true,
		}
	}
}

func displayModelLabel(id string) string {
	// Remove provider prefixes for cleaner display
	id = strings.TrimPrefix(id, "openai/")
	id = strings.TrimPrefix(id, "openrouter/")
	id = strings.TrimPrefix(id, "anthropic/")
	// Remove Ollama quantization tags
	if idx := strings.Index(id, ":latest"); idx >= 0 {
		id = id[:idx]
	}
	// Remove common quantization suffixes: :q4_0, :q4_K_M, :q8_0, etc.
	if idx := strings.LastIndex(id, ":"); idx > 0 {
		suffix := id[idx+1:]
		if strings.HasPrefix(suffix, "q") || suffix == "latest" || suffix == "instruct" {
			id = id[:idx]
		}
	}
	return id
}

func truncateToWidth(s string, w int) string {
	if w <= 0 { return "" }
	runes := []rune(s); if len(runes) <= w { return s }
	return string(runes[:w-1]) + "…"
}

func padOrTrunc(s string, w int) string {
	runes := []rune(s); if len(runes) > w { return string(runes[:w-1]) + "…" }
	return s + strings.Repeat(" ", w-len(runes))
}

func mpBgStyled(s string) string { return lipgloss.NewStyle().Background(lipgloss.Color(ColorCanvas)).Render(s) }
