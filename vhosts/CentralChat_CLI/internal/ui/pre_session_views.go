package ui

import (
	"strings"

	"github.com/charmbracelet/lipgloss"
)

type flowStep int

const (
	flowLogin flowStep = iota
	flowWorkspace
	flowSession
)

func flowStepForScreen(s appScreen) flowStep {
	switch s {
	case screenLogin:
		return flowLogin
	case screenHub, screenDaemonGate:
		return flowWorkspace
	case screenSession:
		return flowSession
	default:
		return flowLogin
	}
}

func renderFlowStepper(active flowStep) string {
	t := Theme()
	bg := lipgloss.Color(ColorCanvas)
	accent := t.StyleAccent.Copy().Background(bg)
	dim := t.StyleDim.Copy().Background(bg)
	done := lipgloss.NewStyle().Background(bg).Foreground(lipgloss.Color("42"))
	labels := []string{"Login", "Workspace", "Session"}
	var parts []string
	for i, lbl := range labels {
		if i > 0 {
			parts = append(parts, dim.Render(" ── "))
		}
		step := flowStep(i)
		text := lbl
		switch {
		case step == active:
			parts = append(parts, accent.Bold(true).Render("● "+text))
		case step < active:
			parts = append(parts, done.Render("✓ "+text))
		default:
			parts = append(parts, dim.Render("○ "+text))
		}
	}
	return strings.Join(parts, "")
}

// renderPreSessionScreen stacks ASCII logo, flow stepper, and form card (login/hub/daemon).
func renderPreSessionScreen(width, height int, step flowStep, cardBody string) string {
	fill := screenFillStyle()
	blank := fill.Width(width).Render("")

	logo := blockCenterScreenRows(width, renderWordmark(width))
	stepper := embedInScreenRow(width, renderFlowStepper(step))
	card := blockCenterScreenRows(width, renderPreSessionCard(width, cardBody))

	body := strings.Join([]string{logo, blank, stepper, blank, card}, "\n")
	return verticalCenterOnScreen(width, height, body)
}

func loginCardWidth(termW int) int {
	w := min(52, termW-12)
	if w < 36 {
		w = termW - 8
	}
	if w < 32 {
		w = 32
	}
	return w
}

func loginCardInnerWidth(termW int) int {
	// card border (2) + horizontal padding (2×1)
	return loginCardWidth(termW) - 4
}

func renderLoginInputField(label, fieldView string, focused bool, width int) string {
	t := Theme()
	lbl := t.StyleDim.Render(label)
	if focused {
		lbl = t.StyleAccent.Render("▸ " + label)
	}
	// width is card content area. StyleInput border adds 2 chars → subtract to fit.
	boxW := width - 2
	box := t.StyleInput.Width(boxW)
	if focused {
		box = t.StyleInputFocus.Width(boxW)
	}
	// textinput.View() trailing padding is plain spaces after the last SGR reset.
	// Inject bg=232 AFTER the last reset so trailing spaces get background.
	if fieldView != "" {
		if idx := strings.LastIndex(fieldView, "\x1b[0m"); idx >= 0 {
			fieldView = fieldView[:idx+4] + "\x1b[48;5;232m" + fieldView[idx+4:]
		} else if idx := strings.LastIndex(fieldView, "\x1b[m"); idx >= 0 {
			fieldView = fieldView[:idx+3] + "\x1b[48;5;232m" + fieldView[idx+3:]
		} else {
			fieldView = "\x1b[48;5;232m" + fieldView
		}
	}
	return lbl + "\n" + box.Render(fieldView) + "\n"
}

func renderSegmentedControl(labels []string, active int) string {
	t := Theme()
	parts := make([]string, len(labels))
	for i, l := range labels {
		if i == active {
			parts[i] = t.StyleTabActive.Render(" " + l + " ")
		} else {
			parts[i] = t.StyleTab.Render(" " + l + " ")
		}
	}
	return strings.Join(parts, "")
}

func renderPreSessionCard(termW int, body string) string {
	cardW := loginCardWidth(termW)
	return Theme().StyleCard.Width(cardW).Render(body)
}

func renderLoginActions(busy bool) string {
	t := Theme()
	line := t.StyleTabActive.Render(" Entrar ")
	if busy {
		return line + "\n" + t.StyleDim.Render("A autenticar…")
	}
	return line
}

func renderLoginHints() string {
	return Theme().StyleDim.Render("Tab: method · ↑↓: field · Enter: login · d: doctor · q: quit")
}
