package ui

import (
	"strings"

	"github.com/charmbracelet/lipgloss"
)

// PickerPanel is a reusable scrollable list panel used by /model, /agent, /tools.
// It manages cursor position, scroll offset, and rendering — leaving item-specific
// styling and actions to the caller.
type PickerPanel struct {
	Cursor     int
	Offset     int
	MaxVisible int
	Focused    bool
}

// Navigate moves the cursor up (-1) or down (+1), clamping and adjusting scroll.
func (p *PickerPanel) Navigate(total int, dir int) {
	if dir < 0 && p.Cursor > 0 {
		p.Cursor--
	}
	if dir > 0 && p.Cursor < total-1 {
		p.Cursor++
	}
	p.clamp(total)
}

// NavigateTo moves the cursor to a specific index and adjusts scroll.
func (p *PickerPanel) NavigateTo(idx, total int) {
	if idx >= 0 && idx < total {
		p.Cursor = idx
	}
	p.clamp(total)
}

// PageUp moves the viewport up by MaxVisible items.
func (p *PickerPanel) PageUp(total int) {
	p.Offset = max(p.Offset-p.MaxVisible, 0)
	p.Cursor = p.Offset
	p.clamp(total)
}

// PageDown moves the viewport down by MaxVisible items.
func (p *PickerPanel) PageDown(total int) {
	p.Offset = min(p.Offset+p.MaxVisible, max(total-p.MaxVisible, 0))
	p.Cursor = p.Offset
	p.clamp(total)
}

// Reset clears cursor and offset.
func (p *PickerPanel) Reset() {
	p.Cursor = 0
	p.Offset = 0
}

// VisibleRange returns the [start, end) slice range for currently visible items.
func (p *PickerPanel) VisibleRange(total int) (start, end int) {
	start = p.Offset
	end = start + p.MaxVisible
	if end > total {
		end = total
	}
	if start >= total {
		start = max(total-p.MaxVisible, 0)
		end = total
	}
	return
}

// VisibleSlice returns the subset of items currently visible.
func (p *PickerPanel) VisibleSlice(items []string) []string {
	total := len(items)
	start, end := p.VisibleRange(total)
	if start >= total {
		return nil
	}
	return items[start:end]
}

// GlobalIdx returns the index of the cursor within VisibleSlice, or -1.
func (p *PickerPanel) GlobalIdx(offset int) int {
	return p.Cursor - offset
}

func (p *PickerPanel) clamp(total int) {
	if total <= 0 {
		p.Cursor = 0
		p.Offset = 0
		return
	}
	if p.Cursor < 0 {
		p.Cursor = 0
	}
	if p.Cursor >= total {
		p.Cursor = total - 1
	}
	// Keep cursor visible
	if p.Cursor < p.Offset {
		p.Offset = p.Cursor
	}
	if p.Cursor >= p.Offset+p.MaxVisible {
		p.Offset = p.Cursor - p.MaxVisible + 1
	}
	// Clamp offset
	if p.Offset < 0 {
		p.Offset = 0
	}
	if p.Offset > max(total-p.MaxVisible, 0) {
		p.Offset = max(total-p.MaxVisible, 0)
	}
}

// ── Panel rendering helpers ───────────────────────────────────────────

// PanelView renders a scrollable panel with ▲▼ indicators.
// lines: pre-rendered item lines (already styled by caller).
// The caller is responsible for padding to panelRows after this call.
func PanelView(lines []string, panel PickerPanel, total int, width int, normalStyle, dimStyle lipgloss.Style) []string {
	vis := panel.MaxVisible
	var out []string

	// Scroll up indicator
	if panel.Offset > 0 {
		out = append(out, dimStyle.Render(padOrTrunc("▲", width)))
	} else {
		out = append(out, normalStyle.Render(strings.Repeat(" ", width)))
	}

	// Visible items
	out = append(out, lines...)

	// Fill remaining slots
	for len(out) < vis+1 {
		out = append(out, normalStyle.Render(strings.Repeat(" ", width)))
	}

	// Scroll down indicator
	if panel.Offset+vis < total {
		out = append(out, dimStyle.Render(padOrTrunc("▼", width)))
	} else {
		out = append(out, normalStyle.Render(strings.Repeat(" ", width)))
	}

	return out
}

// PanelPad pads lines to exactly panelRows using normalStyle fill.
func PanelPad(lines []string, panelRows int, width int, normalStyle lipgloss.Style) []string {
	for len(lines) < panelRows {
		lines = append(lines, normalStyle.Render(strings.Repeat(" ", width)))
	}
	if len(lines) > panelRows {
		lines = lines[:panelRows]
	}
	return lines
}

// GapColumn returns a styled vertical separator column for use with JoinHorizontal.
func GapColumn(height int, bg lipgloss.Color) string {
	style := lipgloss.NewStyle().Background(bg).Foreground(lipgloss.Color(ColorBorder))
	lines := make([]string, height)
	for i := 0; i < height; i++ {
		lines[i] = style.Render("│")
	}
	return strings.Join(lines, "\n")
}
