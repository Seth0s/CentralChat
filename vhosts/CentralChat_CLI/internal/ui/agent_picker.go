package ui

import (
	"fmt"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/centralchurch/central-cli/internal/config"
)

type agentRow struct {
	Name        string
	Description string
	Active      bool
}

type skillRow struct {
	Name        string
	Description string
}

type agentPickerLoadedMsg struct {
	Agents []agentRow
	Skills []skillRow
	Err    error
}

var (
	apBg = lipgloss.Color(ColorCanvas)

	apAgentFocused = lipgloss.NewStyle().
			Foreground(lipgloss.Color("255")).
			Background(lipgloss.Color("33")).
			Bold(true)
	apAgentSelected = lipgloss.NewStyle().
			Foreground(lipgloss.Color("39")).
			Background(apBg)
	apAgentNormal = lipgloss.NewStyle().
			Foreground(lipgloss.Color(ColorText)).
			Background(apBg)

	apSkillOn = lipgloss.NewStyle().
			Foreground(lipgloss.Color("39")).
			Background(apBg).
			Bold(true)
	apSkillFocused = lipgloss.NewStyle().
			Foreground(lipgloss.Color("255")).
			Background(lipgloss.Color("24")).
			Bold(true)
	apSkillNormal = lipgloss.NewStyle().
			Foreground(lipgloss.Color(ColorText)).
			Background(apBg)

	apDim = lipgloss.NewStyle().
		Foreground(lipgloss.Color(ColorTextDim)).
		Background(apBg)

	apOuter = lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(lipgloss.Color(ColorBorder)).
		Background(apBg).
		Padding(0, 1)
)

func (m model) loadAgentPickerCmd() tea.Cmd {
	client := m.client
	activeAgent := m.activeAgentName

	// SOLO mode: show local agents
	if m.runtime.Runtime == config.ModeSolo {
		return func() tea.Msg {
			agents := loadLocalAgents()
			var agentRows []agentRow
			for _, a := range agents {
				agentRows = append(agentRows, agentRow{
					Name: a.Name, Description: a.Description,
					Active: a.Name == activeAgent,
				})
			}
			var skillRows []skillRow
			for _, s := range loadLocalSkills() {
				skillRows = append(skillRows, skillRow{Name: s.Name, Description: s.Description})
			}
			if len(agentRows) == 0 {
				agentRows = append(agentRows, agentRow{Name: "default", Description: "Default local agent", Active: activeAgent == "" || activeAgent == "default"})
			}
			return agentPickerLoadedMsg{Agents: agentRows, Skills: skillRows}
		}
	}

	return func() tea.Msg {
		if client == nil {
			return agentPickerLoadedMsg{Err: fmt.Errorf("no client")}
		}
		var agents []agentRow
		out, err := client.ListTeamAgents("published")
		if err == nil {
			items, _ := out["items"].([]any)
			for _, it := range items {
				row, ok := it.(map[string]any)
				if !ok {
					continue
				}
				name, _ := row["name"].(string)
				if name == "" {
					continue
				}
				desc, _ := row["description"].(string)
				agents = append(agents, agentRow{
					Name: name, Description: desc,
					Active: name == activeAgent,
				})
			}
		}

		var skills []skillRow
		sk, err := client.ListTeamSkills("published")
		if err == nil {
			items, _ := sk["items"].([]any)
			for _, it := range items {
				row, ok := it.(map[string]any)
				if !ok {
					continue
				}
				name, _ := row["name"].(string)
				if name == "" {
					continue
				}
				desc, _ := row["description"].(string)
				skills = append(skills, skillRow{Name: name, Description: desc})
			}
		}

		return agentPickerLoadedMsg{Agents: agents, Skills: skills}
	}
}

func (m model) updateAgentPicker(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	if msg.String() == "esc" || msg.String() == "ctrl+c" {
		m.agentPickerOpen = false
		m.input.Focus()
		return m, nil
	}

	if m.agentPickerFocus == "agent" || len(m.agentPickerSkills) == 0 {
		return m.updateAgentPanel(msg)
	}
	return m.updateAgentSkillPanel(msg)
}

func (m model) updateAgentPanel(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	total := len(m.agentPickerItems)
	switch msg.String() {
	case "up", "k":
		m.agentPanel.Navigate(total, -1)
	case "down", "j":
		m.agentPanel.Navigate(total, 1)
	case " ":
		idx := m.agentPanel.Cursor
		for i := range m.agentPickerItems {
			m.agentPickerItems[i].Active = (i == idx)
		}
		return m, nil
	case "enter", "right":
		if len(m.agentPickerSkills) > 0 {
			m.agentPickerFocus = "skill"
			m.skillPanel.Reset()
		} else {
			return m.applyAgentSelection()
		}
		return m, nil
	case "s":
		return m.applyAgentSelection()
	}
	return m, nil
}

func (m model) updateAgentSkillPanel(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	total := len(m.agentPickerSkills)
	switch msg.String() {
	case "up", "k":
		m.skillPanel.Navigate(total, -1)
	case "down", "j":
		m.skillPanel.Navigate(total, 1)
	case " ", "enter":
		idx := m.skillPanel.Cursor
		if idx >= 0 && idx < total {
			name := m.agentPickerSkills[idx].Name
			if m.agentPickerSkillSel == nil {
				m.agentPickerSkillSel = map[string]bool{}
			}
			m.agentPickerSkillSel[name] = !m.agentPickerSkillSel[name]
		}
	case "left":
		m.agentPickerFocus = "agent"
		return m, nil
	case "s":
		return m.applyAgentSelection()
	}
	return m, nil
}

func (m model) applyAgentSelection() (tea.Model, tea.Cmd) {
	m.agentPickerOpen = false
	m.input.Focus()

	if m.agentPanel.Cursor >= 0 && m.agentPanel.Cursor < len(m.agentPickerItems) {
		agent := m.agentPickerItems[m.agentPanel.Cursor]
		_ = config.SaveActiveAgent(agent.Name)
		m.activeAgentName = agent.Name

		var sel []string
		for _, sk := range m.agentPickerSkills {
			if m.agentPickerSkillSel[sk.Name] {
				sel = append(sel, sk.Name)
			}
		}
		m.sessionSkillNames = sel

		msg := fmt.Sprintf("Agent: %s", agent.Name)
		if len(sel) > 0 {
			msg += fmt.Sprintf(" · Skills: %s", strings.Join(sel, ", "))
		}
		m.messages = append(m.messages, chatLine{role: "system", content: msg})
	}
	return m, nil
}

func (m model) viewAgentPicker(maxW int) string {
	if maxW <= 0 {
		maxW = m.width
	}
	modalW := min(maxW, 74)
	if modalW < 52 {
		modalW = maxW
	}
	leftW := 18
	rightW := modalW - leftW - 1 - 4
	if rightW < 30 {
		rightW = 30
		leftW = modalW - rightW - 1 - 4
		if leftW < 8 {
			leftW = 8
		}
	}

	const panelRows = 12

	totalA := len(m.agentPickerItems)
	var agentLines []string
	start, end := m.agentPanel.VisibleRange(totalA)
	for i := start; i < end; i++ {
		a := m.agentPickerItems[i]
		label := truncateToWidth(a.Name, leftW-3)
		isSelected := i == m.agentPanel.Cursor
		isFocused := m.agentPickerFocus == "agent"

		var prefix string
		var style lipgloss.Style
		if isFocused && isSelected {
			style = apAgentFocused
		} else if isSelected && !isFocused {
			style = apAgentSelected
		} else {
			style = apAgentNormal
		}
		if a.Active {
			prefix = " ●"
		} else {
			prefix = "  "
		}
		agentLines = append(agentLines, style.Render(prefix+padOrTrunc(label, leftW-2)))
	}

	leftLines := PanelView(agentLines, m.agentPanel, totalA, leftW, apAgentNormal, apDim)
	leftLines = PanelPad(leftLines, panelRows, leftW, apAgentNormal)

	contentW := rightW - 2
	if contentW < 14 {
		contentW = 14
	}

	var rightLines []string
	totalS := len(m.agentPickerSkills)

	if totalS == 0 {
		rightLines = append(rightLines, apSkillNormal.Render(strings.Repeat(" ", contentW)))
		rightLines = append(rightLines, apDim.Render(padOrTrunc("  (no skills)", contentW)))
		for len(rightLines) < panelRows {
			rightLines = append(rightLines, apSkillNormal.Render(strings.Repeat(" ", contentW)))
		}
		rightLines = rightLines[:panelRows]
	} else {
		var skillLines []string
		start, end := m.skillPanel.VisibleRange(totalS)
		for i := start; i < end; i++ {
			sk := m.agentPickerSkills[i]
			label := truncateToWidth(sk.Name, contentW-6)
			isSelected := i == m.skillPanel.Cursor
			isFocused := m.agentPickerFocus == "skill"
			isOn := m.agentPickerSkillSel[sk.Name]

			prefix := " ○ "
			if isOn {
				prefix = " ● "
			}

			var line string
			if isFocused && isSelected {
				line = apSkillFocused.Render(prefix + padOrTrunc(label, contentW-3))
			} else if isOn {
				line = apSkillOn.Render(prefix + padOrTrunc(label, contentW-3))
			} else {
				line = apSkillNormal.Render(prefix + padOrTrunc(label, contentW-3))
			}
			skillLines = append(skillLines, line)
		}

		rightLines = PanelView(skillLines, m.skillPanel, totalS, contentW, apSkillNormal, apDim)
		rightLines = PanelPad(rightLines, panelRows, contentW, apSkillNormal)
	}

	leftBlock := strings.Join(leftLines, "\n")
	rightBlock := strings.Join(rightLines, "\n")
	gapCol := GapColumn(panelRows, apBg)

	inner := lipgloss.JoinHorizontal(lipgloss.Top, leftBlock, gapCol, rightBlock)

	header := "/agent — select agent and skills"
	if m.agentPanel.Cursor >= 0 && m.agentPanel.Cursor < totalA {
		header = fmt.Sprintf("/agent — %s", truncateToWidth(m.agentPickerItems[m.agentPanel.Cursor].Name, modalW-15))
	}
	footer := "[space] select  [s] apply  [←→] panels  [Esc] close"

	return apOuter.Render(header + "\n" + inner + "\n\n" + apDim.Render(footer))
}
