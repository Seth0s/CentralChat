package ui

import (
	"os"
	"strings"
	"testing"
)

func TestRenderAssistantMarkdown_disabledUsesPlain(t *testing.T) {
	t.Setenv(envMarkdownOff, "off")
	ApplyCentralTheme("dark")
	InvalidateMarkdownCache()

	md := "## Title\n\nHello **world**"
	out := RenderAssistantMarkdown(md, 60)
	if strings.Contains(out, "\x1b[") {
		t.Fatalf("expected plain text when markdown disabled, got ANSI: %q", out)
	}
	if !strings.Contains(out, "Title") || !strings.Contains(out, "world") {
		t.Fatalf("expected content preserved: %q", out)
	}
}

func TestRenderAssistantMarkdown_rendersANSI(t *testing.T) {
	os.Unsetenv(envMarkdownOff)
	ApplyCentralTheme("dark")
	InvalidateMarkdownCache()

	md := "## Heading\n\nParagraph with **bold**."
	out := RenderAssistantMarkdown(md, 72)
	if !strings.Contains(out, "\x1b[") {
		t.Fatalf("expected ANSI styling from glamour: %q", out)
	}
	if !strings.Contains(out, "Heading") || !strings.Contains(out, "bold") {
		t.Fatalf("expected markdown text in output: %q", out)
	}
}

func TestRenderAssistantMarkdown_cacheHit(t *testing.T) {
	os.Unsetenv(envMarkdownOff)
	ApplyCentralTheme("dark")
	InvalidateMarkdownCache()

	md := "List:\n\n- one\n- two"
	first := RenderAssistantMarkdown(md, 50)
	second := RenderAssistantMarkdown(md, 50)
	if first != second {
		t.Fatal("expected cache to return identical output")
	}
}

func TestRenderAssistantMarkdown_streamingBlocks(t *testing.T) {
	os.Unsetenv(envMarkdownOff)
	ApplyCentralTheme("dark")
	InvalidateMarkdownCache()

	md := "## Done\n\nThis paragraph is complete.\n\n## Streaming"
	out := RenderAssistantMarkdownLive(md, 60)
	if !strings.Contains(out, "\x1b[") {
		t.Fatalf("expected glamour on complete blocks: %q", out)
	}
	if !strings.Contains(out, "Streaming") {
		t.Fatalf("expected tail in output: %q", out)
	}
}

func TestSplitMarkdownBlocks_keepsFences(t *testing.T) {
	md := "intro\n\n```go\nfmt.Println(\"a\")\n\nstill inside\")\n```\n\nafter"
	blocks := splitMarkdownBlocks(md)
	if len(blocks) != 3 {
		t.Fatalf("expected 3 blocks, got %d: %#v", len(blocks), blocks)
	}
	if !strings.Contains(blocks[1], "still inside") {
		t.Fatalf("fence block should not split on inner blank line: %q", blocks[1])
	}
}

func TestRenderAssistantMarkdown_oversizeTruncated(t *testing.T) {
	os.Unsetenv(envMarkdownOff)
	ApplyCentralTheme("dark")
	InvalidateMarkdownCache()

	huge := strings.Repeat("x", maxMarkdownBytes+100)
	out := RenderAssistantMarkdown(huge, 40)
	if len(out) > maxMarkdownBytes+200 {
		t.Fatalf("output unexpectedly large: %d bytes", len(out))
	}
}
