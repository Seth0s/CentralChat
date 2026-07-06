package ui

import (
	"strconv"
	"strings"

	"github.com/charmbracelet/lipgloss"
)

// paintAssistantRow paints one assistant/markdown row on the #000 canvas.
// Used only for assistant message lines — never for input, footer, or user prompts.
func paintAssistantRow(width int, line string) string {
	canvas := chatCanvasStyle()
	if line == "" {
		return canvas.Width(width).Render("")
	}
	line = prepareAssistantANSI(line)
	lw := lipgloss.Width(line)
	if lw > width {
		line = trimVisual(line, width)
		lw = lipgloss.Width(line)
	}
	if lw >= width {
		return canvas.Width(width).Render(line)
	}
	return canvas.Render(line) + canvas.Render(strings.Repeat(" ", width-lw))
}

func prepareAssistantANSI(s string) string {
	s = stripANSIBackgrounds(s)
	return neutralizeANSIResets(s)
}

func neutralizeANSIResets(s string) string {
	if s == "" {
		return s
	}
	s = strings.ReplaceAll(s, "\x1b[0m", "\x1b[39m")
	s = strings.ReplaceAll(s, "\x1b[m", "\x1b[39m")
	return s
}

func stripANSIBackgrounds(s string) string {
	if s == "" || !strings.Contains(s, "\x1b[") {
		return s
	}
	var out strings.Builder
	i := 0
	for i < len(s) {
		if i+1 < len(s) && s[i] == '\x1b' && s[i+1] == '[' {
			j := i + 2
			for j < len(s) && s[j] != 'm' {
				j++
			}
			if j >= len(s) {
				out.WriteString(s[i:])
				break
			}
			if cleaned := filterSGRBackground(s[i : j+1]); cleaned != "" {
				out.WriteString(cleaned)
			}
			i = j + 1
			continue
		}
		out.WriteByte(s[i])
		i++
	}
	return out.String()
}

func filterSGRBackground(seq string) string {
	if len(seq) < 4 || seq[0] != '\x1b' || seq[1] != '[' || seq[len(seq)-1] != 'm' {
		return seq
	}
	raw := strings.Split(seq[2:len(seq)-1], ";")
	var kept []string
	for idx := 0; idx < len(raw); idx++ {
		p := raw[idx]
		if p == "" {
			continue
		}
		n, err := strconv.Atoi(p)
		if err != nil {
			kept = append(kept, p)
			continue
		}
		switch {
		case n == 48:
			if idx+1 < len(raw) {
				switch raw[idx+1] {
				case "5":
					if idx+2 < len(raw) {
						idx += 2
					}
				case "2":
					if idx+4 < len(raw) {
						idx += 4
					}
				}
			}
			continue
		case n == 49:
			continue
		case n >= 40 && n <= 47:
			continue
		case n >= 100 && n <= 107:
			continue
		default:
			kept = append(kept, p)
		}
	}
	if len(kept) == 0 {
		return ""
	}
	return "\x1b[" + strings.Join(kept, ";") + "m"
}
