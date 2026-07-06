package ui

import (
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

type slashCommand struct {
	Name        string
	Description string
	Aliases     []string
}

var slashCatalog = []slashCommand{
	{Name: "/model", Description: "Model catalog + presets", Aliases: []string{"/m", "/models"}},
	{Name: "/agent", Description: "Active team agent", Aliases: []string{"/agents"}},
	{Name: "/tools", Description: "Toggle tool families"},
	{Name: "/memory", Description: "Memory / RAG / context"},
	{Name: "/session", Description: "New · list · open session"},
	{Name: "/approve", Description: "Pending · diff · approve"},
	{Name: "/workspace", Description: "Switch tab / bind"},
	{Name: "/doctor", Description: "Inline checklist"},
	{Name: "/thinking", Description: "Reasoning panel"},
	{Name: "/tier", Description: "Auto tier: economy|balanced|premium"},
	{Name: "/route", Description: "OpenRouter routing: cheapest|fastest|throughput"},
	{Name: "/temp", Description: "Temperature 0.0–2.0"},
	{Name: "/effort", Description: "Reasoning effort: low|medium|high"},
	{Name: "/thinking-budget", Description: "Anthropic thinking budget in tokens"},
	{Name: "/params", Description: "Show current inference params"},
	{Name: "/undo", Description: "Revert last agent turn"},
	{Name: "/retry", Description: "Resend last prompt"},
	{Name: "/prefs", Description: "Save defaults for new sessions"},
	{Name: "/setup", Description: "Configure providers & tools"},
	{Name: "/mode", Description: "Switch SOLO/TEAM mode"},
	{Name: "/clear", Description: "Clear conversation"},
	{Name: "/pin", Description: "Pin/unpin current session"},
	{Name: "/resume", Description: "Switch to another session"},
	{Name: "/logout", Description: "End session (back to login)"},
	{Name: "/exit", Description: "Exit application"},
	{Name: "/help", Description: "Help"},
}

func filterSlashCommands(query string) []slashCommand {
	q := strings.TrimSpace(strings.ToLower(query))
	if q == "/" {
		return slashCatalog
	}
	var out []slashCommand
	for _, c := range slashCatalog {
		if strings.HasPrefix(strings.ToLower(c.Name), q) {
			out = append(out, c)
			continue
		}
		for _, a := range c.Aliases {
			if strings.HasPrefix(strings.ToLower(a), q) {
				out = append(out, c)
				break
			}
		}
	}
	return out
}

func (m *model) openSlashPaletteFromInput() {
	val := strings.TrimSpace(m.input.Value())
	if !strings.HasPrefix(val, "/") {
		m.slashPaletteOpen = false
		return
	}
	m.slashPaletteOpen = true
	m.slashItems = filterSlashCommands(val)
	if len(m.slashItems) == 0 {
		m.slashPaletteOpen = false
		return
	}
	if m.slashIdx >= len(m.slashItems) {
		m.slashIdx = 0
	}
}

const slashMaxVisible = 12

func (m model) viewSlashPalette() string {
	all := m.slashItems
	off := m.slashOff
	vis := slashMaxVisible
	if vis > len(all) {
		vis = len(all)
	}
	end := off + vis
	if end > len(all) {
		end = len(all)
	}
	if off >= len(all) {
		off = max(len(all)-vis, 0)
	}

	var lines []string
	if off > 0 {
		lines = append(lines, styleDim.Render("  ▲ more..."))
	}
	for i := off; i < end; i++ {
		c := all[i]
		lines = append(lines, renderListRow(i == m.slashIdx, c.Name, c.Description))
	}
	if end < len(all) {
		lines = append(lines, styleDim.Render("  ▼ more..."))
	}

	box := Theme().StyleBorder.
		Background(lipgloss.Color(ColorCanvas)).
		Padding(0, 1).Render(
		"/ — commands\n" + strings.Join(lines, "\n") +
			"\n↑↓ navigate · Tab/Enter select · Esc close · type to filter",
	)
	return box
}

func sessionTea(m *model) tea.Model {
	if m == nil {
		return model{}
	}
	return *m
}

func (m *model) updateSlashPalette(key tea.KeyMsg) (tea.Model, tea.Cmd) {
	if key.Type == tea.KeyTab {
		if len(m.slashItems) == 0 {
			return sessionTea(m), nil
		}
		cmd := m.slashItems[m.slashIdx].Name
		m.slashPaletteOpen = false
		m.input.SetValue(cmd + " ")
		return m.handleSlash(cmd)
	}
	switch key.String() {
	case "esc":
		m.slashPaletteOpen = false
		m.input.SetValue("")
		return sessionTea(m), nil
	case "up", "k":
		if m.slashIdx > 0 {
			m.slashIdx--
		}
		m.keepSlashVisible()
	case "down", "j":
		if m.slashIdx < len(m.slashItems)-1 {
			m.slashIdx++
		}
		m.keepSlashVisible()
	case "enter":
		if len(m.slashItems) == 0 {
			return sessionTea(m), nil
		}
		cmd := m.slashItems[m.slashIdx].Name
		m.slashPaletteOpen = false
		m.input.SetValue(cmd + " ")
		return m.handleSlash(cmd)
	default:
		var c tea.Cmd
		m.input, c = m.input.Update(key)
		m.openSlashPaletteFromInput()
		return sessionTea(m), c
	}
	return sessionTea(m), nil
}

func (m *model) keepSlashVisible() {
	if m.slashIdx < m.slashOff {
		m.slashOff = m.slashIdx
	}
	if m.slashIdx >= m.slashOff+slashMaxVisible {
		m.slashOff = m.slashIdx - slashMaxVisible + 1
	}
}

func (m *model) runSlashCommand(name string) (tea.Model, tea.Cmd) {
	return m.handleSlash(name)
}
