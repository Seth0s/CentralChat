package ui

import (
	"fmt"
	"os"
	"os/exec"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/bubbles/textinput"
	"github.com/centralchurch/central-cli/internal/config"
	"github.com/centralchurch/central-cli/internal/websearch"
)

// ── Wizard steps ──────────────────────────────────────────────

type setupStep int

const (
	setupWizardProviders setupStep = iota // configure API keys
	setupWizardTools                       // browser-use & deps
	setupWizardDefaults                    // workspace & model
	setupWizardInstall                    // installing dependencies (spinner)
)

// Sub-states for providers step
type providerSubStep int

const (
	subPick  providerSubStep = iota // browsing provider list
	subEdit                         // editing key for one provider
)

// ── Provider list ─────────────────────────────────────────────

type setupProvider struct {
	Kind  config.ProviderKind
	Label string
}

var setupProviders = []setupProvider{
	{Kind: config.ProviderOpenRouter, Label: "OpenRouter"},
	{Kind: config.ProviderLlamaCpp, Label: "llama.cpp (local)"},
	{Kind: config.ProviderOpenAI, Label: "OpenAI"},
	{Kind: config.ProviderAnthropic, Label: "Anthropic"},
	{Kind: config.ProviderDeepSeek, Label: "DeepSeek"},
}

func providerByKind(k config.ProviderKind) (setupProvider, bool) {
	for _, p := range setupProviders {
		if p.Kind == k {
			return p, true
		}
	}
	return setupProvider{}, false
}

// ── View ──────────────────────────────────────────────────────

func (m rootModel) viewSetup() string {
	t := Theme()
	w := m.width
	b := strings.Builder{}

	// Step header
	steps := []string{"Providers", "Tools", "Defaults", "Install"}
	b.WriteString(t.StyleAccent.Bold(true).Render("CentralChat Setup") + "\n\n")
	for i, s := range steps {
		if i < int(m.setupWizardStep) {
			b.WriteString(t.StyleAccent.Render("✓ " + s))
		} else if i == int(m.setupWizardStep) {
			if m.setupWizardStep == setupWizardInstall && m.setupInstalling {
				b.WriteString(t.StyleAccent.Bold(true).Render("● Installing..."))
			} else {
				b.WriteString(t.StyleAccent.Bold(true).Render("● " + s))
			}
		} else {
			b.WriteString(styleDim.Render("○ " + s))
		}
		if i < len(steps)-1 {
			b.WriteString("  →  ")
		}
	}
	b.WriteString("\n\n")
	b.WriteString(strings.Repeat("─", min(60, w-10)))
	b.WriteString("\n\n")

	switch m.setupWizardStep {
	case setupWizardProviders:
		m.viewSetupProviders(&b, t)
	case setupWizardTools:
		m.viewSetupTools(&b, t)
	case setupWizardDefaults:
		m.viewSetupDefaults(&b, t)
	case setupWizardInstall:
		m.viewSetupInstall(&b, t)
	}

	// Navigation
	b.WriteString("\n")
	if m.setupWizardStep == setupWizardInstall {
		// Installing — no navigation, just wait
		b.WriteString(styleDim.Render("Installing dependencies..."))
	} else {
		if m.setupWizardStep > setupWizardProviders {
			b.WriteString(styleDim.Render("← Back   "))
		}
		if m.setupWizardStep < setupWizardDefaults {
			nextLabel := "Next →"
			if m.setupWizardStep == setupWizardProviders {
				anyKey := false
				for _, v := range m.setupKeys {
					if v != "" { anyKey = true; break }
				}
				if !anyKey {
					nextLabel = styleDim.Render("Next → (configure at least one provider)")
				} else {
					nextLabel = t.StyleAccent.Render("Next →")
				}
			}
			if m.setupWizardStep == setupWizardTools {
				nextLabel = t.StyleAccent.Render("Next →")
			}
			b.WriteString(nextLabel)
		} else if m.setupWizardStep == setupWizardDefaults {
			b.WriteString(t.StyleAccent.Bold(true).Render("Start →"))
		}
		b.WriteString("   " + styleDim.Render("Esc cancel"))
	}

	// Card
	cardW := loginCardWidth(w)
	card := wrapBlock(b.String(), cardW)

	// Layout
	fill := screenFillStyle()
	blank := fill.Width(w).Render("")
	logo := blockCenterScreenRows(w, renderWordmark(w))
	cardBlock := blockCenterScreenRows(w, card)

	body := strings.Join([]string{logo, blank, cardBlock}, "\n")
	return verticalCenterOnScreen(w, m.height, body)
}

// ── Step 1: Providers ─────────────────────────────────────────

func (m rootModel) viewSetupProviders(b *strings.Builder, t CentralTheme) {
	switch m.providerSubStep {
	case subPick:
		for i, p := range setupProviders {
			configured := m.setupKeys[string(p.Kind)] != ""
			prefix := "  "
			status := "  ⬚"
			labelStyle := styleDim
			if i == m.setupCursor {
				prefix = t.StyleAccent.Render("▶ ")
				labelStyle = t.StyleAccent
			}
			if configured {
				status = t.StyleAccent.Render("  ✓")
			}
			b.WriteString(prefix)
			b.WriteString(labelStyle.Render(p.Label))
			b.WriteString(status)
			b.WriteString("\n")
		}
		b.WriteString(styleDim.Render("\n↑↓ choose   Enter configure"))

	case subEdit:
		sp, ok := providerByKind(m.setupProviderKind)
		if !ok {
			b.WriteString("Invalid provider")
			return
		}
		b.WriteString(t.StyleAccent.Bold(true).Render(sp.Label) + "\n\n")
		b.WriteString(t.StyleLabel.Render("API Key: "))
		b.WriteString(m.setupKeyInput.View())
		b.WriteString(styleDim.Render("\n\nEnter save   Esc back"))
	}
}

// ── Step 2: Tools & Dependencies ──────────────────────────────

func (m rootModel) viewSetupTools(b *strings.Builder, t CentralTheme) {
	b.WriteString(t.StyleLabel.Render("Browser-Use (web search)") + "\n\n")

	// Native status
	nativeOK := websearch.NativeAvailable()
	dockerOK := websearch.DockerAvailable()
	containerOK := websearch.ContainerAvailable()

	options := []struct {
		label   string
		status  string
		selected bool
	}{
		{"Native (pip install)", statusIcon(nativeOK), m.setupToolsChoice == 0},
		{"Docker container", statusIcon(containerOK || dockerOK), m.setupToolsChoice == 1},
		{"Skip (DuckDuckGo only)", "  —", m.setupToolsChoice == 2},
	}

	for i, opt := range options {
		prefix := "  "
		if i == m.setupToolsCursor {
			prefix = t.StyleAccent.Render("▶ ")
		}
		b.WriteString(prefix)
		b.WriteString(opt.status + "  ")
		if i == m.setupToolsCursor {
			b.WriteString(t.StyleAccent.Render(opt.label))
		} else {
			b.WriteString(styleDim.Render(opt.label))
		}
		b.WriteString("\n")
	}

	b.WriteString(styleDim.Render("\n↑↓ choose   Enter select"))
}

func statusIcon(ok bool) string {
	if ok {
		return "✓"
	}
	return "⬚"
}

// ── Step 3: Defaults ──────────────────────────────────────────

func (m rootModel) viewSetupDefaults(b *strings.Builder, t CentralTheme) {
	b.WriteString(t.StyleLabel.Render("Default Settings") + "\n\n")

	b.WriteString("Workspace: ")
	b.WriteString(t.StyleInput.Render(m.setupWorkspaceInput.View()))
	b.WriteString("\n\n")

	b.WriteString("Default Model: ")
	b.WriteString(t.StyleInput.Render(m.setupModelInput.View()))
	b.WriteString(styleDim.Render("\n(leave empty for provider default)"))

	b.WriteString(styleDim.Render("\n\n↑↓ switch field   Enter save"))
}

// ── Step 4: Install ──────────────────────────────────────────

func (m rootModel) viewSetupInstall(b *strings.Builder, t CentralTheme) {
	b.WriteString(t.StyleAccent.Bold(true).Render("Installing Dependencies") + "\n\n")

	if m.setupToolsChoice == 0 {
		b.WriteString("Browser-Use (native):\n")
		b.WriteString("  pip install browser-use langchain-openai playwright\n")
		b.WriteString("  playwright install chromium\n")
	} else if m.setupToolsChoice == 1 {
		b.WriteString("Browser-Use (Docker):\n")
		b.WriteString("  docker pull centralchat/browser-use:latest\n")
	}

	b.WriteString("\n")
	if m.setupInstalling {
		spinner := []string{"⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"}
		frame := spinner[m.setupInstallFrame%len(spinner)]
		b.WriteString(t.StyleAccent.Render(frame + " Installing..."))
	} else if m.setupInstallOutput != "" {
		b.WriteString(styleDim.Render(m.setupInstallOutput))
	}
}

type installDoneMsg struct {
	err    error
	output string
}

// ── Update ────────────────────────────────────────────────────

func (m *rootModel) updateSetupKey(key tea.KeyMsg) (tea.Model, tea.Cmd) {
	// Global Esc — cancel setup
	if key.String() == "esc" {
		// If editing provider key, go back to pick
		if m.setupWizardStep == setupWizardProviders && m.providerSubStep == subEdit {
			m.providerSubStep = subPick
			m.setupKeyInput.Blur()
			return m, nil
		}
		// Go back to Hub
		return m.cancelSetup()
	}

	switch m.setupWizardStep {
	case setupWizardProviders:
		return m.updateSetupProviders(key)
	case setupWizardTools:
		return m.updateSetupTools(key)
	case setupWizardDefaults:
		return m.updateSetupDefaults(key)
	}
	return m, nil
}

func (m *rootModel) updateSetupProviders(key tea.KeyMsg) (tea.Model, tea.Cmd) {
	k := key.String()

	if m.providerSubStep == subEdit {
		switch k {
		case "enter":
			key := strings.TrimSpace(m.setupKeyInput.Value())
			if m.setupKeys == nil {
				m.setupKeys = make(map[string]string)
			}
			m.setupKeys[string(m.setupProviderKind)] = key
			m.providerSubStep = subPick
			m.setupKeyInput.Blur()
			return m, nil
		case "esc":
			m.providerSubStep = subPick
			m.setupKeyInput.Blur()
			return m, nil
		default:
			var cmd tea.Cmd
			m.setupKeyInput, cmd = m.setupKeyInput.Update(key)
			return m, cmd
		}
	}

	// subPick — browsing provider list
	switch k {
	case "up", "k":
		if m.setupCursor > 0 {
			m.setupCursor--
		}
	case "down", "j":
		if m.setupCursor < len(setupProviders)-1 {
			m.setupCursor++
		}
	case "enter":
		sp := setupProviders[m.setupCursor]
		m.setupProviderKind = sp.Kind
		m.providerSubStep = subEdit
		ki := textinput.New()
		ki.Placeholder = "sk-... or URL"
		ki.CharLimit = 200
		ki.Width = 36
		ki.EchoMode = textinput.EchoPassword
		ki.EchoCharacter = '•'
		if existing := m.setupKeys[string(sp.Kind)]; existing != "" {
			ki.SetValue(existing)
		}
		ki.Focus()
		m.setupKeyInput = ki
		return m, textinput.Blink
	case "right", "n":
		// Next step (if at least one provider configured)
		for _, v := range m.setupKeys {
			if v != "" {
				m.setupWizardStep = setupWizardTools
				return m, nil
			}
		}
	}
	return m, nil
}

func (m *rootModel) updateSetupTools(key tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch key.String() {
	case "up", "k":
		if m.setupToolsCursor > 0 {
			m.setupToolsCursor--
		}
	case "down", "j":
		if m.setupToolsCursor < 2 {
			m.setupToolsCursor++
		}
	case "enter":
		m.setupToolsChoice = m.setupToolsCursor
		// Installation happens when "Start" is clicked on the Defaults step
	case "left", "b":
		m.setupWizardStep = setupWizardProviders
	case "right", "n":
		m.setupWizardStep = setupWizardDefaults
	}
	return m, nil
}

func (m *rootModel) updateSetupDefaults(key tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch key.String() {
	case "up", "k":
		m.setupDefaultsField = 0
		m.setupWorkspaceInput.Focus()
		m.setupModelInput.Blur()
	case "down", "j":
		m.setupDefaultsField = 1
		m.setupWorkspaceInput.Blur()
		m.setupModelInput.Focus()
	case "enter":
		// Check if install needed before finishing
		if m.setupToolsChoice == 0 && !websearch.NativeAvailable() {
			m.setupWizardStep = setupWizardInstall
			m.setupInstalling = true
			m.setupInstallFrame = 0
			return m, tea.Batch(installBrowserUseCmd(), tickEvery(100*time.Millisecond))
		}
		return m.finishSetup()
	case "left", "b":
		m.setupWizardStep = setupWizardTools
	default:
		var cmd tea.Cmd
		if m.setupDefaultsField == 0 {
			m.setupWorkspaceInput, cmd = m.setupWorkspaceInput.Update(key)
			return m, cmd
		}
		m.setupModelInput, cmd = m.setupModelInput.Update(key)
		return m, cmd
	}
	return m, nil
}

func installBrowserUseCmd() tea.Cmd {
	return func() tea.Msg {
		cmd := exec.Command("pip", "install", "browser-use", "langchain-openai", "playwright")
		output, err := cmd.CombinedOutput()
		if err != nil {
			return installDoneMsg{err: err, output: string(output)}
		}
		cmd = exec.Command("playwright", "install", "chromium")
		output2, err := cmd.CombinedOutput()
		return installDoneMsg{err: err, output: string(output) + "\n" + string(output2)}
	}
}

// ── Finish Setup ───────────────────────────────────────────────

func (m *rootModel) finishSetup() (tea.Model, tea.Cmd) {
	workspace := strings.TrimSpace(m.setupWorkspaceInput.Value())
	model := strings.TrimSpace(m.setupModelInput.Value())

	rt, err := config.LoadRuntimeConfig()
	if err != nil || rt == nil {
		rt = &config.RuntimeConfig{Mode: config.ModeSolo}
	}
	if rt.Solo.Providers == nil {
		rt.Solo.Providers = make(map[string]config.ProviderConfig)
	}

	// Save providers
	for kindStr, key := range m.setupKeys {
		if key == "" {
			continue
		}
		kind := config.ProviderKind(kindStr)
		rt.Solo.Providers[kindStr] = config.ProviderConfig{
			Kind:   kind,
			APIKey: key,
			Model:  defaultModelFor(kind),
		}
		if rt.Solo.DefaultProvider == "" {
			rt.Solo.DefaultProvider = kindStr
		}
	}

	if len(rt.Solo.Providers) == 0 {
		m.errorLine = "No provider configured."
		return m, nil
	}

	if workspace != "" {
		rt.Solo.Model = model
	}
	if model != "" && rt.Solo.Model == "" {
		rt.Solo.Model = model
	}

	if err := config.SaveRuntimeConfig(rt); err != nil {
		m.errorLine = fmt.Sprintf("Failed to save config: %v", err)
		return m, nil
	}

	// Save workspace
	if workspace != "" {
		_ = config.SaveWorkspace(workspace)
	}

	m.cfg.Runtime = config.ModeSolo
	m.errorLine = ""
	return m.cancelSetup()
}

func (m *rootModel) cancelSetup() (tea.Model, tea.Cmd) {
	if m.setupFromSession {
		m.setupFromSession = false
		m.screen = screenSession
		return m, nil
	}
	m.screen = screenHub
	m.prepareHub()
	return m, tea.Batch(m.loadSessionsCmd(), m.loadWorkItemsCmd())
}

func defaultModelFor(k config.ProviderKind) string {
	switch k {
	case config.ProviderOpenRouter:
		return "openai/gpt-4o-mini"
	case config.ProviderLlamaCpp:
		return "local-model"
	case config.ProviderOpenAI:
		return "gpt-4o"
	case config.ProviderAnthropic:
		return "claude-sonnet-4-20250514"
	case config.ProviderDeepSeek:
		return "deepseek-chat"
	default:
		return ""
	}
}

// ── Init setup state ──────────────────────────────────────────

func (m *rootModel) initSetupWizard() {
	m.setupWizardStep = setupWizardProviders
	m.providerSubStep = subPick
	m.setupCursor = 0
	m.setupKeys = make(map[string]string)
	m.setupToolsCursor = 0
	m.setupToolsChoice = 0
	m.setupDefaultsField = 0

	wd, _ := os.Getwd()
	wsInput := textinput.New()
	wsInput.SetValue(wd)
	wsInput.Width = 40
	m.setupWorkspaceInput = wsInput

	modelInput := textinput.New()
	modelInput.Placeholder = "provider default"
	modelInput.Width = 40
	m.setupModelInput = modelInput
}

// ── Handle background install messages ────────────────────────

func (m rootModel) handleSetupMsg(msg tea.Msg) (tea.Model, tea.Cmd) {
	return m, nil
}
