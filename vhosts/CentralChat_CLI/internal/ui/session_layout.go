package ui

import (
	"fmt"
	"math"
	"os"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/charmbracelet/lipgloss"
	"github.com/centralchurch/central-cli/internal/config"
	"github.com/centralchurch/central-cli/internal/solo"
	"github.com/centralchurch/central-cli/internal/version"
)

type interactionMode string

const (
	modeBuild     interactionMode = "build"
	modePlan      interactionMode = "plan"
	modeDebug     interactionMode = "debug"
	modeMultitask interactionMode = "multitask"
	modeAsk       interactionMode = "ask"
)

var interactionModeOrder = []interactionMode{
	modeBuild, modePlan, modeDebug, modeMultitask, modeAsk,
}

func modeDisplayName(mode interactionMode) string {
	switch mode {
	case modePlan:
		return "Plan"
	case modeDebug:
		return "Debug"
	case modeMultitask:
		return "Multitask"
	case modeAsk:
		return "Ask"
	default:
		return "Build"
	}
}

func modeInputChipAndBar(mode interactionMode) (chip lipgloss.Style, bar lipgloss.Color) {
	switch mode {
	case modePlan:
		return lipgloss.NewStyle().Foreground(lipgloss.Color("214")).Bold(true), lipgloss.Color("214")
	case modeDebug:
		return lipgloss.NewStyle().Foreground(lipgloss.Color("1")).Bold(true), lipgloss.Color("1")
	case modeMultitask:
		return lipgloss.NewStyle().Foreground(lipgloss.Color("135")).Bold(true), lipgloss.Color("135")
	case modeAsk:
		return lipgloss.NewStyle().Foreground(lipgloss.Color("42")).Bold(true), lipgloss.Color("42")
	default:
		return lipgloss.NewStyle().Foreground(lipgloss.Color(ColorTextDim)).Bold(true), lipgloss.Color(ColorTextDim)
	}
}

func (m *model) applyInteractionMode(mode interactionMode) {
	m.interactionMode = mode
	switch mode {
	case modePlan:
		m.useAgentTools = false
		m.input.Placeholder = "Planeia antes de codar…"
	case modeAsk:
		m.useAgentTools = false
		m.input.Placeholder = "Pergunta… (/help)"
	case modeDebug:
		m.useAgentTools = true
		m.input.Placeholder = "Debug… (/help)"
	case modeMultitask:
		m.useAgentTools = true
		m.input.Placeholder = "Multitask… (/help)"
	default:
		m.useAgentTools = true
		m.input.Placeholder = "Mensagem… (/help)"
	}
}

func (m *model) toggleInteractionMode() {
	for i, mode := range interactionModeOrder {
		if m.interactionMode == mode {
			next := interactionModeOrder[(i+1)%len(interactionModeOrder)]
			m.applyInteractionMode(next)
			return
		}
	}
	m.applyInteractionMode(modeBuild)
}

func unifiedSessionHeaderRows(hasConfirm bool) int {
	rows := 4 // title + ws tabs + session tabs + separator
	if hasConfirm {
		rows++
	}
	return rows
}



func isHeaderSeparatorLine(line string) bool {
	return strings.Contains(line, "─")
}

// renderSessionHeaderPanel renders title + tabs on the black session canvas.
func renderSessionHeaderPanel(width int, sessionTitle string, wf workspacesFile, sessions []openSession, activeSessionIdx int, tabCloseConfirmID string, runtimeBadge string, wsConnected bool) string {
	raw := strings.TrimRight(renderUnifiedSessionHeader(width, sessionTitle, wf, sessions, activeSessionIdx, tabCloseConfirmID, runtimeBadge, wsConnected), "\n")
	if raw == "" {
		return ""
	}
	t := Theme()
	canvas := chatCanvasStyle()
	gutter := contentGutter(width)
	lines := strings.Split(raw, "\n")
	var content []string
	for _, ln := range lines {
		if isHeaderSeparatorLine(ln) {
			continue
		}
		content = append(content, ln)
	}
	top := renderStyledColumn(strings.Join(content, "\n"), width, len(content), gutter, canvas)
	sep := fillRowWidth(width, t.StyleSeparator.Render(strings.Repeat("─", width)), canvas)
	return top + "\n" + sep
}

func (m model) rightPanelWidth() int {
	w := sessionInnerWidth(m.width) * 30 / 100
	if w < 28 {
		w = 28
	}
	if w > 36 {
		w = 36
	}
	if m.tuiCfg.SidebarWidthCols > 12 && m.tuiCfg.SidebarWidthCols != DefaultTUIConfig().SidebarWidthCols {
		w = m.tuiCfg.SidebarWidthCols
	}
	return w
}

func (m model) contentHeight() int {
	header := m.chromeRows
	if header <= 0 {
		header = unifiedSessionHeaderRows(false)
	}
	h := m.height - header - 2*sessionFrameMargin
	if h < 8 {
		return 8
	}
	return h
}

func appendSidebarSection(lines []string, label string, values ...string) []string {
	lines = append(lines, sidebarLabel(label))
	for _, v := range values {
		if v != "" {
			lines = append(lines, "  "+v)
		}
	}
	lines = append(lines, "")
	return lines
}

func (m model) contextLimitTokens() int {
	used := m.tokensIn + m.tokensOut
	if m.contextPct > 0 && used > 0 {
		limit := (used * 100) / m.contextPct
		if limit >= used {
			return limit
		}
	}
	return 128_000
}

const panelBgColor = ColorSurface

func panelAccent() lipgloss.Style {
	return Theme().StyleAccent.Copy().Background(lipgloss.Color(panelBgColor))
}

func panelLabel() lipgloss.Style {
	return Theme().StyleLabel.Copy().Background(lipgloss.Color(panelBgColor))
}

func panelDim() lipgloss.Style {
	return Theme().StyleDim.Copy().Background(lipgloss.Color(panelBgColor))
}

func panelSep() lipgloss.Style {
	return Theme().StyleSeparator.Copy().Background(lipgloss.Color(panelBgColor))
}

func panelFill() lipgloss.Style {
	return lipgloss.NewStyle().Background(lipgloss.Color(panelBgColor))
}

// panelRow renders "LABEL  value" with consistent #0b0b14 backgrounds.
func panelRow(label, value string) string {
	return panelLabel().Render("  "+label+"  ") + panelDim().Render(value)
}

// panelSection adds a separator + section title.
func panelSection(lines []string, pw int, title string) []string {
	lines = append(lines, "")
	lines = append(lines, panelSep().Render(strings.Repeat("─", pw-4))+" "+panelLabel().Render(title))
	return lines
}

func (m model) renderRightPanel(contentH int) string {
	pw := m.rightPanelWidth()
	title := trim(m.displayTurnTitle(), pw-4)
	if title == "" {
		title = "Session"
	}
	provider := extractProvider(m.activeModelDisplay())

	var lines []string

	// Title
	lines = append(lines, "")
	lines = append(lines, panelAccent().Bold(true).Render("  "+title))
	lines = append(lines, panelSep().Render(strings.Repeat("─", pw)))

	if m.activeAgentName != "" {
		lines = append(lines, panelRow("Agent", m.activeAgentName))
	}
	if len(m.sessionSkillNames) > 0 {
		skills := strings.Join(m.sessionSkillNames, ", ")
		lines = append(lines, panelRow("Skills", trim(skills, pw-10)))
	}

	lines = panelSection(lines, pw, "Model")
	modelDisplay := m.activeModelDisplay()
	if modelDisplay == "" {
		modelDisplay = "(none)"
	}
	lines = append(lines, panelAccent().Bold(true).Render("  "+trim(modelDisplay, pw-4)))

	var metaParts []string
	if provider != "" {
		metaParts = append(metaParts, provider)
	}
	if m.autoTier != "" && m.sessionModelOverride == "" {
		metaParts = append(metaParts, "tier "+m.autoTier)
	}
	if m.providerRouting != "" {
		metaParts = append(metaParts, "route "+m.providerRouting)
	}
	if len(metaParts) > 0 {
		lines = append(lines, panelDim().Render("  "+strings.Join(metaParts, " · ")))
	}

	var paramParts []string
	if m.temperature > 0 {
		paramParts = append(paramParts, fmt.Sprintf("temp %.1f", m.temperature))
	}
	if m.effort != "" {
		paramParts = append(paramParts, "effort "+m.effort)
	}
	if m.thinkingBudget > 0 {
		paramParts = append(paramParts, fmt.Sprintf("thinking %dK", m.thinkingBudget/1000))
	}
	if len(paramParts) > 0 {
		lines = append(lines, panelDim().Render("  "+strings.Join(paramParts, " · ")))
	}

	lines = panelSection(lines, pw, "Usage")
	ctxBarW := 10
	ctxLine := panelLabel().Render("  Context  ") + renderContextBar(m.contextPct, ctxBarW)
	ctxLine += "  " + panelDim().Render(fmt.Sprintf("%d%%", m.contextPct))
	lines = append(lines, ctxLine)
	tokenStr := formatTokensK(m.tokensIn+m.tokensOut) + " / " + formatTokensK(m.contextLimitTokens())
	lines = append(lines, panelDim().Render("    "+tokenStr+" tokens"))
	lines = append(lines, panelRow("Turn", renderDuration(m.lastTurnDuration)))
	lines = append(lines, panelRow("Session", renderDuration(m.sessionElapsed())))
	lines = append(lines, panelRow("Cost", formatCost(m.usageTotalCost)))

	if m.workspace != "" {
		lines = append(lines, "")
		wsLine := formatWorkspacePath(m.workspace, m.branch)
		lines = append(lines, panelDim().Render("  "+trim(wsLine, pw-4)))
	}

	var badges []string
	if m.connectorOnline {
		badges = append(badges, panelAccent().Render("online"))
	}
	if m.pendingCount > 0 {
		badges = append(badges, fmt.Sprintf("%d pending", m.pendingCount))
	}
	badges = append(badges, "v"+version.Version)
	if len(badges) > 0 {
		lines = append(lines, "")
		lines = append(lines, panelDim().Render("  "+strings.Join(badges, " · ")))
	}

	// Runtime section (SOLO mode)
	if m.runtime.Runtime == config.ModeSolo {
		lines = append(lines, "")
		lines = append(lines, panelSep().Render(strings.Repeat("─", pw)))
		lines = append(lines, panelAccent().Bold(true).Render("  SOLO Runtime"))

		// Provider + model (prominent)
		if m.soloAgent != nil && m.soloAgent.Provider != nil {
			providerName := formatProviderName(string(m.soloAgent.Provider.Kind))
			lines = append(lines, panelAccent().Bold(true).Render("  "+providerName+" · "+m.soloAgent.Provider.Model))
		} else {
			lines = append(lines, panelDim().Render("  Provider: not configured"))
		}
		lines = append(lines, "")

		if m.runtimeSnap != nil {
			lines = append(lines, panelDim().Render(fmt.Sprintf("  CPU: %.0f%%  MEM: %.1f/%.1f GB",
				m.runtimeSnap.CPUPercent, m.runtimeSnap.MemUsedGB, m.runtimeSnap.MemTotalGB)))

			if len(m.runtimeSnap.ActiveTools) > 0 {
				lines = append(lines, panelDim().Render("  Active:"))
				for _, t := range m.runtimeSnap.ActiveTools {
					elapsed := time.Since(t.StartTime).Truncate(time.Second)
					lines = append(lines, panelDim().Render(fmt.Sprintf("    ⏳ %-14s %s  [%v]",
						t.Name, t.Args, elapsed)))
				}
			}

			if len(m.runtimeSnap.RecentTools) > 0 {
				lines = append(lines, panelDim().Render("  Recent:"))
				for _, r := range m.runtimeSnap.RecentTools {
					icon := " ✓"
					if r.Error != "" {
						icon = " ✗"
					}
					lines = append(lines, panelDim().Render(fmt.Sprintf("   %s %s", icon, r.Name)))
				}
			}

			if len(m.runtimeSnap.Background) > 0 {
				active := 0
				for _, bg := range m.runtimeSnap.Background {
					if !bg.Done {
						active++
					}
				}
				if active > 0 {
					lines = append(lines, panelDim().Render(fmt.Sprintf("  Background (%d):", active)))
					for _, bg := range m.runtimeSnap.Background {
						if !bg.Done {
							elapsed := time.Since(bg.StartTime).Truncate(time.Second)
							lines = append(lines, panelDim().Render(fmt.Sprintf("    ● %s  [%v]",
								bg.Command, elapsed)))
						}
					}
				}
			}
		} else {
			lines = append(lines, panelDim().Render("  (initializing...)"))
		}

		// Workspace
		lines = append(lines, panelDim().Render(fmt.Sprintf("  Workspace: %s", trim(shortPath(m.runtime.WorkspacePath, 2), pw-14))))
		// Sessions
		sessions, _ := solo.ListSessions()
		lines = append(lines, panelDim().Render(fmt.Sprintf("  Sessions: %d local", len(sessions))))
	}

	// TEAM section
	if m.runtime.Runtime == config.ModeTeam {
		lines = append(lines, "")
		lines = append(lines, panelSep().Render(strings.Repeat("─", pw)))
		lines = append(lines, panelAccent().Bold(true).Render("  TEAM Status"))

		// WS connection status with colored dot
		dotIcon := "●"
		dotColor := lipgloss.Color("1") // red
		wsStatus := "disconnected"
		if m.connectorOnline {
			dotColor = lipgloss.Color("2") // green
			wsStatus = "connected"
		}
		dot := lipgloss.NewStyle().Foreground(dotColor).Bold(true).Render(dotIcon)
		lines = append(lines, panelAccent().Bold(true).Render(fmt.Sprintf("  %s WS: %s", dot, wsStatus)))

		// VPS URL (prominent)
		if m.runtimeSnap != nil && m.runtimeSnap.WSUrl != "" {
			url := m.runtimeSnap.WSUrl
			displayURL := strings.TrimPrefix(url, "wss://")
			displayURL = strings.TrimPrefix(displayURL, "ws://")
			lines = append(lines, panelDim().Render(fmt.Sprintf("  API: %s", trim(displayURL, pw-8))))
		} else if m.client != nil {
			apiURL := m.client.BaseURL
			displayURL := strings.TrimPrefix(apiURL, "https://")
			displayURL = strings.TrimPrefix(displayURL, "http://")
			lines = append(lines, panelDim().Render(fmt.Sprintf("  API: %s", trim(displayURL, pw-8))))
		}
		lines = append(lines, "")

		// Provider + model (prominent)
		if m.soloAgent != nil && m.soloAgent.Provider != nil {
			providerName := formatProviderName(string(m.soloAgent.Provider.Kind))
			lines = append(lines, panelAccent().Bold(true).Render("  "+providerName+" · "+m.soloAgent.Provider.Model))
		} else {
			lines = append(lines, panelDim().Render("  Provider: VPS-assigned"))
		}
		lines = append(lines, "")

		// Plan metrics
		if m.runtimeSnap != nil && m.runtimeSnap.PlanCount > 0 {
			latency := fmt.Sprintf("%dms", m.runtimeSnap.LastPlanLatencyMs)
			lines = append(lines, panelDim().Render(fmt.Sprintf("  Plans: %d | last: %s",
				m.runtimeSnap.PlanCount, latency)))
		}

		// Policy status
		if m.runtimeSnap != nil {
			policyStatus := "not loaded"
			if m.runtimeSnap.PolicyLoaded {
				policyStatus = "loaded"
			}
			policyIcon := "✗"
			if m.runtimeSnap.PolicyLoaded {
				policyIcon = "✓"
			}
			lines = append(lines, panelDim().Render(fmt.Sprintf("  %s Policy: %s", policyIcon, policyStatus)))
		}
	}

	if len(lines) > contentH {
		lines = lines[:contentH]
	}
	for len(lines) < contentH {
		lines = append(lines, "")
	}
	return enforceBackground(strings.Join(lines, "\n"), pw, ColorSurface)
}

func extractProvider(modelName string) string {
	// Extract provider from model name like "openrouter/anthropic/claude-sonnet-4"
	parts := strings.SplitN(modelName, "/", 2)
	if len(parts) >= 1 && parts[0] != "" {
		return parts[0]
	}
	return ""
}

// formatProviderName returns a human-readable provider name from its kind.
func formatProviderName(kind string) string {
	switch kind {
	case "openrouter":
		return "OpenRouter"
	case "openai":
		return "OpenAI"
	case "anthropic":
		return "Anthropic"
	case "llamacpp":
		return "llama.cpp"
	case "deepseek":
		return "DeepSeek"
	case "openai_compatible":
		return "Custom API"
	default:
		return kind
	}
}

func formatCost(v float64) string {
	if v <= 0 {
		return "$0"
	}
	if v < 0.01 {
		return fmt.Sprintf("$%.4f", v)
	}
	if v < 1.0 {
		return fmt.Sprintf("$%.3f", v)
	}
	return fmt.Sprintf("$%.2f", v)
}

func formatWorkspacePath(path, branch string) string {
	if path == "" {
		return ""
	}
	display := path
	if home, err := os.UserHomeDir(); err == nil && strings.HasPrefix(path, home) {
		display = "~" + strings.TrimPrefix(path, home)
	}
	if branch != "" && branch != "unknown" {
		display += ":" + branch
	}
	return display
}

func (m model) sessionElapsed() time.Duration {
	if m.sessionStartedAt.IsZero() {
		return 0
	}
	return time.Since(m.sessionStartedAt)
}

func (m model) renderChatColumn(contentH int) string {
	cw := m.chatWidth()
	inset := contentInset(sessionInnerWidth(m.width))
	innerCW := chatContentWidth(cw, inset)

	footerLines := m.buildChatFooterLines(cw, inset)
	footerH := len(footerLines)
	msgH := contentH - footerH
	if msgH < 1 {
		msgH = 1
		if footerH > contentH-1 {
			footerLines = footerLines[len(footerLines)-(contentH-1):]
			footerH = len(footerLines)
		}
	}

	msgContent := m.buildMessageArea(innerCW, msgH)
	canvas := chatCanvasStyle()

	var rows []string
	for _, vl := range msgContent {
		ln := indentWithGutter(vl.text, inset)
		if vl.assistant {
			rows = append(rows, paintAssistantRow(cw, ln))
		} else {
			rows = append(rows, fillRowWidth(cw, ln, canvas))
		}
	}
	for len(rows) < msgH {
		rows = append(rows, canvas.Width(cw).Render(""))
	}
	for _, ln := range footerLines {
		rows = append(rows, fillRowWidth(cw, ln, canvas))
	}
	for len(rows) < contentH {
		rows = append(rows, canvas.Width(cw).Render(""))
	}
	if len(rows) > contentH {
		rows = rows[:contentH]
	}
	return enforceScreenBG(strings.Join(rows, "\n"), cw)
}

func (m *model) buildMessageArea(innerCW, msgH int) []chatViewportLine {
	if m.isEmptyConversation() && !m.streaming && m.approval == nil && m.clarify == nil {
		m.visibleTurnUserIdx = -1
		msgArea := m.renderSessionEmptyState(innerCW)
		emptyLines := strings.Split(msgArea, "\n")
		if len(emptyLines) < msgH {
			topPad := (msgH - len(emptyLines)) / 4
			if topPad < 1 {
				topPad = 1
			}
			padded := make([]chatViewportLine, msgH)
			for i := topPad; i < msgH && i-topPad < len(emptyLines); i++ {
				padded[i] = chatViewportLine{text: emptyLines[i-topPad]}
			}
			return padded
		}
		if len(emptyLines) > msgH {
			emptyLines = emptyLines[:msgH]
		}
		out := make([]chatViewportLine, len(emptyLines))
		for i, ln := range emptyLines {
			out[i] = chatViewportLine{text: ln}
		}
		return out
	}

	sticky, scrollable := m.buildChatLayout(innerCW)
	offset := m.chatScrollOffset
	maxOff := maxChatScrollOffset(sticky, scrollable, msgH)
	if offset > maxOff {
		offset = maxOff
	}
	if offset < 0 {
		offset = 0
	}

	// Determine visible turn: first user message in the visible scrollable range
	m.visibleTurnUserIdx = visibleTurnFromScrollable(scrollable, offset)
	return layoutStickyChatViewport(sticky, scrollable, msgH, offset)
}

// visibleTurnFromScrollable finds the user message index for the turn visible at the given offset.
func visibleTurnFromScrollable(scrollable []chatViewportLine, offset int) int {
	if offset < 0 || offset >= len(scrollable) {
		return -1
	}
	// Walk forward from offset to find first line with a valid turn tag
	for i := offset; i < len(scrollable); i++ {
		if scrollable[i].turnUserIdx >= 0 {
			return scrollable[i].turnUserIdx
		}
	}
	// Walk backward from offset as fallback
	for i := offset - 1; i >= 0; i-- {
		if scrollable[i].turnUserIdx >= 0 {
			return scrollable[i].turnUserIdx
		}
	}
	return -1
}

func (m model) buildChatFooterLines(cw, inset int) []string {
	t := Theme()
	var lines []string
	if m.toolsPickerOpen {
		innerW := chatContentWidth(cw, inset)
		pickerLines := strings.Split(m.viewToolsPicker(innerW), "\n")
		maxH := max(8, m.contentHeight()-6)
		if len(pickerLines) > maxH {
			pickerLines = pickerLines[:maxH]
		}
		for _, ln := range pickerLines {
			lines = append(lines, indentWithGutter(ln, inset))
		}
	}
	if m.agentPickerOpen {
		innerW := chatContentWidth(cw, inset)
		pickerLines := strings.Split(m.viewAgentPicker(innerW), "\n")
		maxH := max(8, m.contentHeight()-6)
		if len(pickerLines) > maxH {
			pickerLines = pickerLines[:maxH]
		}
		for _, ln := range pickerLines {
			lines = append(lines, indentWithGutter(ln, inset))
		}
	}
	if m.modelPickerOpen {
		innerW := chatContentWidth(cw, inset)
		pickerLines := strings.Split(m.viewModelPicker(innerW), "\n")
		maxH := max(8, m.contentHeight()-6)
		if len(pickerLines) > maxH {
			pickerLines = pickerLines[:maxH]
		}
		for _, ln := range pickerLines {
			lines = append(lines, indentWithGutter(ln, inset))
		}
	}
	if m.paramsPickerOpen {
		innerW := chatContentWidth(cw, inset)
		pickerLines := strings.Split(m.viewParamsPicker(innerW), "\n")
		maxH := max(8, m.contentHeight()-6)
		if len(pickerLines) > maxH {
			pickerLines = pickerLines[:maxH]
		}
		for _, ln := range pickerLines {
			lines = append(lines, indentWithGutter(ln, inset))
		}
	}
	if m.slashPaletteOpen {
		for _, ln := range strings.Split(m.viewSlashPalette(), "\n") {
			lines = append(lines, indentWithGutter(ln, inset))
		}
	}
	if m.shouldShowChatStats() {
		stat := t.StyleDim.Render(m.chatStatsLine())
		innerW := chatContentWidth(cw, inset)
		statLine := lipgloss.NewStyle().Width(innerW).Align(lipgloss.Right).Render(stat)
		lines = append(lines, indentWithGutter(statLine, inset))
	}
	for _, ln := range strings.Split(m.renderInputBox(cw, inset), "\n") {
		if ln != "" {
			lines = append(lines, indentWithGutter(ln, inset))
		}
	}
	lines = append(lines, indentWithGutter(t.StyleDim.Render(sessionFooterHint(cw)), inset))
	return lines
}

func sessionFooterHint(cw int) string {
	if cw < 48 {
		return "Tab cycle mode · Ctrl+N new"
	}
	if cw < 72 {
		return "Ctrl+N new · Ctrl+Tab workspace · Tab cycle mode"
	}
	return "Ctrl+N new · Ctrl+Tab workspace · Tab cycle mode · Ctrl+Shift+C copy"
}

func (m model) shouldShowChatStats() bool {
	return false // Stats now in sidebar Runtime section
}

func (m model) chatStatsLine() string {
	tokensK := formatTokensK(m.tokensIn + m.tokensOut)
	return fmt.Sprintf("%s (%d%%)", tokensK, m.contextPct)
}

func (m model) renderInputBox(cw, inset int) string {
	chip, barColor := modeInputChipAndBar(m.interactionMode)
	modeName := modeDisplayName(m.interactionMode)

	boxW := chatContentWidth(cw, inset)
	innerTextW := boxW - 6 // border + padding + prompt
	if innerTextW < 16 {
		innerTextW = 16
	}

	// During streaming, reserve right portion for spinner
	spinnerW := 0
	if m.streaming && boxW >= 50 {
		spinnerW = 16 // room for 7-wide circle + padding
		innerTextW -= spinnerW + 1 // +1 gap
	}
	if innerTextW < 16 {
		innerTextW = 16
	}

	// Always render at max height so the textarea viewport stays at Y=0.
	// Then clip to the actual display height — avoids viewport scroll bugs.
	ta := m.input
	ta.SetWidth(innerTextW)
	ta.SetHeight(sessionInputMaxLines)
	fullView := ta.View()

	displayH := m.inputDisplayHeight(innerTextW)
	textLines := strings.Split(fullView, "\n")
	if displayH < len(textLines) {
		textLines = textLines[:displayH]
	}
	for len(textLines) < displayH {
		textLines = append(textLines, "")
	}

	// Spinner needs at least 9 lines: 4 above + center + 4 below.
	// Pad textLines to match.
	spinH := displayH
	if m.streaming && spinnerW > 0 {
		if spinH < 9 {
			spinH = 9
			for len(textLines) < spinH {
				textLines = append(textLines, "")
			}
		}
	}

	// Render spinner during streaming
	var spinLines []string
	if m.streaming && spinnerW > 0 {
		spinLines = renderSpinner(spinnerW, spinH, m.spinnerFrame, barColor)
	}

	// Combine textarea + spinner side by side
	nLines := len(textLines)
	if len(spinLines) > nLines {
		nLines = len(spinLines)
	}
	var combined []string
	for i := 0; i < nLines; i++ {
		left := ""
		if i < len(textLines) {
			left = textLines[i]
		}
		right := ""
		if i < len(spinLines) {
			right = spinLines[i]
		}
		combined = append(combined, left+right)
	}
	inputView := strings.Join(combined, "\n")

	meta := chip.Render(modeName)

	// Gradient bar: mode color → black
	gradient := renderGradient(boxW, barColor)

	// Gradient first, then textarea+spinner, blank line, then mode chip
	inner := gradient + "\n" + inputView + "\n\n" + meta

	boxStyle := lipgloss.NewStyle().
		Border(lipgloss.Border{Left: "▌"}).
		BorderForeground(barColor).
		Foreground(lipgloss.Color(ColorText)).
		Padding(0, 1).
		Width(boxW)

	return boxStyle.Render(inner)
}

// renderSpinner draws a rotating gradient ring using true-color ANSI backgrounds.
// The ring fills width×height cells; the gradient color rotates each frame.
// Aspect ratio is corrected (terminal chars are ~2× taller than wide).
func renderSpinner(width, height, frame int, startColor lipgloss.Color) []string {
	if width < 4 || height < 2 {
		return nil
	}

	r, g, b := hexToRGB(string(startColor))
	cx := float64(width)/2.0 - 0.5
	cy := float64(height)/2.0 - 0.5
	// Outer circle radius — uses aspect-corrected effective height
	// (dy is scaled ×2, so effective height = height*2)
	effH := float64(height) * 2.0
	outerR := math.Min(float64(width), effH)/2.0 - 0.8
	if outerR < 1.2 {
		outerR = 1.2
	}
	// Black inner circle: fixed radius 3
	innerR := 3.0
	if innerR >= outerR-0.3 {
		innerR = outerR * 0.7 // fallback if spinner too small
	}
	ringW := outerR - innerR // colored gradient ring
	// 8 frames per full rotation
	rot := float64(frame%8) / 8.0

	var lines []string
	for row := 0; row < height; row++ {
		var line strings.Builder
		line.WriteString("\x1b[0m") // reset any open styling from textarea
		for col := 0; col < width; col++ {
			dx := float64(col) - cx
			dy := (float64(row) - cy) * 2.0     // aspect ratio correction
			dist := math.Sqrt(dx*dx + dy*dy)     // Euclidean = circle

			if dist > innerR && dist <= outerR {
				angle := math.Atan2(dy, dx)
				angularNorm := (angle + math.Pi) / (2.0 * math.Pi)
				angularNorm = math.Mod(angularNorm+rot, 1.0)
				// Falloff from inner edge (0) to outer edge (1)
				radialAlpha := (dist - innerR) / ringW
				if radialAlpha > 1.0 {
					radialAlpha = 1.0
				}
				brightness := radialAlpha * (1.0 - angularNorm)
				rr := uint8(float64(r) * brightness)
				gg := uint8(float64(g) * brightness)
				bb := uint8(float64(b) * brightness)
				line.WriteString(fmt.Sprintf("\x1b[48;2;%d;%d;%dm \x1b[0m", rr, gg, bb))
			} else {
				line.WriteString(" ")
			}
		}
		lines = append(lines, line.String())
	}
	return lines
}

// renderGradient returns a row of spaces with background colors fading from
// the mode color to pure black via alpha blending. The gradient spans 30%
// of the width. Uses true color ANSI for perfectly smooth transitions.
func renderGradient(width int, startColor lipgloss.Color) string {
	if width < 10 {
		return ""
	}
	gradW := width * 30 / 100
	if gradW < 6 {
		gradW = 6
	}

	// Parse hex color to RGB
	hex := string(startColor)
	r, g, b := hexToRGB(hex)

	var out strings.Builder
	for col := 0; col < width; col++ {
		if col < gradW {
			alpha := float64(col) / float64(gradW)
			rr := uint8(float64(r) * (1 - alpha))
			gg := uint8(float64(g) * (1 - alpha))
			bb := uint8(float64(b) * (1 - alpha))
			out.WriteString(fmt.Sprintf("\x1b[48;2;%d;%d;%dm \x1b[0m", rr, gg, bb))
		} else {
			out.WriteString("\x1b[48;5;16m \x1b[0m")
		}
	}
	return out.String()
}

// hexToRGB parses a hex color like "214" (256-color), "#3399ff", or "39" to RGB.
func hexToRGB(hex string) (r, g, b int) {
	// Try 256-color name lookup first
	switch hex {
	case "214", "208":
		return 255, 170, 0 // orange
	case "1", "196":
		return 255, 51, 51 // red
	case "135":
		return 175, 95, 255 // purple
	case "42", "46":
		return 0, 204, 102 // green
	case "39":
		return 51, 153, 255 // blue
	default:
		// Try hex parse
		if len(hex) > 0 && hex[0] == '#' {
			hex = hex[1:]
		}
		if len(hex) == 6 {
			fmt.Sscanf(hex, "%02x%02x%02x", &r, &g, &b)
		} else {
			r, g, b = 51, 153, 255 // default blue
		}
	}
	return
}

func (m model) inputDisplayHeight(innerTextW int) int {
	if m.input.Value() == "" {
		return sessionInputMinLines
	}
	if innerTextW < 1 {
		innerTextW = 1
	}

	total := 0
	for _, line := range strings.Split(m.input.Value(), "\n") {
		if line == "" {
			total++
			continue
		}
		// Count runes, not bytes, for accurate display width
		rc := utf8.RuneCountInString(line)
		dl := (rc + innerTextW - 1) / innerTextW
		if dl < 1 {
			dl = 1
		}
		total += dl
	}
	if total < sessionInputMinLines {
		total = sessionInputMinLines
	}
	if total > sessionInputMaxLines {
		total = sessionInputMaxLines
	}
	return total
}

func renderApprovalCard(ap *approvalCard, cw int) string {
	t := Theme()
	var lines []string
	lines = append(lines, t.StyleDim.Render("Approval"))
	if ap.Command != "" {
		lines = append(lines, "  "+ap.Command)
	} else if ap.Summary != "" {
		lines = append(lines, "  "+ap.Summary)
	} else if ap.Path != "" {
		lines = append(lines, "  "+ap.Path)
	}
	lines = append(lines, t.StyleDim.Render("  [a] approve  [D] diff  [r] reject"))
	return t.StyleCard.Width(cw - 2).Render(strings.Join(lines, "\n"))
}

func renderClarifyCard(cl *clarifyCard, cw int) string {
	t := Theme()
	var lines []string
	lines = append(lines, t.StyleDim.Render("Clarify"))
	lines = append(lines, "  "+wrap(cl.Question, cw-6))
	for i, ch := range cl.Choices {
		if i >= 4 {
			break
		}
		lines = append(lines, fmt.Sprintf("  [%d] %s", i+1, trim(ch, cw-10)))
	}
	lines = append(lines, t.StyleDim.Render("  [o] Outro…"))
	return t.StyleCard.Width(cw - 2).Render(strings.Join(lines, "\n"))
}

func (m model) compactMetricsFooter() string {
	return ""
}

func (m model) footerHints() string {
	return ""
}

func toggleReasoningInPanel(cur string) string {
	if cur == "open" {
		return "collapsed"
	}
	return "open"
}

func normalizeReasoningPanel(cur string) string {
	if cur == "hidden" || cur == "" {
		return "collapsed"
	}
	return cur
}

func renderSessionTopBar(width int, sessionTitle string, onLogoutHint bool) string {
	wf := workspacesFile{}
	return renderUnifiedSessionHeader(width, sessionTitle, wf, nil, -1, "", "", false)
}
