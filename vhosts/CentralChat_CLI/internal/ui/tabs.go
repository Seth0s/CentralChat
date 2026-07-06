package ui

import (
	"os"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/centralchurch/central-cli/internal/config"
)

type workspacesSyncedMsg struct {
	wf  workspacesFile
	err error
}

type sessionTabCreatedMsg struct {
	SessionID string
	Title     string
}

type tabActivatedMsg struct {
	wf workspacesFile
}

func (m rootModel) syncWorkspacesCmd() tea.Cmd {
	client := m.client
	wf := m.workspaces
	return func() tea.Msg {
		if client == nil {
			return workspacesSyncedMsg{wf: wf}
		}
		merged, err := SyncWorkspacesFromServer(client)
		return workspacesSyncedMsg{wf: merged, err: err}
	}
}

func (m rootModel) activateTabCmd(id string) tea.Cmd {
	client := m.client
	cfg := m.cfg
	wf := m.workspaces
	return func() tea.Msg {
		wf, tab := ActivateWorkspaceTab(wf, id)
		if tab == nil {
			return tabActivatedMsg{wf: wf}
		}
		if cfg != nil {
			cfg.WorkspacePath = tab.Path
		}
		if client != nil {
			_ = client.BindWorkspace(tab.Path)
			_ = SyncWorkspacesToServer(client, wf)
		}
		return tabActivatedMsg{wf: wf}
	}
}

func (m rootModel) closeTabCmd(id string) tea.Cmd {
	client := m.client
	wf := CloseWorkspaceTab(id)
	return func() tea.Msg {
		if client != nil {
			_ = SyncWorkspacesToServer(client, wf)
		}
		return tabActivatedMsg{wf: wf}
	}
}

const newSessionTabLabel = "[ + New session ]"

func sessionTabsBarRowY() int {
	// applySessionFrame top margin + title row (tabs are the second header line).
	return sessionFrameMargin + 1
}

func (m rootModel) sessionTabsBarStartX() int {
	return sessionFrameMargin + contentGutter(sessionInnerWidth(m.width))
}

func workspaceTabRenderedWidth(tab WorkspaceTab, active bool) int {
	t := Theme()
	label := tab.Label + " ×"
	var rendered string
	if active {
		rendered = t.StyleTabHeaderActive.Render(label)
	} else {
		rendered = styleOnChatCanvas(t.StyleTabHeader).Render(label)
	}
	return lipgloss.Width(rendered)
}

func newSessionTabButtonWidth() int {
	t := Theme()
	return lipgloss.Width(styleOnChatCanvas(t.StyleDim).Render(newSessionTabLabel))
}

func tabBarGapWidth() int {
	return lipgloss.Width(chatCanvasSpace())
}

func (m rootModel) addWorkspaceTabCmd() tea.Cmd {
	return func() tea.Msg {
		wd, err := os.Getwd()
		if err != nil {
			return tabActivatedMsg{}
		}
		wf, _, err := AddOrActivateWorkspace(wd)
		if err != nil {
			return tabActivatedMsg{wf: wf}
		}
		return tabActivatedMsg{wf: wf}
	}
}

func (m rootModel) triggerNewChatSession() (tea.Model, tea.Cmd) {
	if m.session == nil {
		return m, nil
	}
	sm, cmd := m.session.beginNewChatSession()
	s := ptrSession(sm)
	if s != nil {
		m.session = s
		// Add to open sessions (id will be set when surfaceLoadedMsg arrives)
		m.openSessions = append(m.openSessions, openSession{model: s})
		m.activeSessionIdx = len(m.openSessions) - 1
	}
	return m, cmd
}

func (m *rootModel) sessionStreaming() bool {
	return m.session != nil && m.session.streaming
}

func (m rootModel) updateSessionTabKey(key tea.KeyMsg) (tea.Model, tea.Cmd, bool) {
	if m.screen != screenSession {
		return m, nil, false
	}
	if m.tabCloseConfirmID != "" {
		switch key.String() {
		case "y", "Y":
			id := m.tabCloseConfirmID
			m.tabCloseConfirmID = ""
			return m, m.closeTabCmd(id), true
		case "n", "esc":
			m.tabCloseConfirmID = ""
			return m, nil, true
		}
		return m, nil, true
	}
	switch key.String() {
	case "ctrl+tab":
		if len(m.workspaces.Tabs) < 2 {
			return m, nil, true
		}
		id := NextTabID(m.workspaces, 1)
		return m, m.activateTabCmd(id), true
	case "ctrl+shift+tab", "ctrl+pgup":
		if len(m.workspaces.Tabs) < 2 {
			return m, nil, true
		}
		id := NextTabID(m.workspaces, -1)
		return m, m.activateTabCmd(id), true
	case "ctrl+w":
		if m.workspaces.ActiveWorkspaceID == "" {
			return m, nil, true
		}
		if m.sessionStreaming() {
			m.tabCloseConfirmID = m.workspaces.ActiveWorkspaceID
			return m, nil, true
		}
		return m, m.closeTabCmd(m.workspaces.ActiveWorkspaceID), true
	case "ctrl+n":
		nm, cmd := m.triggerNewChatSession()
		return nm, cmd, true
	case "ctrl+shift+right":
		if len(m.openSessions) > 1 {
			next := (m.activeSessionIdx + 1) % len(m.openSessions)
			if nm, cmd, ok := m.switchToSession(next); ok {
				return nm, cmd, true
			}
		}
	case "ctrl+shift+left":
		if len(m.openSessions) > 1 {
			prev := m.activeSessionIdx - 1
			if prev < 0 {
				prev = len(m.openSessions) - 1
			}
			if nm, cmd, ok := m.switchToSession(prev); ok {
				return nm, cmd, true
			}
		}
	}
	return m, nil, false
}

func (m rootModel) handleSessionTabMouse(msg tea.MouseMsg) (tea.Model, tea.Cmd, bool) {
	if m.screen != screenSession || msg.Action != tea.MouseActionRelease || msg.Button != tea.MouseButtonLeft {
		return m, nil, false
	}
	// Row 0 = title/badge row, Row 1 = workspace tabs, Row 2 = session tabs
	wsRowY := sessionTabsBarRowY()
	titleRowY := wsRowY - 1
	sessionRowY := wsRowY + 1

	// Click on title/badge row → check if it's the mode badge
	if msg.Y == titleRowY {
		x := msg.X - m.sessionTabsBarStartX()
		if x >= 0 {
			badgeStart, badgeEnd := m.modeBadgeXRange()
			if x >= badgeStart && x < badgeEnd {
				return m.toggleModeFromBadge()
			}
		}
		return m, nil, false
	}

	if msg.Y != wsRowY && msg.Y != sessionRowY {
		return m, nil, false
	}
	x := msg.X - m.sessionTabsBarStartX()
	if x < 0 {
		return m, nil, false
	}
	gap := tabBarGapWidth()

	if msg.Y == wsRowY {
		// Workspace tabs
		for _, t := range m.workspaces.Tabs {
			width := workspaceTabRenderedWidth(t, t.ID == m.workspaces.ActiveWorkspaceID)
			if x >= 0 && x < width {
				if x >= width-2 {
					if m.sessionStreaming() {
						m.tabCloseConfirmID = t.ID
						return m, nil, true
					}
					return m, m.closeTabCmd(t.ID), true
				}
				if t.ID != m.workspaces.ActiveWorkspaceID {
					return m, m.activateTabCmd(t.ID), true
				}
				return m, nil, true
			}
			x -= width + gap
		}
	} else {
		// Session tabs
		for i, s := range m.openSessions {
			title := s.title
			if title == "" {
				title = "New session"
			}
			label := trim(title, 24) + " ×"
			w := lipgloss.Width(Theme().StyleTabHeader.Render(label))
			if i == m.activeSessionIdx {
				w = lipgloss.Width(Theme().StyleTabHeaderActive.Render(label))
			}
			if x >= 0 && x < w {
				if x >= w-2 {
					// Close session tab
					if m.sessionStreaming() {
						return m, nil, true
					}
					m.closeSessionTab(i)
					return m, nil, true
				}
				if i != m.activeSessionIdx {
					return m.switchToSession(i)
				}
				return m, nil, true
			}
			x -= w + gap
		}
	}
	// [+ New session] button (on session row)
	if msg.Y == sessionRowY && x >= 0 && x < newSessionTabButtonWidth() {
		nm, cmd := m.triggerNewChatSession()
		return nm, cmd, true
	}
	return m, nil, false
}

func (m *rootModel) closeSessionTab(idx int) {
	if idx < 0 || idx >= len(m.openSessions) {
		return
	}
	m.openSessions = append(m.openSessions[:idx], m.openSessions[idx+1:]...)
	if len(m.openSessions) == 0 {
		m.screen = screenHub
		m.session = nil
		m.activeSessionIdx = 0
		return
	}
	if m.activeSessionIdx >= len(m.openSessions) {
		m.activeSessionIdx = len(m.openSessions) - 1
	}
	m.session = m.openSessions[m.activeSessionIdx].model
}

func (m *rootModel) switchToSession(idx int) (tea.Model, tea.Cmd, bool) {
	if idx < 0 || idx >= len(m.openSessions) || m.session == nil {
		return m, nil, false
	}
	m.activeSessionIdx = idx
	os := m.openSessions[idx]
	m.session = os.model
	if os.id != "" && m.sessionsEnabled {
		return m, os.model.sessionOpenCmd(os.id), true
	}
	return m, nil, true
}

func renderWorkspaceTabsBar(wf workspacesFile) string {
	if len(wf.Tabs) == 0 {
		return ""
	}
	t := Theme()
	var parts []string
	for _, tab := range wf.Tabs {
		label := tab.Label + " ×"
		if tab.ID == wf.ActiveWorkspaceID {
			parts = append(parts, t.StyleTabHeaderActive.Render(label))
		} else {
			parts = append(parts, styleOnChatCanvas(t.StyleTabHeader).Render(label))
		}
	}
	return strings.Join(parts, chatCanvasSpace())
}

func renderSessionTabsBar(sessions []openSession, activeIdx int) string {
	t := Theme()
	var parts []string
	for i, s := range sessions {
		title := s.title
		if title == "" {
			title = "New session"
		}
		label := trim(title, 24) + " ×"
		if i == activeIdx {
			parts = append(parts, t.StyleTabHeaderActive.Render(label))
		} else {
			parts = append(parts, styleOnChatCanvas(t.StyleTabHeader).Render(label))
		}
	}
	parts = append(parts, styleOnChatCanvas(t.StyleDim).Render(newSessionTabLabel))
	return strings.Join(parts, chatCanvasSpace())
}

func (m rootModel) renderUnifiedSessionHeader() string {
	title := ""
	wsConnected := false
	if m.session != nil {
		title = m.session.displayTurnTitle()
		wsConnected = m.session.connectorOnline
	}
	return renderUnifiedSessionHeader(m.width, title, m.workspaces, m.openSessions, m.activeSessionIdx, m.tabCloseConfirmID, strings.ToUpper(string(m.cfg.Runtime)), wsConnected)
}

func renderUnifiedSessionHeader(width int, sessionTitle string, wf workspacesFile, sessions []openSession, activeSessionIdx int, tabCloseConfirmID string, runtimeBadge string, wsConnected bool) string {
	t := Theme()
	title := trim(sessionTitle, 32)
	if title == "" {
		title = "Sessão"
	}
	badge := ""
	if runtimeBadge != "" {
		if runtimeBadge == "TEAM" {
			// TEAM badge with green/red dot based on WS connection
			dotColor := lipgloss.Color("1") // red = disconnected
			if wsConnected {
				dotColor = lipgloss.Color("2") // green = connected
			}
			dot := lipgloss.NewStyle().Foreground(dotColor).Bold(true).Render("●")
			badgeStyle := styleOnChatCanvas(t.StyleAccent.Copy().Background(lipgloss.Color("#5c3fa0")))
			badge = badgeStyle.Render(" [" + runtimeBadge + "] ") + dot + " "
		} else {
			// SOLO badge (existing style)
			badge = styleOnChatCanvas(t.StyleAccent.Copy().Background(lipgloss.Color("#5c3fa0"))).Render(" [" + runtimeBadge + "] ") + " "
		}
	}
	left := styleOnChatCanvas(t.StyleAccent).Render("CENTRAL") + badge + styleOnChatCanvas(t.StyleDim).Render("· " + title)
	right := styleOnChatCanvas(t.StyleDim).Render("[Sair] Ctrl+L logout · Ctrl+C quit")

	innerW := width
	if innerW < 20 {
		innerW = 20
	}
	padW := innerW - lipgloss.Width(left) - lipgloss.Width(right)
	if padW < 0 {
		padW = 0
	}
	mid := ""
	if padW > 0 {
		mid = styleOnChatCanvas(lipgloss.NewStyle()).Render(strings.Repeat(" ", padW))
	}
	row1 := left + mid + right

	row2 := renderWorkspaceTabsBar(wf)
	row3 := renderSessionTabsBar(sessions, activeSessionIdx)
	sep := t.StyleSeparator.Render(strings.Repeat("─", width))

	out := row1
	if row2 != "" {
		out += "\n" + row2
	}
	if row3 != "" {
		out += "\n" + row3
	}
	out += "\n" + sep
	if tabCloseConfirmID != "" {
		out += "\n" + t.StyleError.Render("Close tab with active stream? [y] yes · [n] no")
	}
	return out + "\n"
}

func (m rootModel) renderSessionChrome() string {
	return m.renderUnifiedSessionHeader()
}

func (m *rootModel) applyTabActivated(wf workspacesFile) tea.Cmd {
	m.workspaces = wf
	if tab := ActiveWorkspace(wf); tab != nil {
		m.cfg.WorkspacePath = tab.Path
		_ = config.SaveWorkspace(tab.Path)
	}
	if m.session != nil {
		m.session.workspaceTabs = wf.Tabs
		m.session.activeTabID = wf.ActiveWorkspaceID
		if tab := ActiveWorkspace(wf); tab != nil {
			m.session.workspace = tab.Path
			m.session.runtime.WorkspacePath = tab.Path
		}
	}
	return nil
}

// modeBadgeXRange returns the start and end x-coordinate of the [SOLO]/[TEAM] badge
// within the session title row (relative to the sessionTabsBarStartX).
func (m rootModel) modeBadgeXRange() (int, int) {
	t := Theme()
	start := lipgloss.Width(styleOnChatCanvas(t.StyleAccent).Render("CENTRAL"))
	// After "CENTRAL" there's the badge text. We add a small padding.
	badgeText := " [" + strings.ToUpper(string(m.cfg.Runtime)) + "] "
	badgeW := lipgloss.Width(styleOnChatCanvas(t.StyleAccent.Copy().Background(lipgloss.Color("#5c3fa0"))).Render(badgeText))
	return start, start + badgeW
}

// toggleModeFromBadge toggles between SOLO and TEAM mode when the badge is clicked.
func (m *rootModel) toggleModeFromBadge() (tea.Model, tea.Cmd, bool) {
	if m.session == nil {
		return m, nil, false
	}
	switch m.cfg.Runtime {
	case config.ModeSolo:
		m.session.switchToTeam()
		m.cfg.Runtime = config.ModeTeam
	case config.ModeTeam:
		m.session.switchToSolo()
		m.cfg.Runtime = config.ModeSolo
	}
	return m, nil, true
}
