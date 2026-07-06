package ui

import (
	"hash/fnv"
	"os"
	"strings"
	"sync"

	"github.com/charmbracelet/glamour"
)

const (
	maxMarkdownBytes = 32 << 10 // 32 KiB
	envMarkdownOff   = "CENTRAL_CLI_MARKDOWN"
)

var (
	markdownCache   sync.Map // cacheKey -> string
	rendererCache   sync.Map // rendererKey -> *glamour.TermRenderer
)

type cacheKey struct {
	width int
	theme string
	hash  uint64
}

type rendererKey struct {
	width int
	theme string
}

// MarkdownEnabled reports whether assistant markdown rendering is active.
func MarkdownEnabled() bool {
	v := strings.ToLower(strings.TrimSpace(os.Getenv(envMarkdownOff)))
	return v != "0" && v != "false" && v != "off" && v != "no"
}

// InvalidateMarkdownCache drops cached renders and renderers (e.g. after terminal resize).
func InvalidateMarkdownCache() {
	markdownCache = sync.Map{}
	rendererCache = sync.Map{}
}

// RenderAssistantMarkdown renders finalized assistant content for the TUI.
func RenderAssistantMarkdown(content string, width int) string {
	return renderAssistantMarkdown(content, width, false)
}

// RenderAssistantMarkdownLive renders streaming content: complete markdown blocks use
// Glamour; the trailing incomplete block stays plain to avoid broken fences mid-stream.
func RenderAssistantMarkdownLive(content string, width int) string {
	return renderAssistantMarkdown(content, width, true)
}

func renderAssistantMarkdown(content string, width int, live bool) string {
	content = trimPreserveNewlines(content, maxMarkdownBytes)
	if content == "" {
		return ""
	}
	if width < 16 {
		width = 16
	}
	if !MarkdownEnabled() {
		return wrapMultiline(content, width)
	}

	if live {
		return renderStreamingMarkdown(content, width)
	}

	themeName := themeNameForMarkdown()
	key := cacheKey{width: width, theme: themeName, hash: hashContent(content)}
	if cached, ok := markdownCache.Load(key); ok {
		return cached.(string)
	}

	rendered, err := renderBlockWithGlamour(content, width, themeName)
	if err != nil {
		return wrapMultiline(content, width)
	}
	rendered = strings.TrimRight(rendered, "\n")
	markdownCache.Store(key, rendered)
	return rendered
}

func renderStreamingMarkdown(content string, width int) string {
	themeName := themeNameForMarkdown()
	blocks := splitMarkdownBlocks(content)
	if len(blocks) == 0 {
		return ""
	}
	if len(blocks) == 1 {
		return wrapMultiline(blocks[0], width)
	}

	var parts []string
	for i := 0; i < len(blocks)-1; i++ {
		block := blocks[i]
		key := cacheKey{width: width, theme: themeName, hash: hashContent(block)}
		var rendered string
		if cached, ok := markdownCache.Load(key); ok {
			rendered = cached.(string)
		} else {
			var err error
			rendered, err = renderBlockWithGlamour(block, width, themeName)
			if err != nil {
				rendered = wrapMultiline(block, width)
			} else {
				rendered = strings.TrimRight(rendered, "\n")
				markdownCache.Store(key, rendered)
			}
		}
		if rendered != "" {
			parts = append(parts, rendered)
		}
	}
	tail := wrapMultiline(blocks[len(blocks)-1], width)
	if tail != "" {
		parts = append(parts, tail)
	}
	return strings.Join(parts, "\n")
}

// splitMarkdownBlocks splits on paragraph breaks while keeping fenced code blocks intact.
func splitMarkdownBlocks(s string) []string {
	raw := strings.Split(s, "\n\n")
	if len(raw) == 0 {
		return nil
	}
	var blocks []string
	var cur strings.Builder
	fenceCount := 0
	flush := func() {
		if cur.Len() == 0 {
			return
		}
		blocks = append(blocks, cur.String())
		cur.Reset()
		fenceCount = 0
	}
	for _, part := range raw {
		if cur.Len() > 0 {
			cur.WriteString("\n\n")
		}
		cur.WriteString(part)
		fenceCount += countFenceMarkers(part)
		if fenceCount%2 == 0 {
			flush()
		}
	}
	if cur.Len() > 0 {
		blocks = append(blocks, cur.String())
	}
	return blocks
}

func countFenceMarkers(s string) int {
	n := 0
	for _, line := range strings.Split(s, "\n") {
		trimmed := strings.TrimSpace(line)
		if strings.HasPrefix(trimmed, "```") {
			n++
		}
	}
	return n
}

func renderBlockWithGlamour(content string, width int, themeName string) (string, error) {
	r, err := getMarkdownRenderer(width, themeName)
	if err != nil {
		return "", err
	}
	return r.Render(content)
}

func getMarkdownRenderer(width int, themeName string) (*glamour.TermRenderer, error) {
	key := rendererKey{width: width, theme: themeName}
	if cached, ok := rendererCache.Load(key); ok {
		return cached.(*glamour.TermRenderer), nil
	}
	r, err := glamour.NewTermRenderer(
		glamour.WithStylesFromJSONBytes(centralMarkdownStyleJSON(themeName)),
		glamour.WithWordWrap(width),
	)
	if err != nil {
		return nil, err
	}
	rendererCache.Store(key, r)
	return r, nil
}

func themeNameForMarkdown() string {
	themeName := Theme().Name
	if themeName == "" {
		return "dark"
	}
	return themeName
}

func hashContent(s string) uint64 {
	h := fnv.New64a()
	_, _ = h.Write([]byte(s))
	return h.Sum64()
}
