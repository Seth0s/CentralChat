package ui

import (
	"fmt"
	"os"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/bubbles/textinput"
	"github.com/charmbracelet/lipgloss"
	"github.com/centralchurch/central-cli/internal/api"
	"github.com/centralchurch/central-cli/internal/auth"
	"github.com/centralchurch/central-cli/internal/config"
)

func configLoadWd() (string, error) {
	return os.Getwd()
}

func (m *rootModel) blurLoginInputs() {
	m.loginEmail.Blur()
	m.loginPass.Blur()
	m.loginAPIURL.Blur()
	m.loginAPIKey.Blur()
}

func (m *rootModel) loginFieldMax() int {
	switch m.loginTab {
	case 0:
		return 2 // email, password, api url
	case 2:
		return 1 // api key, api url
	default:
		return -1
	}
}

func (m *rootModel) focusLoginField() tea.Cmd {
	m.blurLoginInputs()
	switch m.loginTab {
	case 0:
		switch m.loginField {
		case 1:
			m.loginPass.Focus()
		case 2:
			m.loginAPIURL.Focus()
		default:
			m.loginField = 0
			m.loginEmail.Focus()
		}
	case 2:
		switch m.loginField {
		case 1:
			m.loginAPIURL.Focus()
		default:
			m.loginField = 0
			m.loginAPIKey.Focus()
		}
	}
	return textinput.Blink
}

func (m *rootModel) enterLoginScreen() tea.Cmd {
	m.screen = screenLogin
	m.loginField = 0
	m.errorLine = ""
	return m.focusLoginField()
}

func (m rootModel) viewLogin() string {
	innerW := loginCardInnerWidth(m.width)
	tabs := []string{"Email", "Device", "API key"}
	b := strings.Builder{}
	b.WriteString(renderSegmentedControl(tabs, m.loginTab))
	b.WriteString("\n\n")

	switch m.loginTab {
	case 0:
		b.WriteString(renderLoginInputField("Email", m.loginEmail.View(), m.loginField == 0, innerW))
		b.WriteString(renderLoginInputField("Password", m.loginPass.View(), m.loginField == 1, innerW))
		b.WriteString(renderLoginInputField("API URL (advanced)", m.loginAPIURL.View(), m.loginField == 2, innerW))
	case 1:
		b.WriteString(styleDim.Render("Login no browser — sem password neste terminal."))
		b.WriteString("\n\n")
		if m.deviceCode != "" {
			b.WriteString(styleAccent.Render("Code: ") + m.deviceCode + "\n")
			b.WriteString(styleDim.Render("Approve in browser or dashboard. Waiting…"))
		} else {
			b.WriteString(styleDim.Render("Enter to generate device code."))
		}
	case 2:
		b.WriteString(styleDim.Render("For CI/automation (ck_…). Not the API URL."))
		b.WriteString("\n")
		b.WriteString(renderLoginInputField("API key", m.loginAPIKey.View(), m.loginField == 0, innerW))
		b.WriteString(renderLoginInputField("API URL", m.loginAPIURL.View(), m.loginField == 1, innerW))
	}

	b.WriteString("\n")
	b.WriteString(renderLoginActions(m.loginBusy))
	b.WriteString("\n\n")
	b.WriteString(renderLoginHints())
	if el := m.renderErrorLine(); el != "" {
		b.WriteString("\n\n")
		b.WriteString(el)
	}
	return renderPreSessionScreen(m.width, m.height, flowLogin, b.String())
}

func (m *rootModel) updateLoginKey(key tea.KeyMsg) (tea.Model, tea.Cmd) {
	if m.loginBusy {
		return m, nil
	}
	switch key.String() {
	case "tab":
		m.loginTab = (m.loginTab + 1) % 3
		m.errorLine = ""
		m.loginField = 0
		return m, m.focusLoginField()
	case "shift+tab":
		m.loginTab = (m.loginTab + 2) % 3
		m.errorLine = ""
		m.loginField = 0
		return m, m.focusLoginField()
	case "up":
		if m.loginField > 0 {
			m.loginField--
			return m, m.focusLoginField()
		}
		return m, nil
	case "down":
		if max := m.loginFieldMax(); max >= 0 && m.loginField < max {
			m.loginField++
			return m, m.focusLoginField()
		}
		return m, nil
	case "q", "ctrl+c":
		return m, tea.Quit
	case "d":
		m.errorLine = "Doctor: central doctor (terminal separado)"
		return m, nil
	case "enter":
		if m.loginTab == 1 {
			m.loginBusy = true
			return m, m.submitLogin()
		}
		if m.loginTab == 0 {
			email := strings.TrimSpace(m.loginEmail.Value())
			pass := strings.TrimSpace(m.loginPass.Value())
			if email == "" || pass == "" {
				m.errorLine = "Preenche email e password."
				return m, nil
			}
		}
		if m.loginTab == 2 {
			if strings.TrimSpace(m.loginAPIKey.Value()) == "" {
				m.errorLine = "Preenche a API key (ck_…)."
				return m, nil
			}
		}
		if max := m.loginFieldMax(); max >= 0 && m.loginField < max {
			m.loginField++
			return m, m.focusLoginField()
		}
		m.loginBusy = true
		return m, m.submitLogin()
	}

	var cmd tea.Cmd
	switch m.loginTab {
	case 0:
		switch m.loginField {
		case 1:
			m.loginPass, cmd = m.loginPass.Update(key)
		case 2:
			m.loginAPIURL, cmd = m.loginAPIURL.Update(key)
		default:
			m.loginEmail, cmd = m.loginEmail.Update(key)
		}
	case 2:
		switch m.loginField {
		case 1:
			m.loginAPIURL, cmd = m.loginAPIURL.Update(key)
		default:
			m.loginAPIKey, cmd = m.loginAPIKey.Update(key)
		}
	}
	return m, cmd
}

func (m *rootModel) submitLogin() tea.Cmd {
	tab := m.loginTab
	email := strings.TrimSpace(m.loginEmail.Value())
	pass := strings.TrimSpace(m.loginPass.Value())
	apiURL := strings.TrimSpace(m.loginAPIURL.Value())
	apiKey := strings.TrimSpace(m.loginAPIKey.Value())
	if apiURL == "" {
		apiURL = m.cfg.APIURL
	}
	return func() tea.Msg {
		client := api.New(apiURL, "")
		var resp *api.LoginResponse
		var err error
		method := "email"
		switch tab {
		case 1:
			method = "device"
			start, e := client.StartDeviceAuth("central-cli")
			if e != nil {
				return loginDoneMsg{Err: e}
			}
			deviceCode, _ := start["device_code"].(string)
			userCode, _ := start["user_code"].(string)
			interval := 5
			if v, ok := start["interval"].(float64); ok && v > 0 {
				interval = int(v)
			}
			deadline := time.Now().Add(10 * time.Minute)
			for time.Now().Before(deadline) {
				resp, err = client.PollDeviceToken(deviceCode)
				if err == nil {
					break
				}
				if !strings.Contains(err.Error(), "428") && !strings.Contains(err.Error(), "authorization_pending") {
					return loginDoneMsg{Err: err}
				}
				time.Sleep(time.Duration(interval) * time.Second)
			}
			if resp == nil {
				return loginDoneMsg{Err: err}
			}
			_ = userCode
		case 2:
			method = "api_key"
			resp, err = client.ExchangeApiKey(apiKey)
		default:
			resp, err = client.Login(email, pass)
		}
		if err != nil {
			return loginDoneMsg{Err: err}
		}
		credPath, e := config.CredentialsPath()
		if e != nil {
			return loginDoneMsg{Err: e}
		}
		if err := auth.Save(credPath, &auth.Credentials{
			AccessToken:  resp.AccessToken,
			RefreshToken: resp.RefreshToken,
			APIURL:       apiURL,
		}); err != nil {
			return loginDoneMsg{Err: err}
		}
		_ = SaveAuthPreferences(AuthPreferences{LastMethod: method, LastEmail: email})
		return loginDoneMsg{Client: api.New(apiURL, resp.AccessToken)}
	}
}

func (m rootModel) viewHub() string {
	leftW := hubColumnWidth(m.width)
	rightW := hubColumnWidth(m.width)

	// Render each panel as a bordered block
	leftBlock := m.renderHubLeftBlock(leftW)
	rightBlock := m.renderHubWorkQueueBlock(rightW)

	// Equalize heights — pad shorter block with plain bg fill (no border extension)
	leftH := lipgloss.Height(leftBlock)
	rightH := lipgloss.Height(rightBlock)
	bgFill := func(w int) string {
		return lipgloss.NewStyle().Background(lipgloss.Color(ColorCanvas)).Width(w).Render("")
	}
	if leftH < rightH {
		for i := leftH; i < rightH; i++ {
			leftBlock += "\n" + bgFill(leftW)
		}
	} else if rightH < leftH {
		for i := rightH; i < leftH; i++ {
			rightBlock += "\n" + bgFill(rightW)
		}
	}

	// Join with explicit bg gap — each line has its own ANSI background
	maxBlockH := leftH
	if rightH > maxBlockH {
		maxBlockH = rightH
	}
	gapStyle := lipgloss.NewStyle().Background(lipgloss.Color(ColorCanvas))
	var gapLines []string
	for i := 0; i < maxBlockH; i++ {
		gapLines = append(gapLines, gapStyle.Width(4).Render(""))
	}
	gapCol := strings.Join(gapLines, "\n")
	joined := lipgloss.JoinHorizontal(lipgloss.Top, leftBlock, gapCol, rightBlock)

	// Footer
	footerDim := styleDim.Copy().Background(lipgloss.Color(ColorCanvas))
	var footer string
	if m.errorLine != "" {
		footer = styleError.Render(m.errorLine)
	} else {
		footer = footerDim.Render("↑↓ navegar   Tab painéis   Enter abrir   d apagar   s refresh   a +ws atual   q sair")
	}
	footerLine := embedInScreenRow(m.width, footer)

	// Build screen
	fill := screenFillStyle()
	blank := fill.Width(m.width).Render("")
	logo := blockCenterScreenRows(m.width, renderWordmark(m.width))
	stepper := embedInScreenRow(m.width, renderFlowStepper(flowWorkspace))
	card := blockCenterScreenRows(m.width, joined)

	body := strings.Join([]string{logo, blank, stepper, blank, card, blank, footerLine}, "\n")
	return verticalCenterOnScreen(m.width, m.height, body)
}

// blockBorderRow renders a single content-row with side borders, used to pad block heights.
func blockBorderRow(width int) string {
	s := lipgloss.NewStyle().
		Background(lipgloss.Color(ColorCanvas)).
		Foreground(lipgloss.Color(ColorBorder))
	innerW := width - 4 // left border + left pad + right pad + right border = 4
	if innerW < 0 {
		innerW = 0
	}
	return s.Render("│") +
		lipgloss.NewStyle().Background(lipgloss.Color(ColorCanvas)).Padding(0, 1).Width(innerW).Render("") +
		s.Render("│")
}

func hubColumnWidth(termW int) int {
	// Two equal columns with 4-char gap. 82-wide card base.
	cardW := min(82, termW-6)
	colW := (cardW - 4) / 2
	if colW < 38 {
		colW = 38
	}
	return colW
}

func (m rootModel) renderHubLeftPanel(width int) string {
	t := Theme()
	b := strings.Builder{}

	textOnBlue := lipgloss.NewStyle().Foreground(lipgloss.Color("255")).Background(lipgloss.Color("33")).Bold(true)
	accentOnBlue := lipgloss.NewStyle().Foreground(lipgloss.Color("39")).Background(lipgloss.Color("33")).Bold(true)

	// ── Workspaces ──
	b.WriteString(t.StyleAccent.Render("Hub"))
	b.WriteString("\n")
	b.WriteString(t.StyleSeparator.Render(strings.Repeat("─", width-4)))
	b.WriteString("\n\n")
	b.WriteString(t.StyleLabel.Render("Workspaces"))
	b.WriteString("\n")
	if len(m.workspaces.Tabs) == 0 {
		b.WriteString(styleDim.Render("  (Enter para usar cwd)"))
	} else {
		for i, ws := range m.workspaces.Tabs {
			label := trim(ws.Label, 14)
			short := shortPath(ws.Path, 3)
			path := trim(short, width-6)
			isActive := ws.ID == m.workspaces.ActiveWorkspaceID
			connectorTag := ""
			if ws.ConnectorID != "" {
				connectorTag = " " + styleDim.Render("@"+ws.ConnectorID)
			}
			if m.hubPanel == panelWorkspaces && i == m.wsList.cursor {
				dot := "  "
				if isActive {
					dot = "● "
				}
				b.WriteString("  " + accentOnBlue.Render(dot) + textOnBlue.Render(label) + connectorTag + "\n")
			} else {
				activeMark := ""
				if isActive {
					activeMark = t.StyleAccent.Render("● ")
				}
				b.WriteString("  " + activeMark + label + connectorTag + "\n")
			}
			b.WriteString("   " + styleDim.Render(path) + "\n")
		}
	}
	b.WriteString("\n")

	// ── Sessions ──
	const pageSize = 8
	b.WriteString(t.StyleLabel.Render("Sessions"))
	if len(m.sessionList) > pageSize {
		totalPages := (len(m.sessionList) + pageSize - 1) / pageSize
		currentPage := m.sessList.offset / pageSize
		b.WriteString(t.StyleDim.Render(fmt.Sprintf(" (%d/%d)", currentPage+1, totalPages)))
	}
	b.WriteString("\n")
	if len(m.sessionList) == 0 {
		b.WriteString(styleDim.Render("  sem sessões recentes"))
		b.WriteString("\n")
	} else {
		start := m.sessList.offset
		end := start + pageSize
		if end > len(m.sessionList) {
			end = len(m.sessionList)
		}
		m.sessList.clamp(len(m.sessionList) - 1)
		for i := start; i < end; i++ {
			s := m.sessionList[i]
			info := fmt.Sprintf("%d msgs", s.MessageCount)
			if s.Pinned {
				info += " · 📌"
			}
			displayTitle := trim(s.Title, width-len(info)-8)
			if m.hubPanel == panelSessions && i == m.sessList.cursor {
				b.WriteString("  " + textOnBlue.Render(displayTitle+"  "+info) + "\n")
			} else {
				b.WriteString("  " + displayTitle + "  " + styleDim.Render(info) + "\n")
			}
		}
		if len(m.sessionList) > pageSize {
			nav := t.StyleDim.Render("  ← anterior  |  seguinte →")
			b.WriteString(nav + "\n")
		}
	}
	// Button / disabled notice
	b.WriteString("\n")
	if !m.sessionsEnabled {
		b.WriteString(styleDim.Render("  (sessões desabilitadas)") + "\n")
	} else if m.hubPanel == panelNewSession {
		b.WriteString("  " + t.StyleTabActive.Render(" + New session ") + "\n")
	} else {
		b.WriteString("  " + styleDim.Render("+ New session") + "\n")
	}

	if m.hubDeleteConfirmID != "" {
		b.WriteString("\n")
		b.WriteString(styleError.Render("Confirm delete? [y] yes  [n] no"))
	}
	return wrapBlock(b.String(), width)
}
// wrapBlock takes plain text content and wraps it in a bordered block.
func wrapBlock(content string, width int) string {
	blockStyle := lipgloss.NewStyle().
		Border(lipgloss.NormalBorder()).
		BorderForeground(lipgloss.Color(ColorBorder)).
		Background(lipgloss.Color(ColorCanvas)).
		Padding(0, 1).
		Width(width - 2) // border adds 2
	return blockStyle.Render(content)
}

func (m rootModel) renderHubLeftBlock(width int) string {
	return m.renderHubLeftPanel(width)
}

func (m rootModel) renderHubWorkQueueBlock(width int) string {
	return m.renderHubWorkQueuePanel(width)
}

func (m rootModel) renderHubWorkQueuePanel(width int) string {
	t := Theme()
	b := strings.Builder{}

	// Focus indicator
	if m.hubPanel == panelWorkQueue {
		b.WriteString(lipgloss.NewStyle().Foreground(lipgloss.Color("255")).Background(lipgloss.Color("33")).Bold(true).Render("Work Queue"))
	} else {
		b.WriteString(t.StyleAccent.Render("Work Queue"))
	}
	b.WriteString("\n")
	b.WriteString(t.StyleSeparator.Render(strings.Repeat("─", width-4)))
	b.WriteString("\n\n")

	if len(m.workItems) == 0 {
		b.WriteString(styleDim.Render("  (carregando…)"))
	} else {
		// Show max 8 items to fit
		maxItems := 8
		if len(m.workItems) < maxItems {
			maxItems = len(m.workItems)
		}
		for i := 0; i < maxItems; i++ {
			wi := m.workItems[i]
			title := trim(wi.Title, width-14)
			status := statusBadge(wi.Status)
			priority := priorityBadge(wi.Priority)
			line := fmt.Sprintf("  %s %s  %s", status, priority, t.StyleDim.Render(title))
			b.WriteString(line + "\n")
		}
		if len(m.workItems) > maxItems {
			b.WriteString(styleDim.Render(fmt.Sprintf("  ... +%d mais", len(m.workItems)-maxItems)))
			b.WriteString("\n")
		}
	}
	return wrapBlock(b.String(), width)
}

func statusBadge(s string) string {
	switch s {
	case "open":
		return Theme().StyleLabel.Render("◉")
	case "in_progress":
		return Theme().StyleBarPlan.Render("▶")
	case "done", "closed":
		return lipgloss.NewStyle().Foreground(lipgloss.Color("42")).Render("✓")
	default:
		return Theme().StyleDim.Render("○")
	}
}

func priorityBadge(s string) string {
	switch s {
	case "critical":
		return Theme().StyleError.Render("‼")
	case "high":
		return lipgloss.NewStyle().Foreground(lipgloss.Color("214")).Render("▲")
	default:
		return ""
	}
}

func (m *rootModel) updateHubKey(key tea.KeyMsg) (tea.Model, tea.Cmd) {
	isActive := func(p hubPanel) bool { return m.hubPanel == p }
	maxWS := len(m.workspaces.Tabs) - 1
	maxSess := len(m.sessionList) - 1

	// ── Quit ──
	if key.String() == "q" || key.String() == "ctrl+c" {
		return m, tea.Quit
	}

	// ── Panel switching ──
	if key.Type == tea.KeyTab {
		m.hubPanel = hubPanel((int(m.hubPanel) + 1) % int(panelCount))
		return m, nil
	}
	if key.Type == tea.KeyShiftTab {
		m.hubPanel = hubPanel((int(m.hubPanel) + int(panelCount) - 1) % int(panelCount))
		return m, nil
	}

	// ── Confirm delete ──
	if m.hubDeleteConfirmID != "" {
		switch key.String() {
		case "y":
			if isActive(panelSessions) {
				sid := m.hubDeleteConfirmID
				m.hubDeleteConfirmID = ""
				return m, m.deleteSessionCmd(sid)
			}
			if isActive(panelWorkspaces) {
				id := m.hubDeleteConfirmID
				m.hubDeleteConfirmID = ""
				wf := CloseWorkspaceTab(id)
				m.workspaces = wf
				m.wsList.clamp(len(wf.Tabs) - 1)
			}
		case "n", "esc":
			m.hubDeleteConfirmID = ""
		}
		return m, nil
	}

	// ── Navigation ──
	switch key.String() {
	case "up", "k":
		switch {
		case isActive(panelWorkspaces):
			if m.wsList.cursor == 0 {
				if maxSess >= 0 {
					m.hubPanel = panelSessions
					m.sessList.cursor = maxSess
				}
			} else {
				m.wsList.up()
			}
		case isActive(panelSessions):
			if m.sessList.cursor == 0 && m.sessList.offset == 0 {
				m.hubPanel = panelWorkspaces
				m.wsList.clamp(maxWS)
			} else {
				m.sessList.up()
			}
		case isActive(panelNewSession):
			if maxSess >= 0 {
				m.hubPanel = panelSessions
				m.sessList.cursor = maxSess
			} else {
				m.hubPanel = panelWorkspaces
				m.wsList.clamp(maxWS)
			}
		case isActive(panelWorkQueue):
			if maxSess >= 0 {
				m.hubPanel = panelSessions
			} else {
				m.hubPanel = panelWorkspaces
			}
		}
	case "down", "j":
		switch {
		case isActive(panelWorkspaces):
			if m.wsList.cursor >= maxWS {
				if maxSess >= 0 {
					m.hubPanel = panelSessions
					m.sessList.cursor = 0
				} else {
					m.hubPanel = panelNewSession
				}
			} else {
				m.wsList.down(maxWS)
			}
		case isActive(panelSessions):
			lastOnPage := m.sessList.offset + 7
			if lastOnPage > maxSess {
				lastOnPage = maxSess
			}
			if m.sessList.cursor >= lastOnPage || maxSess < 0 {
				m.hubPanel = panelNewSession
			} else {
				m.sessList.down(maxSess)
			}
		case isActive(panelWorkQueue):
			m.hubPanel = panelWorkspaces
		}
	case "left":
		if isActive(panelSessions) && m.sessList.offset > 0 {
			m.sessList.offset -= 8
			m.sessList.cursor = m.sessList.offset
		}
	case "right":
		if isActive(panelSessions) && m.sessList.offset+8 <= maxSess {
			m.sessList.offset += 8
			m.sessList.cursor = m.sessList.offset
		}
	case "s":
		return m, m.loadSessionsCmd()
	case "a":
		if wd, err := os.Getwd(); err == nil {
			wf, _, _ := AddOrActivateWorkspace(wd)
			m.workspaces = wf
			m.wsList.cursor = len(wf.Tabs) - 1
			m.wsList.clamp(len(wf.Tabs) - 1)
			m.hubPanel = panelWorkspaces
		}
	case "d":
		if isActive(panelSessions) && m.sessList.cursor <= maxSess {
			m.hubDeleteConfirmID = m.sessionList[m.sessList.cursor].ID
		} else if isActive(panelWorkspaces) && m.wsList.cursor <= maxWS {
			m.hubDeleteConfirmID = m.workspaces.Tabs[m.wsList.cursor].ID
		}
	case "enter":
		switch {
		case isActive(panelNewSession):
			if !m.sessionsEnabled {
				m.errorLine = "Sessions disabled on backend."
				return m, nil
			}
			m.activateCurrentWorkspace()
			// SOLO: no daemon required
			if m.cfg.Runtime != config.ModeSolo && m.daemon.state != daemonOnline {
				m.screen = screenDaemonGate
				return m, nil
			}
			return m, func() tea.Msg { return enterSessionMsg{} }
		case isActive(panelSessions) && len(m.sessionList) > 0:
			if !m.sessionsEnabled {
				m.errorLine = "Sessions disabled on backend."
				return m, nil
			}
			sid := m.sessionList[m.sessList.cursor].ID
			return m.openSessionByID(sid)
		case isActive(panelWorkspaces):
			m.selectCurrentWorkspace()
			return m, m.loadSessionsCmd()
		}
	}
	return m, nil
}

func (m *rootModel) selectCurrentWorkspace() {
	if len(m.workspaces.Tabs) == 0 {
		return
	}
	m.wsList.clamp(len(m.workspaces.Tabs) - 1)
	tab := m.workspaces.Tabs[m.wsList.cursor]
	wf := m.workspaces
	wf.ActiveWorkspaceID = tab.ID
	_ = SaveWorkspaces(wf)
	m.workspaces = wf
	_ = config.SaveWorkspace(tab.Path)
	m.cfg.WorkspacePath = tab.Path
	if m.client != nil {
		_ = m.client.BindWorkspace(tab.Path)
		_ = SyncWorkspacesToServer(m.client, wf)
	}
}

func (m *rootModel) activateCurrentWorkspace() {
	if len(m.workspaces.Tabs) == 0 {
		if wd, err := os.Getwd(); err == nil {
			wf, _, _ := AddOrActivateWorkspace(wd)
			m.workspaces = wf
		}
	}
	m.wsList.clamp(len(m.workspaces.Tabs) - 1)
	if len(m.workspaces.Tabs) > 0 {
		tab := m.workspaces.Tabs[m.wsList.cursor]
		wf := m.workspaces
		wf.ActiveWorkspaceID = tab.ID
		_ = SaveWorkspaces(wf)
		m.workspaces = wf
		_ = config.SaveWorkspace(tab.Path)
		m.cfg.WorkspacePath = tab.Path
		if m.client != nil {
			_ = m.client.BindWorkspace(tab.Path)
			_ = SyncWorkspacesToServer(m.client, wf)
		}
		m.daemon.Refresh()
	}
}

func (m *rootModel) openSessionByID(sid string) (tea.Model, tea.Cmd) {
	// Activate workspace first
	m.activateCurrentWorkspace()
	sm := newModel(m.client, m.cfg, RunOptions{})
	sm.offlineMode = m.offline
	sm.workspaceTabs = m.workspaces.Tabs
	sm.activeTabID = m.workspaces.ActiveWorkspaceID
	sm.daemonChip = m.daemon.Chip()
	if tab := ActiveWorkspace(m.workspaces); tab != nil {
		sm.workspace = tab.Path
		sm.runtime.WorkspacePath = tab.Path
	}
	applySessionDimensions(&sm, m.width, m.height)
	sm.skipSessionHeader = true
	m.session = &sm
	m.screen = screenSession
	// Track in open sessions
	m.openSessions = append(m.openSessions, openSession{id: sid, model: &sm})
	m.activeSessionIdx = len(m.openSessions) - 1
	return m, tea.Batch(sm.Init(), sm.sessionOpenCmd(sid))
}

func applySessionDimensions(sm *model, width, height int) {
	if width > 0 {
		sm.width = width
	}
	if height > 0 {
		sm.height = height
	}
	if sm.width > 0 {
		sm.syncInputWidth()
	}
}

func (m rootModel) viewDaemonGate() string {
	body := styleAccent.Render("Daemon local") + "\n\n" +
		daemonGateMessage(&m.daemon) + "\n\n" +
		styleDim.Render("Enter: iniciar · s: read-only · Esc: voltar")
	if el := m.renderErrorLine(); el != "" {
		body += "\n\n" + el
	}
	return renderPreSessionScreen(m.width, m.height, flowWorkspace, body)
}

func (m *rootModel) updateDaemonKey(key tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch key.String() {
	case "esc":
		m.screen = screenHub
		return m, nil
	case "enter":
		_ = m.daemon.Start()
		m.offline = false
		return m, tea.Tick(2*time.Second, func(time.Time) tea.Msg { return enterSessionMsg{} })
	case "s":
		m.offline = true
		return m, func() tea.Msg { return enterSessionMsg{} }
	}
	return m, nil
}
