package ui

import (
	"fmt"
	"strconv"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/centralchurch/central-cli/internal/config"
)

type paramRow struct {
	Name    string
	Value   string
	Kind    string // "enum" | "number"
	Options []string // for enum
}

type paramsPickerLoadedMsg struct {
	Err error
}

var (
	pBg = lipgloss.Color(ColorCanvas)

	pParamFocused = lipgloss.NewStyle().
			Foreground(lipgloss.Color("255")).
			Background(lipgloss.Color("24")).
			Bold(true)

	pParamNormal = lipgloss.NewStyle().
			Foreground(lipgloss.Color(ColorText)).
			Background(pBg)

	pLabel = lipgloss.NewStyle().
		Foreground(lipgloss.Color("39")).
		Background(pBg).
		Bold(true)

	pValue = lipgloss.NewStyle().
		Foreground(lipgloss.Color(ColorText)).
		Background(pBg)

	pDim = lipgloss.NewStyle().
		Foreground(lipgloss.Color(ColorTextDim)).
		Background(pBg)

	pOuter = lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(lipgloss.Color(ColorBorder)).
		Background(pBg).
		Padding(0, 1)
)

func (m model) buildParamsPickerItems() []paramRow {
	var items []paramRow

	items = append(items, paramRow{
		Name: "Tier", Value: m.autoTier, Kind: "enum",
		Options: []string{"", "economy", "balanced", "premium"},
	})

	// Route: only meaningful for cloud (OpenRouter)
	items = append(items, paramRow{
		Name: "Route", Value: m.providerRouting, Kind: "enum",
		Options: []string{"", "cheapest", "fastest", "throughput"},
	})

	items = append(items, paramRow{
		Name: "Temperature", Value: fmt.Sprintf("%.1f", m.temperature), Kind: "number",
	})

	items = append(items, paramRow{
		Name: "Effort", Value: m.effort, Kind: "enum",
		Options: []string{"", "low", "medium", "high"},
	})

	items = append(items, paramRow{
		Name: "Thinking", Value: fmt.Sprintf("%d", m.thinkingBudget), Kind: "number",
	})

	return items
}

func (m *model) cycleParamValue(item *paramRow) {
	if item.Kind != "enum" || len(item.Options) == 0 {
		return
	}
	idx := -1
	for i, o := range item.Options {
		if o == item.Value {
			idx = i
			break
		}
	}
	idx = (idx + 1) % len(item.Options)
	item.Value = item.Options[idx]
}

func (m *model) applyParamsPicker() {
	for _, p := range m.paramsPickerItems {
		switch p.Name {
		case "Tier":
			m.autoTier = p.Value
		case "Route":
			m.providerRouting = p.Value
		case "Temperature":
			if t, err := strconv.ParseFloat(p.Value, 64); err == nil {
				m.temperature = t
			}
		case "Effort":
			m.effort = p.Value
		case "Thinking":
			if tb, err := strconv.Atoi(p.Value); err == nil {
				m.thinkingBudget = tb
			}
		}
	}
}

func (m *model) applyAndSaveParams() tea.Cmd {
	m.applyParamsPicker()

	// SOLO mode: save locally (in-memory only, config.toml for persistence)
	if m.runtime.Runtime == config.ModeSolo {
		return func() tea.Msg {
			// Save to config.toml if possible
			rt, err := config.LoadRuntimeConfig()
			if err == nil && rt != nil {
				if m.autoTier != "" { rt.Solo.Model = m.modelName }
				_ = config.SaveRuntimeConfig(rt)
			}
			return memoryStatusMsg{Text: "Params applied locally."}
		}
	}

	prefs := map[string]any{}
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
	if m.thinkingBudget > 0 {
		prefs["thinking_budget"] = m.thinkingBudget
	}

	return func() tea.Msg {
		_, err := m.client.SetPreferences(prefs)
		if err != nil {
			return memoryStatusMsg{Err: err}
		}
		return memoryStatusMsg{Text: "Params saved as defaults."}
	}
}

func (m model) updateParamsPicker(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch msg.String() {
	case "esc", "ctrl+c":
		m.paramsPickerOpen = false
		m.input.Focus()
		return m, nil
	case "up", "k":
		if m.paramsPanel.Cursor > 0 {
			m.paramsPanel.NavigateTo(m.paramsPanel.Cursor-1, len(m.paramsPickerItems))
		}
	case "down", "j":
		m.paramsPanel.NavigateTo(m.paramsPanel.Cursor+1, len(m.paramsPickerItems))
	case " ", "enter":
		idx := m.paramsPanel.Cursor
		if idx >= 0 && idx < len(m.paramsPickerItems) {
			item := &m.paramsPickerItems[idx]
			if item.Kind == "enum" {
				m.cycleParamValue(item)
			}
		}
	case "p":
		m.paramsPickerOpen = false
		m.input.Focus()
		m.messages = append(m.messages, chatLine{role: "system", content: "Params saved as defaults for new sessions."})
		return m, m.applyAndSaveParams()
	case "s":
		m.paramsPickerOpen = false
		m.input.Focus()
		m.applyParamsPicker()
		var parts []string
		for _, p := range m.paramsPickerItems {
			if p.Value != "" && p.Value != "0.0" && p.Value != "0" {
				parts = append(parts, p.Name+": "+p.Value)
			}
		}
		msg := "Params applied"
		if len(parts) > 0 {
			msg += ": " + strings.Join(parts, ", ")
		}
		m.messages = append(m.messages, chatLine{role: "system", content: msg})
		return m, nil
	}
	return m, nil
}

func (m model) viewParamsPicker(maxW int) string {
	if maxW <= 0 {
		maxW = m.width
	}
	w := min(maxW, 50)
	if w < 30 {
		w = maxW
	}
	contentW := w - 4
	const panelRows = 10

	total := len(m.paramsPickerItems)
	start, end := m.paramsPanel.VisibleRange(total)
	visItems := m.paramsPickerItems[start:end]

	var itemLines []string
	for i, p := range visItems {
		globalIdx := start + i

		// Show value with cycle indicator for enums
		valDisplay := p.Value
		if p.Value == "" || p.Value == "0.0" || p.Value == "0" {
			valDisplay = "(off)"
		}
		if p.Kind == "enum" {
			valDisplay += " ▶"
		}

		label := fmt.Sprintf("%-14s %s", p.Name, valDisplay)
		label = truncateToWidth(label, contentW-2)

		var line string
		if globalIdx == m.paramsPanel.Cursor {
			line = pParamFocused.Render("  " + padOrTrunc(label, contentW-2))
		} else {
			line = pParamNormal.Render("  " + padOrTrunc(label, contentW-2))
		}
		itemLines = append(itemLines, line)
	}

	lines := PanelView(itemLines, m.paramsPanel, total, contentW, pParamNormal, pDim)
	lines = PanelPad(lines, panelRows, contentW, pParamNormal)

	header := fmt.Sprintf("/params — %d parameters", total)
	footer := "[space] cycle  [enter] cycle enum  [s] apply  [p] save  [Esc] close"

	return pOuter.Render(header + "\n" + strings.Join(lines, "\n") + "\n\n" + pDim.Render(footer))
}
