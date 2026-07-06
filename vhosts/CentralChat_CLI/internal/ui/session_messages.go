package ui

import (
	"fmt"
	"strings"
	"time"

	"github.com/charmbracelet/lipgloss"
)

func formatThoughtMs(ms int64) string {
	if ms <= 0 {
		return "—"
	}
	if ms < 1000 {
		return fmt.Sprintf("%dms", ms)
	}
	return fmt.Sprintf("%.1fs", float64(ms)/1000)
}

func thoughtLabel(open bool, ms int64) string {
	prefix := "+"
	if open {
		prefix = "−"
	}
	return prefix + " Thought: " + formatThoughtMs(ms)
}

func renderMessageBlock(line chatLine, width int, live bool) string {
	switch line.role {
	case "user":
		return renderUserMessageBlock(line, width)
	case "assistant":
		return renderAssistantMessageBlock(line, width, live)
	default:
		innerW := width - 4
		if innerW < 16 {
			innerW = 16
		}
		return Theme().StyleDim.Render(wrap(trim(line.content, 2000), innerW))
	}
}

func renderUserMessageBlock(line chatLine, innerW int) string {
	chip, barColor := modeInputChipAndBar(line.turnMode)
	contentW := innerW - 3
	if contentW < 12 {
		contentW = 12
	}
	bar := lipgloss.NewStyle().Foreground(barColor).Bold(true).Render("▌")
	wrapped := strings.Split(wrap(trim(line.content, 2000), contentW), "\n")
	var rows []string
	for i, ln := range wrapped {
		if i == 0 {
			rows = append(rows, bar+" "+chip.Render(ln))
		} else {
			rows = append(rows, "  "+chip.Render(ln))
		}
	}
	return strings.Join(rows, "\n")
}

func renderAssistantMessageBlock(line chatLine, innerW int, live bool) string {
	t := Theme()
	if innerW < 16 {
		innerW = 16
	}
	_, modeColor := modeInputChipAndBar(line.turnMode)
	thoughtStyle := lipgloss.NewStyle().
		Foreground(modeColor).
		Italic(true).
		Underline(true)

	var parts []string
	hasThought := line.thought != "" || line.thoughtMs > 0 || live
	if hasThought {
		ms := line.thoughtMs
		if live && ms == 0 {
			ms = 1
		}
		parts = append(parts, "  "+thoughtStyle.Render(thoughtLabel(line.thoughtOpen, ms)))
		if line.thoughtOpen && line.thought != "" {
			parts = append(parts, "  "+t.StyleDim.Render(wrap(line.thought, innerW-4)))
		}
	}

	body := renderAssistantBody(line.content, innerW-2, live)
	if body != "" {
		parts = append(parts, body)
	}

	dur := line.duration
	if dur > 0 || live {
		meta := "▣ " + modeDisplayName(line.turnMode)
		if dur > 0 {
			meta += " · " + renderDuration(dur)
		}
		parts = append(parts, t.StyleDim.Render("  "+meta))
	}

	return strings.Join(parts, "\n")
}

func renderAssistantBody(content string, width int, live bool) string {
	content = trimPreserveNewlines(content, maxMarkdownBytes)
	if content == "" {
		return ""
	}
	if live {
		return RenderAssistantMarkdownLive(content, width)
	}
	return RenderAssistantMarkdown(content, width)
}

func (m model) liveThoughtMs() int64 {
	if m.thinkingStartedAt.IsZero() {
		return 0
	}
	return time.Since(m.thinkingStartedAt).Milliseconds()
}

func (m *model) toggleLastThought() {
	for i := len(m.messages) - 1; i >= 0; i-- {
		if m.messages[i].role == "assistant" && (m.messages[i].thought != "" || m.messages[i].thoughtMs > 0) {
			m.messages[i].thoughtOpen = !m.messages[i].thoughtOpen
			return
		}
	}
	if m.streaming && (m.thinking != "" || m.thinkingActive) {
		m.streamingThoughtOpen = !m.streamingThoughtOpen
	}
}

func (m *model) scrollChatBy(delta int) {
	innerCW := chatContentWidth(m.chatWidth(), contentInset(sessionInnerWidth(m.width)))
	msgH := m.messageViewportHeight()
	sticky, scrollable := m.buildChatLayout(innerCW)
	maxOff := maxChatScrollOffset(sticky, scrollable, msgH)
	m.chatScrollOffset += delta
	if m.chatScrollOffset < 0 {
		m.chatScrollOffset = 0
	}
	if m.chatScrollOffset > maxOff {
		m.chatScrollOffset = maxOff
	}
	// Track whether user scrolled away from bottom
	m.userScrolledUp = m.chatScrollOffset < maxOff
}

func (m *model) scrollChatToBottom() {
	innerCW := chatContentWidth(m.chatWidth(), contentInset(sessionInnerWidth(m.width)))
	msgH := m.messageViewportHeight()
	sticky, scrollable := m.buildChatLayout(innerCW)
	m.chatScrollOffset = maxChatScrollOffset(sticky, scrollable, msgH)
	m.userScrolledUp = false
}

func (m model) messageViewportHeight() int {
	inset := contentInset(sessionInnerWidth(m.width))
	cw := m.chatWidth()
	footerH := len(m.buildChatFooterLines(cw, inset))
	contentH := m.contentHeight()
	msgH := contentH - footerH
	if msgH < 1 {
		return 1
	}
	return msgH
}

func (m model) isMouseInMessageViewport(mouseY int) bool {
	if m.width == 0 || m.height == 0 {
		return false
	}
	headerRows := m.chromeRows
	if headerRows <= 0 {
		headerRows = unifiedSessionHeaderRows(false)
	}
	top := sessionFrameMargin + headerRows + sessionFrameMargin
	bottom := top + m.messageViewportHeight()
	return mouseY >= top && mouseY < bottom
}
