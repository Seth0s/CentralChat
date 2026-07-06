package ui

import (
	"strings"
	"testing"
)

func TestDisplayTurnTitle_prefersStickyOverSessionTitle(t *testing.T) {
	m := model{
		sessionTitle: "Tese",
		stickyPrompt: "Ultima pergunta",
		messages: []chatLine{
			{role: "user", content: "Tese"},
			{role: "user", content: "Outra"},
		},
	}
	if got := m.displayTurnTitle(); got != "Ultima pergunta" {
		t.Fatalf("expected sticky prompt, got %q", got)
	}
}

func TestBuildChatLayout_stickyPinsLastUserPrompt(t *testing.T) {
	ApplyCentralTheme("dark")
	m := model{
		messages: []chatLine{
			{role: "user", content: "Tese", turnMode: modeBuild},
			{role: "assistant", content: "ola"},
			{role: "user", content: "Ultima pergunta", turnMode: modePlan},
			{role: "assistant", content: "resposta"},
		},
		stickyPrompt:     "Ultima pergunta",
		stickyPromptMode: modePlan,
	}
	sticky, scrollable := m.buildChatLayout(60)
	stickyText := joinViewportText(sticky)
	scrollText := joinViewportText(scrollable)
	if !strings.Contains(stickyText, "Ultima") {
		t.Fatalf("sticky should contain last user prompt, got %q", stickyText)
	}
	if strings.Contains(stickyText, "Tese") {
		t.Fatalf("sticky should not contain session/first prompt: %q", stickyText)
	}
	if !strings.Contains(scrollText, "Tese") {
		t.Fatalf("scrollable should contain earlier user prompt: %q", scrollText)
	}
}

func TestPinnedUserMessageIndex_matchesStickyContent(t *testing.T) {
	m := model{
		messages: []chatLine{
			{role: "user", content: "Tese"},
			{role: "assistant", content: "a"},
			{role: "user", content: "Nova"},
		},
		stickyPrompt: "Nova",
	}
	if got := m.pinnedUserMessageIndex(); got != 2 {
		t.Fatalf("expected pinned index 2, got %d", got)
	}
}

func joinViewportText(lines []chatViewportLine) string {
	parts := make([]string, 0, len(lines))
	for _, ln := range lines {
		parts = append(parts, ln.text)
	}
	return strings.Join(parts, " ")
}
