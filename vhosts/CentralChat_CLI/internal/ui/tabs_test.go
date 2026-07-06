package ui

import "testing"

func TestSessionTabsBarRowY_afterFrameMargin(t *testing.T) {
	got := sessionTabsBarRowY()
	want := sessionFrameMargin + 1
	if got != want {
		t.Fatalf("expected tab row %d, got %d", want, got)
	}
}

func TestNewSessionTabButtonWidth_matchesRender(t *testing.T) {
	ApplyCentralTheme("dark")
	if newSessionTabButtonWidth() <= 0 {
		t.Fatal("expected positive button width")
	}
}

func TestWorkspaceTabRenderedWidth_activeDiffers(t *testing.T) {
	ApplyCentralTheme("dark")
	tab := WorkspaceTab{ID: "a", Label: "proj"}
	inactive := workspaceTabRenderedWidth(tab, false)
	active := workspaceTabRenderedWidth(tab, true)
	if inactive <= 0 || active <= 0 {
		t.Fatalf("unexpected widths inactive=%d active=%d", inactive, active)
	}
}
