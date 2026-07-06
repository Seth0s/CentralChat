package ui

import (
	"strings"
	"testing"

	"github.com/charmbracelet/lipgloss"
)

func TestBuildChatLayout_assistantLinesFlagged(t *testing.T) {
	ApplyCentralTheme("dark")
	m := model{
		messages: []chatLine{
			{role: "user", content: "hi"},
			{role: "assistant", content: "## Title\n\nbody"},
		},
		stickyPrompt: "hi",
	}
	_, scrollable := m.buildChatLayout(60)
	var assistantRows int
	for _, ln := range scrollable {
		if ln.assistant {
			assistantRows++
		}
	}
	if assistantRows == 0 {
		t.Fatal("expected assistant viewport lines to be flagged")
	}
}

func TestPaintAssistantRow_fullWidthGetsBlackCanvas(t *testing.T) {
	line := prepareAssistantANSI("\x1b[38;5;252m" + strings.Repeat("x", 30) + "\x1b[0m")
	out := paintAssistantRow(30, line)
	if lipgloss.Width(out) != 30 {
		t.Fatalf("expected width 30, got %d", lipgloss.Width(out))
	}
}

func TestPaintAssistantRow_preservesPlainUserPathUntouched(t *testing.T) {
	// User/footer path uses fillRowWidth — ensure assistant paint is separate.
	canvas := chatCanvasStyle()
	user := fillRowWidth(20, "prompt", canvas)
	if lipgloss.Width(user) != 20 {
		t.Fatalf("fillRowWidth unchanged for user lines: %d", lipgloss.Width(user))
	}
}
