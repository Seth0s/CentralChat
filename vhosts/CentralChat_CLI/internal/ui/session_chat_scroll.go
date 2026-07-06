package ui

import (
	"strings"
	"time"
)

func lastUserMessageIndex(msgs []chatLine) int {
	for i := len(msgs) - 1; i >= 0; i-- {
		if msgs[i].role == "user" {
			return i
		}
	}
	return -1
}

// displayTurnTitle is the active turn label: the user question currently visible in the viewport.
// When scrolled to the bottom (latest turn), shows the latest user question.
// When scrolled up to an older turn, shows that turn's user question.
func (m model) displayTurnTitle() string {
	// When at bottom (no scroll or showing latest), prefer stickyPrompt (last question)
	if m.chatScrollOffset == 0 {
		if s := strings.TrimSpace(m.stickyPrompt); s != "" {
			return s
		}
	}
	// Dynamic: show user question of the turn currently in view
	if m.visibleTurnUserIdx >= 0 && m.visibleTurnUserIdx < len(m.messages) {
		if m.messages[m.visibleTurnUserIdx].role == "user" {
			return m.messages[m.visibleTurnUserIdx].content
		}
	}
	// Fallback: last user message
	if idx := lastUserMessageIndex(m.messages); idx >= 0 {
		return m.messages[idx].content
	}
	return strings.TrimSpace(m.sessionTitle)
}

func splitRenderedLines(block string) []string {
	block = strings.TrimRight(block, "\n")
	if block == "" {
		return nil
	}
	return strings.Split(block, "\n")
}

// buildChatLayout splits transcript into sticky (pinned last user prompt) and scrollable tail.
func (m model) buildChatLayout(innerCW int) (sticky, scrollable []chatViewportLine) {
	pinnedIdx := m.pinnedUserMessageIndex()

	if line, ok := m.pinnedUserLine(); ok {
		sticky = appendViewportBlockWithTurn(sticky, renderUserMessageBlock(line, innerCW), false, pinnedIdx)
	}

	currentTurnUserIdx := -1
	for i, msg := range m.messages {
		if pinnedIdx >= 0 && i == pinnedIdx {
			continue
		}
		if msg.role == "user" {
			currentTurnUserIdx = i
		}
		scrollable = appendViewportBlockWithTurn(scrollable, m.renderChatMessageBlock(msg, innerCW, false), msg.role == "assistant", currentTurnUserIdx)
	}

	if m.streaming && (m.streamingText != "" || m.thinking != "" || m.thinkingActive || !m.thinkingStartedAt.IsZero()) {
		streamLine := chatLine{
			role:        "assistant",
			content:     m.streamingText,
			thought:     m.thinking,
			thoughtMs:   m.liveThoughtMs(),
			thoughtOpen: m.streamingThoughtOpen,
			turnMode:    m.interactionMode,
		}
		if !m.streamStartedAt.IsZero() {
			streamLine.duration = time.Since(m.streamStartedAt)
		}
		scrollable = appendViewportBlockWithTurn(scrollable, renderAssistantMessageBlock(streamLine, innerCW, true), true, currentTurnUserIdx)
	}

	if m.approval != nil {
		scrollable = appendViewportBlock(scrollable, renderApprovalCard(m.approval, innerCW), false)
	}
	if m.clarify != nil {
		scrollable = appendViewportBlock(scrollable, renderClarifyCard(m.clarify, innerCW), false)
	}

	// Tool execution timeline
	if len(m.toolLog.Calls) > 0 {
		toolLines := m.renderToolLog(innerCW)
		for _, ln := range toolLines {
			scrollable = append(scrollable, chatViewportLine{text: ln})
		}
	}

	return sticky, scrollable
}

func (m model) pinnedUserLine() (chatLine, bool) {
	if strings.TrimSpace(m.stickyPrompt) != "" {
		mode := m.stickyPromptMode
		if mode == "" {
			mode = modeBuild
		}
		return chatLine{role: "user", content: m.stickyPrompt, turnMode: mode}, true
	}
	idx := lastUserMessageIndex(m.messages)
	if idx < 0 {
		return chatLine{}, false
	}
	return m.messages[idx], true
}

func (m model) pinnedUserMessageIndex() int {
	if strings.TrimSpace(m.stickyPrompt) == "" {
		return lastUserMessageIndex(m.messages)
	}
	for i := len(m.messages) - 1; i >= 0; i-- {
		if m.messages[i].role != "user" {
			continue
		}
		if m.messages[i].content == m.stickyPrompt {
			return i
		}
	}
	return lastUserMessageIndex(m.messages)
}

func (m *model) syncStickyPromptFromMessages() {
	idx := lastUserMessageIndex(m.messages)
	if idx < 0 {
		m.stickyPrompt = ""
		return
	}
	m.stickyPrompt = m.messages[idx].content
	m.stickyPromptMode = m.messages[idx].turnMode
	if m.stickyPromptMode == "" {
		m.stickyPromptMode = modeBuild
	}
}

func (m model) renderChatMessageBlock(msg chatLine, innerCW int, live bool) string {
	switch msg.role {
	case "user":
		return renderUserMessageBlock(msg, innerCW)
	case "assistant":
		return renderAssistantMessageBlock(msg, innerCW, live)
	default:
		return renderMessageBlock(msg, innerCW, live)
	}
}

func layoutStickyChatViewport(sticky, scrollable []chatViewportLine, msgH, offset int) []chatViewportLine {
	if msgH < 1 {
		msgH = 1
	}
	stickyH := len(sticky)
	if stickyH > msgH {
		return sticky[:msgH]
	}
	avail := msgH - stickyH
	if avail < 1 {
		return sticky[:msgH]
	}

	if len(scrollable) <= avail {
		out := make([]chatViewportLine, 0, msgH)
		out = append(out, sticky...)
		for i := 0; i < avail-len(scrollable); i++ {
			out = append(out, chatViewportLine{})
		}
		out = append(out, scrollable...)
		return out
	}

	maxOff := len(scrollable) - avail
	if offset > maxOff {
		offset = maxOff
	}
	if offset < 0 {
		offset = 0
	}

	out := make([]chatViewportLine, 0, msgH)
	out = append(out, sticky...)
	out = append(out, scrollable[offset:offset+avail]...)
	return out
}

func maxChatScrollOffset(sticky, scrollable []chatViewportLine, msgH int) int {
	stickyH := len(sticky)
	avail := msgH - stickyH
	if avail < 1 {
		return 0
	}
	if len(scrollable) <= avail {
		return 0
	}
	return len(scrollable) - avail
}
