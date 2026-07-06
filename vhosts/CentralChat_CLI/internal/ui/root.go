package ui

import (
	"fmt"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/bubbles/textinput"
	"github.com/charmbracelet/lipgloss"
	"github.com/centralchurch/central-cli/internal/api"
	"github.com/centralchurch/central-cli/internal/auth"
	"github.com/centralchurch/central-cli/internal/clierrors"
	"github.com/centralchurch/central-cli/internal/config"
	"github.com/centralchurch/central-cli/internal/version"
)

type appScreen int

const (
	screenSplash appScreen = iota
	screenLogin
	screenModeSelect
	screenHub
	screenDaemonGate
	screenSetup
	screenSession
)

type bootDoneMsg struct {
	APIOK bool
	Authed bool
	Err   string
}

type loginDoneMsg struct {
	Client *api.Client
	Err    error
}

// hubPanel identifies which panel has keyboard focus in the hub.
type hubPanel int

const (
	panelWorkspaces hubPanel = iota
	panelSessions
	panelNewSession
	panelWorkQueue
	panelCount // sentinel
)

// listState holds cursor position and scroll offset for a scrollable list.
type listState struct {
	cursor int
	offset int
}

func (ls *listState) down(maxIdx int) {
	if ls.cursor < maxIdx {
		ls.cursor++
	}
}

func (ls *listState) up() {
	if ls.cursor > 0 {
		ls.cursor--
	}
}

func (ls *listState) clamp(maxIdx int) {
	if ls.cursor > maxIdx {
		ls.cursor = maxIdx
	}
	if ls.cursor < 0 {
		ls.cursor = 0
	}
}

// openSession tracks an active in-memory session tab.
type openSession struct {
	id    string
	title string
	model *model
}

type rootModel struct {
	screen appScreen
	width  int
	height int

	cfg   *config.Config
	client *api.Client

	splashAt   time.Time
	splashSkip bool
	bootLine   string

	// login
	loginTab    int // 0 email 1 device 2 api_key
	loginField  int // field index within tab
	loginEmail  textinput.Model
	loginPass   textinput.Model
	loginAPIURL textinput.Model
	loginAPIKey textinput.Model
	loginBusy   bool
	deviceCode  string
	devicePoll  bool

	// hub
	workspaces  workspacesFile
	sessionList        []SessionMeta
	sessionsEnabled    bool
	workItems          []WorkItemMeta
	hubPanel    hubPanel
	wsList      listState
	sessList    listState

	// unified error (replaces loginErr + hubErr)
	errorLine string

	// setup wizard
	setupWizardStep    setupStep       // 0=providers, 1=tools, 2=defaults
	providerSubStep    providerSubStep // subPick or subEdit within providers
	setupCursor        int             // cursor in provider list
	setupProviderKind  config.ProviderKind
	setupKeyInput      textinput.Model
	setupKeys          map[string]string // kind -> api key (temporary until save)
	setupToolsCursor   int             // cursor in tools list
	setupToolsChoice   int             // 0=native, 1=docker, 2=skip
	setupWorkspaceInput textinput.Model
	setupModelInput    textinput.Model
	setupDefaultsField int             // 0=workspace, 1=model
	setupFromSession   bool            // true if opened via /setup from session
	setupInstalling    bool            // true while running pip/docker install
	setupInstallOutput string          // output from install command
	setupInstallFrame  int             // spinner frame counter

	// mode selection screen
	modeSelectTeamURL     textinput.Model
	modeSelectEnteringURL bool

	daemon DaemonManager

	session          *model
	offline          bool
	openSessions     []openSession
	activeSessionIdx int

	tabCloseConfirmID  string
	hubDeleteConfirmID string
}

func newRootModel(cfg *config.Config) rootModel {
	applyTheme(LoadTUIConfig().Theme)

	innerW := loginCardInnerWidth(80)
	email := styleLoginInput(textinput.New())
	email.Placeholder = "email@exemplo.com"
	email.CharLimit = 200
	email.Width = innerW - 5

	pass := styleLoginInput(textinput.New())
	pass.Placeholder = "password"
	pass.EchoMode = textinput.EchoPassword
	pass.EchoCharacter = '•'
	pass.CharLimit = 200
	pass.Width = innerW - 5

	apiURL := styleLoginInput(textinput.New())
	apiURL.Placeholder = "http://127.0.0.1:8004"
	apiURL.SetValue(cfg.APIURL)
	apiURL.CharLimit = 300
	apiURL.Width = innerW - 5

	apiKey := styleLoginInput(textinput.New())
	apiKey.Placeholder = "ck_…"
	apiKey.CharLimit = 300
	apiKey.Width = innerW - 5

	prefs := LoadAuthPreferences()
	tab := 0
	switch prefs.LastMethod {
	case "device":
		tab = 1
	case "api_key":
		tab = 2
	}
	if prefs.LastEmail != "" {
		email.SetValue(prefs.LastEmail)
	}

	email.Blur()
	pass.Blur()
	apiURL.Blur()
	apiKey.Blur()

	m := rootModel{
		screen:      screenSplash,
		cfg:         cfg,
		splashAt:    time.Now(),
		loginTab:    tab,
		loginEmail:  email,
		loginPass:   pass,
		loginAPIURL: apiURL,
		loginAPIKey: apiKey,
		workspaces: LoadWorkspaces(),
		hubPanel:   panelNewSession,
		modeSelectTeamURL: styleLoginInput(textinput.New()),
	}
	m.modeSelectTeamURL.Placeholder = "http://vps.example.com:8004"
	m.modeSelectTeamURL.CharLimit = 300
	m.modeSelectTeamURL.Width = 40
	m.modeSelectTeamURL.SetValue(cfg.APIURL)
	m.modeSelectTeamURL.Blur()
	m.focusLoginField()
	return m
}

// RunApp is the P0+ entry: splash → login → hub → daemon → session.
func RunApp(cfg *config.Config) error {
	m := newRootModel(cfg)
	p := tea.NewProgram(m, tea.WithAltScreen(), tea.WithMouseCellMotion())
	_, err := p.Run()
	return err
}

func ptrSession(m tea.Model) *model {
	switch s := m.(type) {
	case *model:
		return s
	case model:
		return &s
	default:
		return nil
	}
}

func (m rootModel) Init() tea.Cmd {
	return tea.Batch(
		textinput.Blink,
		m.bootCmd(),
		tea.Tick(1200*time.Millisecond, func(time.Time) tea.Msg { return splashTimeoutMsg{} }),
		tea.EnableMouseCellMotion,
	)
}

type splashTimeoutMsg struct{}

func (m rootModel) bootCmd() tea.Cmd {
	cfg := m.cfg
	return func() tea.Msg {
		client, authed, errStr := tryLoadClient(cfg)
		apiOK := false
		if client != nil {
			if err := client.Health(); err == nil {
				apiOK = true
			}
		} else {
			c := api.New(cfg.APIURL, "")
			apiOK = c.Health() == nil
		}
		if authed && client != nil {
			if _, err := client.GetWorkspaces(); err != nil && clierrors.IsAuthError(err) {
				if p, e := config.CredentialsPath(); e == nil {
					_ = auth.Clear(p)
				}
				authed = false
				client = nil
			}
		}
		return bootDoneMsg{APIOK: apiOK, Authed: authed, Err: errStr}
	}
}

func tryLoadClient(cfg *config.Config) (*api.Client, bool, string) {
	credPath, err := config.CredentialsPath()
	if err != nil {
		return nil, false, err.Error()
	}
	cred, err := auth.Load(credPath)
	if err != nil {
		return nil, false, ""
	}
	base := cfg.APIURL
	if cred.APIURL != "" {
		base = cred.APIURL
	}
	return api.New(base, cred.AccessToken), true, ""
}

func (m rootModel) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	if mouse, ok := msg.(tea.MouseMsg); ok {
		return m.updateMouse(mouse)
	}
	if key, ok := msg.(tea.KeyMsg); ok {
		if m.screen == screenModeSelect && m.modeSelectEnteringURL {
			return m.updateModeSelectURLKey(key)
		}
		if nm, cmd, handled := m.updateSessionTabKey(key); handled {
			return nm, cmd
		}
	}

	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		fw := loginFieldWidth(m.width)
		m.loginEmail.Width = fw - 5
		m.loginPass.Width = fw - 5
		m.loginAPIURL.Width = fw - 5
		m.loginAPIKey.Width = fw - 5
		m.modeSelectTeamURL.Width = fw - 5
		if m.session != nil {
			sm, cmd := m.session.Update(msg)
			m.session = ptrSession(sm)
			return m, cmd
		}
		return m, nil

	case splashTimeoutMsg:
		if m.screen == screenSplash && !m.splashSkip {
			// If config.toml doesn't exist yet, show mode selection first
			if !config.HasRuntimeConfig() {
				m.screen = screenModeSelect
				return m, nil
			}
			rt, _ := config.LoadRuntimeConfig()
			if rt != nil && rt.Mode == config.ModeSolo {
				m.cfg.Runtime = config.ModeSolo

				// First boot without provider → setup screen
				if !config.HasAnyProvider() {
					m.screen = screenSetup
					m.initSetupWizard()
					return m, nil
				}

				// SOLO: skip login, go directly to hub
				m.screen = screenHub
				m.prepareHub()
				return m, tea.Batch(m.loadSessionsCmd(), m.loadWorkItemsCmd())
			}
			if m.client != nil {
				m.screen = screenHub
				m.prepareHub()
				return m, tea.Batch(m.syncWorkspacesCmd(), m.loadSessionsCmd(), m.loadWorkItemsCmd())
			} else if m.bootLine == "" {
				return m, m.enterLoginScreen()
			} else if strings.Contains(m.bootLine, "auth ✓") && m.client != nil {
				m.screen = screenHub
				m.prepareHub()
				return m, tea.Batch(m.syncWorkspacesCmd(), m.loadSessionsCmd(), m.loadWorkItemsCmd())
			} else {
				return m, m.enterLoginScreen()
			}
		}

	case bootDoneMsg:
		if msg.APIOK {
			m.bootLine = "API ✓ · auth · workspace"
		} else {
			m.bootLine = styleError.Render("API unreachable") + " · check CENTRAL_API_URL"
		}
		if msg.Authed {
			m.bootLine = "API ✓ · auth ✓ · workspace…"
			m.client, _, _ = tryLoadClient(m.cfg)
			if m.screen == screenSplash {
				m.screen = screenHub
				m.prepareHub()
				return m, tea.Batch(m.syncWorkspacesCmd(), m.loadSessionsCmd(), m.loadWorkItemsCmd())
				}
		} else if m.screen == screenSplash && m.splashSkip {
			return m, m.enterLoginScreen()
		}

	case workspacesSyncedMsg:
		if len(msg.wf.Tabs) > 0 {
			m.workspaces = msg.wf
		}
		if msg.err != nil {
			if clierrors.IsAuthError(msg.err) {
				if p, err := config.CredentialsPath(); err == nil {
					_ = auth.Clear(p)
				}
				m.client = nil
				m.errorLine = ""
				return m, m.enterLoginScreen()
			}
			m.errorLine = clierrors.UserMessage(msg.err)
		}
		return m, nil

	case tabActivatedMsg:
		sessCmd := m.applyTabActivated(msg.wf)
		if m.client != nil {
			return m, tea.Batch(sessCmd, m.syncWorkspacesCmd())
		}
		return m, sessCmd

	case loginDoneMsg:
		m.loginBusy = false
		if msg.Err != nil {
			m.errorLine = clierrors.UserMessage(msg.Err)
			return m, nil
		}
		m.client = msg.Client
		m.errorLine = ""
		m.screen = screenHub
		m.prepareHub()
		return m, tea.Batch(m.syncWorkspacesCmd(), m.loadSessionsCmd(), m.loadWorkItemsCmd())

	case goHubMsg:
		m.screen = screenHub
		m.session = nil
		m.prepareHub()
		return m, tea.Batch(m.syncWorkspacesCmd(), m.loadSessionsCmd(), m.loadWorkItemsCmd())

	case goDaemonGateMsg:
		m.daemon.Refresh()
		m.screen = screenDaemonGate
		return m, nil

	case goLoginMsg:
		if m.cfg.Runtime == config.ModeSolo {
			// SOLO mode: ignore logout, go to Hub instead
			m.screen = screenHub
			m.prepareHub()
			return m, tea.Batch(m.loadSessionsCmd(), m.loadWorkItemsCmd())
		}
		if m.client != nil {
			_ = m.client.Logout()
		}
		if p, err := config.CredentialsPath(); err == nil {
			_ = auth.Clear(p)
		}
		m.client = nil
		m.session = nil
		m.screen = screenLogin
		m.errorLine = ""
		return m, m.enterLoginScreen()

	case sessionListMsg:
		if msg.Err != nil {
			m.errorLine = msg.Err.Error()
		} else {
			m.sessionList = msg.Sessions
			m.sessionsEnabled = msg.SessionsEnabled
			m.errorLine = ""
		}
		return m, nil

	case sessionDeletedMsg:
		if msg.Err != nil {
			m.errorLine = msg.Err.Error()
		} else {
			m.errorLine = ""
		}
		return m, m.loadSessionsCmd()

	case workItemsLoadedMsg:
		if msg.Err != nil {
			m.errorLine = msg.Err.Error()
		} else {
			m.workItems = msg.Items
		}
		return m, nil

	case installDoneMsg:
		m.setupInstalling = false
		if msg.err != nil {
			m.setupInstallOutput = fmt.Sprintf("✗ Install failed: %v", msg.err)
		} else {
			m.setupInstallOutput = "✓ Installation complete"
		}
		return m, nil

	case tickMsg:
		if m.setupWizardStep == setupWizardInstall && m.setupInstalling {
			m.setupInstallFrame++
			return m, tickEvery(100*time.Millisecond)
		}
		return m, nil

	case enterSessionMsg:
		m.screen = screenSession
		if m.session == nil {
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
			sm.sessionStartedAt = time.Now()
			m.session = &sm
			// Add to open sessions
			m.openSessions = append(m.openSessions, openSession{model: &sm})
			m.activeSessionIdx = len(m.openSessions) - 1
		}
		return m, m.session.Init()

	default:
		if m.screen == screenSession && m.session != nil {
			sm, cmd := m.session.Update(msg)
			s := ptrSession(sm)
			if s == nil {
				return m, cmd
			}
			if s.requestHub {
				s.requestHub = false
				m.session = s
				return m, func() tea.Msg { return goHubMsg{} }
			}
			if s.requestSetup {
				s.requestSetup = false
				m.session = s
				m.screen = screenSetup
				m.initSetupWizard()
				m.setupFromSession = true
				// Pre-fill from existing config
				if rt, err := config.LoadRuntimeConfig(); err == nil && rt != nil {
					for name, p := range rt.Solo.Providers {
						// Only pre-fill if key is not a $VAR reference
						if p.APIKey != "" && !strings.HasPrefix(p.APIKey, "$") {
							m.setupKeys[name] = p.APIKey
						}
					}
				}
				return m, nil
			}
			if s.requestLogout {
				s.requestLogout = false
				m.session = s
				return m, func() tea.Msg { return goLoginMsg{} }
			}
			m.session = s
			// Sync session ID to open session tab (for Ctrl+N created sessions)
			if m.activeSessionIdx >= 0 && m.activeSessionIdx < len(m.openSessions) {
				if s.sessionID != "" {
					m.openSessions[m.activeSessionIdx].id = s.sessionID
				}
				m.openSessions[m.activeSessionIdx].model = s
			}
			return m, cmd
		}
	}

	if key, ok := msg.(tea.KeyMsg); ok {
		return m.updateKey(key)
	}
	return m, nil
}

func (m rootModel) updateMouse(mouse tea.MouseMsg) (tea.Model, tea.Cmd) {
	ev := tea.MouseEvent(mouse)
	if mouse.Shift && !ev.IsWheel() {
		return m, tea.DisableMouse
	}
	var reenable tea.Cmd
	if mouse.Action == tea.MouseActionRelease && !mouse.Shift {
		reenable = tea.EnableMouseCellMotion
	}
	if nm, cmd, handled := m.handleSessionTabMouse(mouse); handled {
		return nm, tea.Batch(reenable, cmd)
	}
	if m.screen == screenSession && m.session != nil {
		sm, cmd := m.session.Update(mouse)
		s := ptrSession(sm)
		if s == nil {
			return m, tea.Batch(reenable, cmd)
		}
		if s.requestHub {
			s.requestHub = false
			m.session = s
			return m, tea.Batch(reenable, func() tea.Msg { return goHubMsg{} })
		}
		if s.requestLogout {
			s.requestLogout = false
			m.session = s
			return m, tea.Batch(reenable, func() tea.Msg { return goLoginMsg{} })
		}
		m.session = s
		return m, tea.Batch(reenable, cmd)
	}
	if reenable != nil {
		return m, reenable
	}
	return m, nil
}

type goHubMsg struct{}
type goLoginMsg struct{}
type goDaemonGateMsg struct{}
type enterSessionMsg struct{}

func (m *rootModel) updateKey(key tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch m.screen {
	case screenModeSelect:
		return m.updateModeSelectKey(key)
	case screenSplash:
		if key.String() == "enter" || key.String() == "esc" {
			m.splashSkip = true
			if m.client != nil {
				m.screen = screenHub
				m.prepareHub()
				return m, nil
			}
			return m, m.enterLoginScreen()
		}
	case screenLogin:
		return m.updateLoginKey(key)
	case screenHub:
		return m.updateHubKey(key)
	case screenDaemonGate:
		return m.updateDaemonKey(key)
	case screenSetup:
		return m.updateSetupKey(key)
	}
	return m, nil
}

func (m *rootModel) prepareHub() {
	m.workspaces = LoadWorkspaces()
	if wd, err := osGetwd(); err == nil {
		wf, tab, _ := AddOrActivateWorkspace(wd)
		m.workspaces = wf
		for i, t := range wf.Tabs {
			if t.ID == tab.ID {
				m.wsList.cursor = i
				break
			}
		}
	} else if len(m.workspaces.Tabs) == 0 && m.cfg.WorkspacePath != "" {
		wf, _, _ := AddOrActivateWorkspace(m.cfg.WorkspacePath)
		m.workspaces = wf
	}
	m.hubPanel = panelNewSession
	m.sessList = listState{}
	m.wsList.clamp(len(m.workspaces.Tabs) - 1)
	if tab := ActiveWorkspace(m.workspaces); tab != nil {
		for i, t := range m.workspaces.Tabs {
			if t.ID == tab.ID {
				m.wsList.cursor = i
				break
			}
		}
	}
}

func osGetwd() (string, error) {
	return configLoadWd()
}

func (m rootModel) View() string {
	switch m.screen {
	case screenSplash:
		return enforceScreenBG(m.viewSplash(), m.width)
	case screenLogin:
		return enforceScreenBG(m.viewLogin(), m.width)
	case screenModeSelect:
		return enforceScreenBG(m.viewModeSelect(), m.width)
	case screenSetup:
		return enforceScreenBG(m.viewSetup(), m.width)
	case screenHub:
		return enforceScreenBG(m.viewHub(), m.width)
	case screenDaemonGate:
		return enforceScreenBG(m.viewDaemonGate(), m.width)
	case screenSession:
		if m.session != nil {
			m.session.chromeRows = unifiedSessionHeaderRows(m.tabCloseConfirmID != "")
			m.session.skipSessionHeader = true
			title := m.session.displayTurnTitle()
			innerW := sessionInnerWidth(m.width)
			headerPanel := renderSessionHeaderPanel(innerW, title, m.workspaces, m.openSessions, m.activeSessionIdx, m.tabCloseConfirmID, strings.ToUpper(string(m.cfg.Runtime)), m.session.connectorOnline)
			body := m.session.View()
			frame := lipgloss.JoinVertical(lipgloss.Left, headerPanel, body)
			innerH := m.height - 2*sessionFrameMargin
			return applySessionFrame(ensureFrameHeight(frame, innerW, innerH), m.width, m.height)
		}
		return renderLoadingScreen(m.width, m.height, 0, "Loading session", "Ctrl+C sair")
	}
	return ""
}

func (m rootModel) renderErrorLine() string {
	if m.errorLine == "" {
		return ""
	}
	return styleError.Render(m.errorLine)
}

func (m rootModel) viewSplash() string {
	body := renderWordmark(m.width)
	footer := styleDim.Render(fmt.Sprintf("v%s · Enter para continuar", version.Version))
	if m.bootLine != "" {
		footer = styleDim.Render(m.bootLine) + "\n" + footer
	}
	if el := m.renderErrorLine(); el != "" {
		footer = el + "\n" + footer
	}
	return renderScreenCentered(m.width, m.height, body+"\n\n"+footer)
}

func lipglossCenter(width, height int, s string) string {
	return renderScreenCentered(width, height, s)
}

// ── Mode selection screen ────────────────────────────────────────

var modeSelectChoice int // 0 = solo, 1 = team

func (m *rootModel) viewModeSelect() string {
	t := Theme()

	if m.modeSelectEnteringURL {
		title := t.StyleAccent.Bold(true).Render("TEAM Mode — VPS URL") + "\n\n"
		urlField := renderLoginInputField("API URL", m.modeSelectTeamURL.View(), true, loginCardInnerWidth(m.width))
		footer := "\n" + t.StyleDim.Render("Enter URL · Esc to go back")
		return renderPreSessionScreen(m.width, m.height, flowLogin,
			title+urlField+footer)
	}

	title := t.StyleAccent.Bold(true).Render("Welcome to CentralChat") + "\n\n"

	soloHighlight := "  "
	teamHighlight := "  "
	soloMarker := " "
	teamMarker := " "
	if modeSelectChoice == 0 {
		soloHighlight = t.StyleAccent.Render("▶ ")
		soloMarker = t.StyleAccent.Render("←")
	} else {
		teamHighlight = t.StyleAccent.Render("▶ ")
		teamMarker = t.StyleAccent.Render("←")
	}

	soloHeader := soloHighlight + "[S] " + t.StyleAccent.Bold(true).Render("SOLO") + "  " + soloMarker + "\n"
	soloHeader += "    Local, no server required.\n"
	soloHeader += "    Just your API key — no login, no VPS."

	teamHeader := teamHighlight + "[T] " + t.StyleAccent.Bold(true).Render("TEAM") + "  " + teamMarker + "\n"
	teamHeader += "    Connect to VPS (enterprise).\n"
	teamHeader += "    RBAC, approvals, work queue, audit."

	footer := "\n\n" + t.StyleDim.Render("S/T select · ↑↓ arrows · Enter confirm · Esc quit")

	return renderScreenCentered(m.width, m.height,
		title+soloHeader+"\n\n"+teamHeader+footer,
	)
}

func (m *rootModel) updateModeSelectKey(key tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch key.String() {
	case "s", "S":
		modeSelectChoice = 0
		return m.confirmModeSelection()
	case "t", "T":
		modeSelectChoice = 1
		// Enter URL input mode for TEAM
		m.modeSelectEnteringURL = true
		m.modeSelectTeamURL.Focus()
		return m, textinput.Blink
	case "up", "k":
		modeSelectChoice = 0
	case "down", "j":
		modeSelectChoice = 1
	case "enter":
		if modeSelectChoice == 1 {
			// TEAM: prompt for URL first
			m.modeSelectEnteringURL = true
			m.modeSelectTeamURL.Focus()
			return m, textinput.Blink
		}
		return m.confirmModeSelection()
	case "esc", "ctrl+c":
		return m, tea.Quit
	}
	return m, nil
}

func (m *rootModel) updateModeSelectURLKey(key tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch key.String() {
	case "enter":
		// Confirm URL and proceed
		url := strings.TrimSpace(m.modeSelectTeamURL.Value())
		if url == "" {
			url = "http://127.0.0.1:8004"
		}
		m.cfg.APIURL = url
		return m.confirmModeSelection()
	case "esc":
		m.modeSelectEnteringURL = false
		m.modeSelectTeamURL.Blur()
		return m, nil
	}
	var cmd tea.Cmd
	m.modeSelectTeamURL, cmd = m.modeSelectTeamURL.Update(key)
	return m, cmd
}

func (m *rootModel) confirmModeSelection() (tea.Model, tea.Cmd) {
	rt, _ := config.LoadRuntimeConfig()
	if rt == nil {
		rt = &config.RuntimeConfig{}
	}

	if modeSelectChoice == 0 {
		// SOLO mode
		rt.Mode = config.ModeSolo
		_ = config.SaveRuntimeConfig(rt)
		m.cfg.Runtime = config.ModeSolo

		// First boot without provider → setup screen
		if !config.HasAnyProvider() {
			m.screen = screenSetup
			m.initSetupWizard()
			return m, nil
		}

		m.screen = screenHub
		m.prepareHub()
		return m, tea.Batch(m.loadSessionsCmd(), m.loadWorkItemsCmd())
	}

	// TEAM mode
	rt.Mode = config.ModeTeam
	if m.cfg.APIURL != "" {
		rt.Team.APIURL = m.cfg.APIURL
	}
	_ = config.SaveRuntimeConfig(rt)
	m.cfg.Runtime = config.ModeTeam
	m.modeSelectEnteringURL = false
	return m, m.enterLoginScreen()
}
