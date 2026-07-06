package ui

import (
	"fmt"
	"sort"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

type sessionCapabilitiesMsg struct {
	Tools  []string
	Skills []string
	Agent  string
	Err    error
}

func (m model) loadSessionCapabilitiesCmd() tea.Cmd {
	client := m.client
	return func() tea.Msg {
		msg := sessionCapabilitiesMsg{}
		if client == nil {
			return msg
		}
		if cfg, err := client.GetConfig(); err == nil {
			if raw, ok := cfg["agent_tools_catalog"].([]any); ok {
				for _, item := range raw {
					row, ok := item.(map[string]any)
					if !ok {
						continue
					}
					if name, ok := row["name"].(string); ok && name != "" {
						msg.Tools = append(msg.Tools, name)
					}
				}
			}
		}
		if skills, err := client.ListTeamSkills("published"); err == nil {
			if items, ok := skills["items"].([]any); ok {
				for _, item := range items {
					row, ok := item.(map[string]any)
					if !ok {
						continue
					}
					if name, ok := row["name"].(string); ok && name != "" {
						msg.Skills = append(msg.Skills, name)
					}
				}
			}
		}
		if agents, err := client.ListTeamAgents("published"); err == nil {
			if items, ok := agents["items"].([]any); ok && len(items) > 0 {
				if row, ok := items[0].(map[string]any); ok {
					msg.Agent, _ = row["name"].(string)
				}
			}
		}
		return msg
	}
}

func (m model) isEmptyConversation() bool {
	if len(m.messages) > 0 || m.streaming {
		return false
	}
	return m.approval == nil && m.clarify == nil
}

// applyCanvasBg wraps every line of a text block in the canvas background style.
// Patches internal SGR resets so the background survives inline style boundaries.
func applyCanvasBg(block string, width int) string {
	return enforceScreenBG(block, width)
}

func (m model) renderSessionEmptyState(cw int) string {
	logo := renderEmptyStateWordmark(cw)
	block := renderCapabilitiesBlock(m, cw)
	return logo + "\n\n" + block
}

// renderEmptyStateWordmark shows ASCII wordmark whenever the session has no messages.
func renderEmptyStateWordmark(width int) string {
	t := Theme()
	accent := t.StyleAccent.Copy().Background(lipgloss.Color(ColorCanvas))
	dim := t.StyleDim.Copy().Background(lipgloss.Color(ColorCanvas))

	var art string
	switch {
	case width < 44:
		return accent.Bold(true).Render(wordmarkCompact) + "\n" + dim.Render(wordmarkSub)
	case width < 70:
		art = wordmarkSessionASCII
	default:
		art = wordmarkASCII
	}
	return renderLinesOnCanvas(art, accent) + "\n" + dim.Render(wordmarkSub)
}

// renderLinesOnCanvas paints each line on black so ASCII gaps stay filled.
func renderLinesOnCanvas(block string, style lipgloss.Style) string {
	block = strings.Trim(block, "\n")
	if block == "" {
		return ""
	}
	lines := strings.Split(block, "\n")
	out := make([]string, len(lines))
	for i, ln := range lines {
		if strings.TrimSpace(ln) == "" {
			out[i] = style.Render("")
		} else {
			out[i] = style.Render(ln)
		}
	}
	return strings.Join(out, "\n")
}

func renderCapabilitiesBlock(m model, width int) string {
	t := Theme()
	bg := lipgloss.Color(ColorCanvas)
	label := t.StyleLabel.Copy().Background(bg)
	dim := t.StyleDim.Copy().Background(bg)
	tools := m.sessionToolNames
	if len(tools) == 0 {
		tools = defaultSessionTools(m.useAgentTools)
	}
	skills := m.sessionSkillNames

	var lines []string
	lines = append(lines, label.Render("Available Tools"))
	for _, line := range formatToolGroups(tools, width) {
		lines = append(lines, dim.Render("  "+line))
	}
	lines = append(lines, "")
	lines = append(lines, label.Render("Available Skills"))
	if len(skills) == 0 {
		lines = append(lines, dim.Render("  (no published skills)"))
	} else {
		for _, line := range formatSkillList(skills, width) {
			lines = append(lines, dim.Render("  "+line))
		}
	}
	if m.activeAgentName != "" {
		lines = append(lines, "")
		lines = append(lines, label.Render("Agent  ")+dim.Render(m.activeAgentName))
	}
	lines = append(lines, "")
	lines = append(lines, dim.Render(fmt.Sprintf(
		"%d tools · %d skills · /help for commands",
		len(tools), len(skills),
	)))
	return strings.Join(lines, "\n")
}

func defaultSessionTools(enabled bool) []string {
	if !enabled {
		return []string{"(Plan mode — tools off until Build)"}
	}
	return []string{
		"file_read", "file_write", "file_list",
		"shell_run", "grep_search",
		"web_fetch",
	}
}

func groupToolNames(names []string) map[string][]string {
	groups := map[string][]string{}
	order := []string{}
	for _, n := range names {
		fam := n
		short := n
		if idx := strings.Index(n, "_"); idx > 0 {
			fam = n[:idx]
			short = n[idx+1:]
		}
		if _, ok := groups[fam]; !ok {
			order = append(order, fam)
		}
		groups[fam] = append(groups[fam], short)
	}
	sort.Strings(order)
	out := make(map[string][]string, len(groups))
	for _, fam := range order {
		out[fam] = groups[fam]
	}
	return out
}

func formatToolGroups(names []string, width int) []string {
	if len(names) == 1 && strings.HasPrefix(names[0], "(") {
		return names
	}
	groups := groupToolNames(names)
	fams := make([]string, 0, len(groups))
	for fam := range groups {
		fams = append(fams, fam)
	}
	sort.Strings(fams)
	var lines []string
	for _, fam := range fams {
		line := fam + ": " + strings.Join(groups[fam], ", ")
		lines = append(lines, trim(line, width-2))
		if len(lines) >= 6 {
			lines = append(lines, "…")
			break
		}
	}
	if len(lines) == 0 {
		return []string{"(loading…)"}
	}
	return lines
}

func formatSkillList(names []string, width int) []string {
	if len(names) == 0 {
		return nil
	}
	sort.Strings(names)
	var lines []string
	var row []string
	rowLen := 0
	for _, name := range names {
		part := name
		if rowLen+len(part)+2 > width-2 && len(row) > 0 {
			lines = append(lines, strings.Join(row, ", "))
			row = nil
			rowLen = 0
		}
		row = append(row, part)
		rowLen += len(part) + 2
		if len(lines) >= 5 {
			break
		}
	}
	if len(row) > 0 && len(lines) < 6 {
		lines = append(lines, strings.Join(row, ", "))
	}
	if len(names) > 6 {
		lines = append(lines, fmt.Sprintf("… +%d", len(names)-6))
	}
	return lines
}

func sidebarLabel(text string) string {
	return Theme().StyleLabel.Render(text)
}

func sidebarRow(label, value string) string {
	return sidebarLabel(label) + Theme().StyleDim.Render("  "+value)
}
