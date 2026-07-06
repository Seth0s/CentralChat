package ui

import (
	"strings"

	"github.com/charmbracelet/lipgloss"
)

// fitRow pads or truncates one styled row to exactly width using style (background fill).
func fitRow(line string, width int, style lipgloss.Style) string {
	return fillRowWidth(width, line, style)
}

// joinHorizontalBlocks places two blocks side-by-side, one output row per line index.
// Each row is leftW + gapW + rightW; gap and both sides share the session canvas (black).
func joinHorizontalBlocks(left, right string, leftW, gapW, rightW int) string {
	leftLines := splitLines(left)
	rightLines := splitLines(right)
	h := len(leftLines)
	if len(rightLines) > h {
		h = len(rightLines)
	}
	canvas := chatCanvasStyle()
	gap := ""
	if gapW > 0 {
		gap = canvas.Width(gapW).Render("")
	}
	rows := make([]string, h)
	for i := 0; i < h; i++ {
		ll := ""
		if i < len(leftLines) {
			ll = leftLines[i]
		}
		rl := ""
		if i < len(rightLines) {
			rl = rightLines[i]
		}
		rows[i] = fitRow(ll, leftW, canvas) + gap + fitRow(rl, rightW, panelCellStyle())
	}
	return strings.Join(rows, "\n")
}

// fitBlockHeight pads or truncates a block to exactly height lines at width.
func fitBlockHeight(block string, width, height int, style lipgloss.Style) string {
	return renderStyledColumn(block, width, height, 0, style)
}

func splitLines(s string) []string {
	s = strings.TrimRight(s, "\n")
	if s == "" {
		return nil
	}
	return strings.Split(s, "\n")
}
