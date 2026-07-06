package ui

import (
	"fmt"
	"strings"
	"time"

	"github.com/charmbracelet/lipgloss"
)

func centerScreen(width, height int, content string) string {
	return renderScreenCentered(width, height, content)
}

// panelLine renders one full-width row with panel background.
func panelLine(width int, content string) string {
	return fillRowWidth(width, content, panelCellStyle())
}

var spinnerFrames = []string{"⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"}

func renderLoadingScreen(width, height int, frame int, title, hint string) string {
	if title == "" {
		title = "A inicializar"
	}
	spin := spinnerFrames[frame%len(spinnerFrames)]
	body := styleAccent.Render(spin+" "+title) + "…"
	if hint != "" {
		body += "\n\n" + styleDim.Render(hint)
	}
	return renderScreenCentered(width, height, body)
}

func loginFieldWidth(termWidth int) int {
	return loginCardInnerWidth(termWidth)
}

// renderContextBar draws a gradient usage bar: colored fill fades toward empty.
// Uses true-color ANSI backgrounds for smooth gradient matching the input bar.
func renderContextBar(pct, width int) string {
	if width < 6 {
		width = 6
	}
	if pct < 0 {
		pct = 0
	}
	if pct > 100 {
		pct = 100
	}
	inner := width - 2
	if inner < 2 {
		inner = 2
	}
	filled := (pct * inner) / 100
	if filled > inner {
		filled = inner
	}

	// Gradient color: blue (#39) normal, red (#1) when >= 85%
	barColor := lipgloss.Color("39")
	if pct >= 85 {
		barColor = lipgloss.Color("1")
	}
	r, g, b := hexToRGB(string(barColor))

	var sb strings.Builder
	sb.WriteString("[")
	for col := 0; col < inner; col++ {
		if col < filled {
			alpha := float64(col) / float64(filled)
			if filled <= 0 {
				alpha = 1.0
			}
			rr := uint8(float64(r) * (1.0 - alpha))
			gg := uint8(float64(g) * (1.0 - alpha))
			bb := uint8(float64(b) * (1.0 - alpha))
			sb.WriteString(fmt.Sprintf("\x1b[48;2;%d;%d;%dm \x1b[0m", rr, gg, bb))
		} else {
			sb.WriteString(fmt.Sprintf("\x1b[48;5;16m \x1b[0m"))
		}
	}
	sb.WriteString("]")
	return sb.String()
}

func formatTokenCount(n int) string {
	if n >= 1_000_000 {
		return fmt.Sprintf("%.1fM tokens", float64(n)/1_000_000)
	}
	if n >= 10_000 {
		return fmt.Sprintf("%dK tokens", n/1000)
	}
	if n >= 1000 {
		return fmt.Sprintf("%.1fK tokens", float64(n)/1000)
	}
	return fmt.Sprintf("%d tokens", n)
}

// renderProgressBar draws a block progress bar for context usage (0–100).
func renderProgressBar(pct, width int) string {
	if width < 4 {
		width = 4
	}
	if pct < 0 {
		pct = 0
	}
	if pct > 100 {
		pct = 100
	}
	inner := width - 2
	filled := (pct * inner) / 100
	if filled > inner {
		filled = inner
	}
	t := Theme()
	fillStyle := t.StyleProgressFill
	if pct >= 85 {
		fillStyle = t.StyleProgressWarn
	}
	emptyStyle := t.StyleProgressEmpty
	bar := "[" + fillStyle.Render(strings.Repeat("█", filled)) +
		emptyStyle.Render(strings.Repeat("░", inner-filled)) + "]"
	return bar + fmt.Sprintf(" %d%%", pct)
}

func renderDuration(d time.Duration) string {
	if d <= 0 {
		return "—"
	}
	if d < time.Minute {
		if d < time.Second {
			return fmt.Sprintf("%dms", d.Milliseconds())
		}
		return fmt.Sprintf("%.1fs", d.Seconds())
	}
	m := int(d.Minutes())
	s := int(d.Seconds()) % 60
	return fmt.Sprintf("%dm %02ds", m, s)
}

func formatTokensK(n int) string {
	if n < 1000 {
		return fmt.Sprintf("%d", n)
	}
	return fmt.Sprintf("%.1fK", float64(n)/1000)
}

func formatTokensComma(n int) string {
	if n < 1000 {
		return fmt.Sprintf("%d tokens", n)
	}
	s := fmt.Sprintf("%d", n)
	var parts []string
	for len(s) > 3 {
		parts = append([]string{s[len(s)-3:]}, parts...)
		s = s[:len(s)-3]
	}
	if s != "" {
		parts = append([]string{s}, parts...)
	}
	return strings.Join(parts, ",") + " tokens"
}

func lineCount(s string) int {
	if s == "" {
		return 0
	}
	return strings.Count(s, "\n") + 1
}

func padLines(n int) string {
	if n <= 0 {
		return ""
	}
	return strings.Repeat("\n", n)
}

func alignRight(width int, s string) string {
	if width < 1 {
		return s
	}
	return lipgloss.NewStyle().Width(width).Align(lipgloss.Right).Render(s)
}

// renderFilledPanel renders exactly height lines, each with full width background.
func renderFilledPanel(content string, width, height int, style lipgloss.Style) string {
	if height < 1 {
		height = 1
	}
	style = style.Copy().Padding(0, 0)
	raw := strings.Split(content, "\n")
	if len(raw) > height {
		raw = raw[:height]
	}
	var lines []string
	for _, line := range raw {
		lines = append(lines, fillRowWidth(width, line, style))
	}
	for len(lines) < height {
		lines = append(lines, style.Width(width).Render(""))
	}
	return strings.Join(lines, "\n")
}

func renderVerticalSeparator(height int) string {
	if height < 1 {
		return ""
	}
	t := Theme()
	style := panelCellStyle()
	var lines []string
	for i := 0; i < height; i++ {
		lines = append(lines, style.Width(1).Render(t.StyleSeparator.Render("│")))
	}
	return strings.Join(lines, "\n")
}

func centerOverlay(width, height int, content string) string {
	if width < 1 {
		width = 80
	}
	if height < 1 {
		height = 24
	}
	return lipgloss.Place(width, height, lipgloss.Center, lipgloss.Center, content)
}

// overlayModal overlays a content block centered on top of base.
// Base is the full chat body; the modal floats on top with the canvas
// still visible above and below. Terminal has no alpha — the modal's own
// Background(#232) provides the visual distinction.
func overlayModal(base string, modal string, termW, baseH int) string {
	baseLines := strings.Split(base, "\n")
	modalLines := strings.Split(modal, "\n")

	// Pad base to exactly baseH lines
	for len(baseLines) < baseH {
		baseLines = append(baseLines, "")
	}
	if len(baseLines) > baseH {
		baseLines = baseLines[:baseH]
	}

	modalW := lipgloss.Width(modalLines[0])
	for _, ln := range modalLines {
		if w := lipgloss.Width(ln); w > modalW {
			modalW = w
		}
	}

	// Center vertically
	startLine := (baseH - len(modalLines)) / 2
	if startLine < 0 {
		startLine = 0
	}

	canvasBG := "\x1b[48;5;0m"

	for i := 0; i < len(modalLines) && startLine+i < baseH; i++ {
		// Center the modal line horizontally
		leftPad := (termW - modalW) / 2
		if leftPad < 0 {
			leftPad = 0
		}
		// Left padding with canvas background, then modal line with its own bg
		overlayLine := canvasBG + strings.Repeat(" ", leftPad) + modalLines[i]
		// Fill rest of line with canvas background
		rightFill := termW - lipgloss.Width(overlayLine)
		// Account for the canvasBG prefix (not visible width)
		visibleW := leftPad + lipgloss.Width(modalLines[i])
		rightFill = termW - visibleW
		if rightFill > 0 {
			overlayLine += canvasBG + strings.Repeat(" ", rightFill)
		}
		baseLines[startLine+i] = overlayLine
	}

	return strings.Join(baseLines, "\n")
}

func renderListRow(selected bool, left, right string) string {
	t := Theme()
	row := left
	if right != "" {
		pad := 28 - len(left)
		if pad < 1 {
			pad = 1
		}
		row += strings.Repeat(" ", pad) + t.StyleDim.Render(right)
	}
	if selected {
		return t.StyleListActive.Render("▸ " + row)
	}
	return t.StyleListRow.Render("  " + row)
}
