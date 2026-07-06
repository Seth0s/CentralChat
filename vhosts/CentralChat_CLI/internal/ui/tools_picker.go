package ui

import (
	"fmt"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/centralchurch/central-cli/internal/config"
	agentruntime "github.com/centralchurch/central-cli/internal/runtime"
)

type toolRow struct {
	Name        string
	Description string
	Enabled     bool
}

type toolsLoadedMsg struct {
	Tools []toolRow
	Err   error
}

var (
	tBg = lipgloss.Color(ColorCanvas)

	tToolOn = lipgloss.NewStyle().
			Foreground(lipgloss.Color("39")).
			Background(tBg).
			Bold(true)
	tToolFocused = lipgloss.NewStyle().
			Foreground(lipgloss.Color("255")).
			Background(lipgloss.Color("24")).
			Bold(true)
	tToolNormal = lipgloss.NewStyle().
			Foreground(lipgloss.Color(ColorText)).
			Background(tBg)

	tDim = lipgloss.NewStyle().
		Foreground(lipgloss.Color(ColorTextDim)).
		Background(tBg)

	tOuter = lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(lipgloss.Color(ColorBorder)).
		Background(tBg).
		Padding(0, 1)
)

func (m model) loadToolsCmd() tea.Cmd {
	client := m.client
	currentTools := m.sessionToolNames

	// SOLO mode: show local tool catalog
	if m.runtime.Runtime == config.ModeSolo {
		return func() tea.Msg {
			catalog := agentruntime.ToolNames()
			var tools []toolRow
			currentSet := map[string]bool{}
			for _, t := range currentTools { currentSet[t] = true }
			for _, name := range catalog {
				tools = append(tools, toolRow{Name: name, Description: "", Enabled: currentSet[name]})
			}
			return toolsLoadedMsg{Tools: tools}
		}
	}

	return func() tea.Msg {
		if client == nil {
			return toolsLoadedMsg{Err: fmt.Errorf("no client")}
		}
		cfg, err := client.GetConfig()
		if err != nil {
			return toolsLoadedMsg{Err: err}
		}
		var tools []toolRow
		currentSet := map[string]bool{}
		for _, t := range currentTools {
			currentSet[t] = true
		}
		if raw, ok := cfg["agent_tools_catalog"].([]any); ok {
			for _, item := range raw {
				row, ok := item.(map[string]any)
				if !ok {
					continue
				}
				name, _ := row["name"].(string)
				if name == "" {
					continue
				}
				desc, _ := row["description"].(string)
				tools = append(tools, toolRow{
					Name: name, Description: desc,
					Enabled: currentSet[name],
				})
			}
		}
		if len(tools) == 0 {
			return toolsLoadedMsg{Err: fmt.Errorf("no tools available")}
		}
		return toolsLoadedMsg{Tools: tools}
	}
}

func (m model) updateToolsPicker(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	if msg.String() == "esc" || msg.String() == "ctrl+c" {
		m.toolsPickerOpen = false
		m.input.Focus()
		return m, nil
	}

	total := len(m.toolsPickerItems)
	switch msg.String() {
	case "up", "k":
		m.toolsPanel.Navigate(total, -1)
	case "down", "j":
		m.toolsPanel.Navigate(total, 1)
	case "pgup":
		m.toolsPanel.PageUp(total)
	case "pgdown":
		m.toolsPanel.PageDown(total)
	case " ":
		idx := m.toolsPanel.Cursor
		if idx >= 0 && idx < total {
			m.toolsPickerItems[idx].Enabled = !m.toolsPickerItems[idx].Enabled
		}
	case "a":
		for i := range m.toolsPickerItems {
			m.toolsPickerItems[i].Enabled = true
		}
	case "n":
		for i := range m.toolsPickerItems {
			m.toolsPickerItems[i].Enabled = false
		}
	case "enter", "s":
		return m.applyToolsSelection()
	}
	return m, nil
}

func (m model) applyToolsSelection() (tea.Model, tea.Cmd) {
	m.toolsPickerOpen = false
	m.input.Focus()

	var enabled []string
	for _, t := range m.toolsPickerItems {
		if t.Enabled {
			enabled = append(enabled, t.Name)
		}
	}
	m.sessionToolNames = enabled
	m.useAgentTools = len(enabled) > 0

	msg := fmt.Sprintf("Tools: %d active", len(enabled))
	if len(enabled) > 0 {
		msg += fmt.Sprintf(" (%s)", strings.Join(enabled, ", "))
	}
	m.messages = append(m.messages, chatLine{role: "system", content: msg})
	return m, nil
}

func (m model) viewToolsPicker(maxW int) string {
	if maxW <= 0 {
		maxW = m.width
	}
	w := min(maxW, 60)
	if w < 30 {
		w = maxW
	}
	contentW := w - 4
	const panelRows = 14

	total := len(m.toolsPickerItems)
	start, end := m.toolsPanel.VisibleRange(total)
	visItems := m.toolsPickerItems[start:end]

	var itemLines []string
	for i, t := range visItems {
		globalIdx := start + i
		prefix := " ○ "
		if t.Enabled {
			prefix = " ● "
		}
		label := truncateToWidth(t.Name, contentW-6)
		if t.Description != "" {
			label += " · " + truncateToWidth(t.Description, contentW-len(t.Name)-6)
		}

		var line string
		if globalIdx == m.toolsPanel.Cursor {
			line = tToolFocused.Render(prefix + padOrTrunc(label, contentW-3))
		} else if t.Enabled {
			line = tToolOn.Render(prefix + padOrTrunc(label, contentW-3))
		} else {
			line = tToolNormal.Render(prefix + padOrTrunc(label, contentW-3))
		}
		itemLines = append(itemLines, line)
	}

	lines := PanelView(itemLines, m.toolsPanel, total, contentW, tToolNormal, tDim)
	lines = PanelPad(lines, panelRows, contentW, tToolNormal)

	header := fmt.Sprintf("/tools — %d tools", total)
	enabledCount := 0
	for _, t := range m.toolsPickerItems {
		if t.Enabled {
			enabledCount++
		}
	}
	if enabledCount > 0 {
		header += fmt.Sprintf(" (%d active)", enabledCount)
	}
	footer := "[a] all  [n] none  [space] toggle  [s/Enter] apply  [Esc] close"

	return tOuter.Render(header + "\n" + strings.Join(lines, "\n") + "\n\n" + tDim.Render(footer))
}
