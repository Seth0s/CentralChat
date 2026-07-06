package ui

import (
	"strings"

	"github.com/charmbracelet/lipgloss"
)

// panelCellStyle is the grid cell style: full-width background, no padding.
func panelCellStyle() lipgloss.Style {
	return Theme().StylePanel.Copy().Padding(0, 0)
}

// chatCanvasStyle — dark gray canvas for chat column.
func chatCanvasStyle() lipgloss.Style {
	return lipgloss.NewStyle().Background(lipgloss.Color(ColorCanvas)).Padding(0, 0)
}

// styleOnChatCanvas adds chat-canvas background to a style (header/chat chrome).
func styleOnChatCanvas(s lipgloss.Style) lipgloss.Style {
	return s.Copy().Background(lipgloss.Color(ColorCanvas))
}

// chatCanvasSpace is one space on the black session canvas.
func chatCanvasSpace() string {
	return styleOnChatCanvas(lipgloss.NewStyle()).Render(" ")
}

// screenFillStyle paints pre-session screens (splash/login). Session chat uses chatCanvasStyle.
func screenFillStyle() lipgloss.Style {
	return Theme().StyleScreen.Copy().Padding(0, 0)
}

// renderScreenFill paints width×height with the screen background.
func renderScreenFill(width, height int) string {
	if height < 1 {
		height = 1
	}
	return renderFilledPanel("", width, height, screenFillStyle())
}

// embedInScreenRow centers one styled line without re-rendering inner ANSI (preserves borders).
func embedInScreenRow(screenW int, line string) string {
	fill := screenFillStyle()
	if line == "" {
		return fill.Width(screenW).Render("")
	}
	lw := lipgloss.Width(line)
	lp := (screenW - lw) / 2
	if lp < 0 {
		lp = 0
	}
	rp := screenW - lp - lw
	if rp < 0 {
		rp = 0
	}
	return fill.Render(strings.Repeat(" ", lp)) + line + fill.Render(strings.Repeat(" ", rp))
}

// blockCenterScreenRows centers a multi-line block; each row spans screenW with #232 margins.
func blockCenterScreenRows(screenW int, block string) string {
	block = strings.TrimRight(block, "\n")
	if block == "" {
		return ""
	}
	lines := strings.Split(block, "\n")
	maxW := 0
	for _, ln := range lines {
		if ln == "" {
			continue
		}
		if w := lipgloss.Width(ln); w > maxW {
			maxW = w
		}
	}
	leftPad := (screenW - maxW) / 2
	if leftPad < 0 {
		leftPad = 0
	}
	fill := screenFillStyle()
	out := make([]string, len(lines))
	for i, ln := range lines {
		if ln == "" {
			out[i] = fill.Width(screenW).Render("")
			continue
		}
		lw := lipgloss.Width(ln)
		rp := screenW - leftPad - lw
		if rp < 0 {
			rp = 0
		}
		out[i] = fill.Render(strings.Repeat(" ", leftPad)) + ln + fill.Render(strings.Repeat(" ", rp))
	}
	return strings.Join(out, "\n")
}

// verticalCenterOnScreen places full-width rows vertically centered on a filled screen.
func verticalCenterOnScreen(width, height int, content string) string {
	screen := strings.Split(renderScreenFill(width, height), "\n")
	contentLines := strings.Split(content, "\n")
	top := (height - len(contentLines)) / 2
	if top < 0 {
		top = 0
	}
	fill := screenFillStyle()
	for i, ln := range contentLines {
		y := top + i
		if y >= height {
			break
		}
		if ln == "" {
			screen[y] = fill.Width(width).Render("")
		} else {
			screen[y] = ln
		}
	}
	return strings.Join(screen, "\n")
}

// renderScreenCentered fills the terminal and centers content without gray gaps.
func renderScreenCentered(width, height int, content string) string {
	if width < 1 {
		width = 80
	}
	if height < 1 {
		height = 24
	}
	content = strings.TrimRight(content, "\n")
	if content == "" {
		return renderScreenFill(width, height)
	}
	filled := blockCenterScreenRows(width, content)
	return verticalCenterOnScreen(width, height, filled)
}

// padBlockToWidth left-aligns each line of a rendered block to totalWidth with bg and gutter.
func padBlockToWidth(block string, totalWidth int, style lipgloss.Style, gutter int) string {
	style = style.Copy().Padding(0, 0)
	lines := strings.Split(block, "\n")
	out := make([]string, len(lines))
	for i, ln := range lines {
		out[i] = fillRowWidth(totalWidth, indentWithGutter(ln, gutter), style)
	}
	return strings.Join(out, "\n")
}

// padBlockPlain left-aligns a block to totalWidth without painting row backgrounds.
func padBlockPlain(block string, totalWidth, gutter int) string {
	lines := strings.Split(block, "\n")
	out := make([]string, len(lines))
	for i, ln := range lines {
		out[i] = plainRow(totalWidth, ln, gutter)
	}
	return strings.Join(out, "\n")
}

// renderColumn renders exactly height lines at width with panel background.
func renderColumn(content string, width, height int) string {
	return renderFilledPanel(content, width, height, panelCellStyle())
}

// ensureFrameHeight pads the bottom with black canvas rows if the frame is shorter than height.
func ensureFrameHeight(content string, width, height int) string {
	h := lipgloss.Height(content)
	if h >= height {
		return content
	}
	canvas := chatCanvasStyle()
	var pad []string
	for i := 0; i < height-h; i++ {
		pad = append(pad, canvas.Width(width).Render(""))
	}
	return content + "\n" + strings.Join(pad, "\n")
}

const (
	sessionFrameMargin = 1 // minimal outer inset (almost imperceptible)
	sessionColumnGap   = 1 // gap between chat column and sidebar
)

// sessionInnerWidth is the usable width inside the session frame margins.
func sessionInnerWidth(termW int) int {
	w := termW - 2*sessionFrameMargin
	if w < 40 {
		w = 40
	}
	return w
}

// applySessionFrame adds a minimal margin; rows are painted black to match the session canvas.
func applySessionFrame(content string, termW, termH int) string {
	margin := sessionFrameMargin
	canvas := chatCanvasStyle()
	raw := strings.Split(strings.TrimRight(content, "\n"), "\n")

	var lines []string
	for i := 0; i < margin; i++ {
		lines = append(lines, canvas.Width(termW).Render(""))
	}
	for _, ln := range raw {
		lines = append(lines, fillRowWidth(termW, indentWithGutter(ln, margin), canvas))
	}
	for len(lines) < termH {
		lines = append(lines, canvas.Width(termW).Render(""))
	}
	if len(lines) > termH {
		lines = lines[:termH]
	}
	return enforceScreenBG(strings.Join(lines, "\n"), termW)
}

// renderGapColumn renders a narrow transparent gap between panels.
func renderGapColumn(height, gapW int) string {
	if gapW <= 0 || height < 1 {
		return ""
	}
	var lines []string
	for i := 0; i < height; i++ {
		lines = append(lines, strings.Repeat(" ", gapW))
	}
	return strings.Join(lines, "\n")
}

// contentInset returns symmetric horizontal inset inside session panels.
func contentInset(termWidth int) int {
	if termWidth >= 100 {
		return 2
	}
	return 1
}

// contentGutter is the left inset applied when rendering panel rows.
func contentGutter(termWidth int) int {
	return contentInset(termWidth)
}

// chatContentWidth is usable text width inside a chat column after symmetric inset.
func chatContentWidth(colW, inset int) int {
	w := colW - inset*2
	if w < 16 {
		w = 16
	}
	return w
}

func indentWithGutter(line string, gutter int) string {
	if gutter <= 0 || line == "" {
		return line
	}
	return strings.Repeat(" ", gutter) + line
}

// renderStyledColumn renders rows with a given fill style and optional left gutter.
func renderStyledColumn(content string, width, height, gutter int, style lipgloss.Style) string {
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
		if line == "" {
			lines = append(lines, style.Width(width).Render(""))
			continue
		}
		lines = append(lines, fillRowWidth(width, indentWithGutter(line, gutter), style))
	}
	for len(lines) < height {
		lines = append(lines, style.Width(width).Render(""))
	}
	return strings.Join(lines, "\n")
}

// renderColumnGuttered renders a panel column with inset content.
func renderColumnGuttered(content string, width, height, gutter int) string {
	return renderStyledColumn(content, width, height, gutter, panelCellStyle())
}

// renderTransparentColumn renders rows without painting a background (terminal canvas shows through).
func renderTransparentColumn(content string, width, height, gutter int) string {
	return renderPlainColumn(content, width, height, gutter)
}

func transparentLine(width int, content string, gutter int) string {
	return plainRow(width, content, gutter)
}

// renderPlainFill returns height rows of spaces at width (no ANSI background).
func renderPlainFill(width, height int) string {
	if height < 1 {
		return ""
	}
	row := strings.Repeat(" ", width)
	lines := make([]string, height)
	for i := range lines {
		lines[i] = row
	}
	return strings.Join(lines, "\n")
}

// renderPlainColumn left-aligns content rows with optional gutter; pads/truncates to width.
func renderPlainColumn(content string, width, height, gutter int) string {
	if height < 1 {
		height = 1
	}
	raw := strings.Split(content, "\n")
	if len(raw) > height {
		raw = raw[:height]
	}
	lines := make([]string, 0, height)
	for _, line := range raw {
		lines = append(lines, plainRow(width, line, gutter))
	}
	for len(lines) < height {
		lines = append(lines, strings.Repeat(" ", width))
	}
	return strings.Join(lines, "\n")
}

func plainRow(width int, content string, gutter int) string {
	line := indentWithGutter(content, gutter)
	lw := lipgloss.Width(line)
	if lw > width {
		return trimVisual(line, width)
	}
	if lw < width {
		return line + strings.Repeat(" ", width-lw)
	}
	return line
}

func trimVisual(s string, width int) string {
	if width < 1 {
		return ""
	}
	if lipgloss.Width(s) <= width {
		return s
	}
	// Walk runes until visual width exceeds limit (preserves leading ANSI when possible).
	var b strings.Builder
	w := 0
	for _, r := range s {
		rw := lipgloss.Width(string(r))
		if w+rw > width {
			break
		}
		b.WriteRune(r)
		w += rw
	}
	return b.String()
}

func panelLineGuttered(width int, content string, gutter int) string {
	return fillRowWidth(width, indentWithGutter(content, gutter), panelCellStyle())
}

// fillRowWidth pads a session row to exact width using concat (keeps inner styles intact).
func fillRowWidth(width int, line string, style lipgloss.Style) string {
	style = style.Copy().Padding(0, 0)
	if line == "" {
		return style.Width(width).Render("")
	}
	lw := lipgloss.Width(line)
	if lw > width {
		line = trimVisual(line, width)
		lw = lipgloss.Width(line)
	}
	if lw >= width {
		return line
	}
	return style.Render(line) + style.Render(strings.Repeat(" ", width-lw))
}

// enforceBackground ensures every line has the given background from start to full width.
// Patches internal SGR resets so the background survives inline style boundaries.
func enforceBackground(content string, width int, bgColor string) string {
	if width < 1 {
		return content
	}
	// Convert hex to 256-color ANSI prefix
	bgPrefix := hexToAnsiBg(bgColor)
	bgStyle := lipgloss.NewStyle().Background(lipgloss.Color(bgColor))
	lines := strings.Split(strings.TrimRight(content, "\n"), "\n")
	out := make([]string, len(lines))
	for i, ln := range lines {
		if ln == "" {
			out[i] = bgStyle.Width(width).Render("")
		} else {
			patched := strings.ReplaceAll(ln, "\x1b[0m", "\x1b[0m"+bgPrefix)
			lw := lipgloss.Width(patched)
			if lw < width {
				out[i] = bgPrefix + patched + bgStyle.Render(strings.Repeat(" ", width-lw))
			} else if lw > width {
				out[i] = bgPrefix + trimVisual(patched, width)
			} else {
				out[i] = bgPrefix + patched
			}
		}
	}
	return strings.Join(out, "\n")
}

// enforceScreenBG wraps enforceBackground with ColorCanvas.
func enforceScreenBG(content string, width int) string {
	return enforceBackground(content, width, ColorCanvas)
}

// hexToAnsiBg converts a hex color like "#252526" to 256-color ANSI bg prefix.
func hexToAnsiBg(hex string) string {
	return "\x1b[48;5;16m" // default to black; lipgloss handles hex→256 mapping internally
}
