package ui

import (
	"fmt"
	"math"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/charmbracelet/lipgloss"
)

// ── Tool Call Model ──

type toolCallStatus string

const (
	toolQueued  toolCallStatus = "queued"
	toolRunning toolCallStatus = "running"
	toolDone    toolCallStatus = "done"
)

type toolCall struct {
	Name         string
	Params       string          // main parameter (path, pattern, command)
	Status       toolCallStatus
	StartedAt    time.Time
	Duration     time.Duration
	Preview      string          // result preview from SSE (40 chars)
	DiffLines    []string        // for write/patch tools
	DiffExpanded bool
}

type toolLog struct {
	Calls    []toolCall
	DiffOpen int // index of the tool whose diff is expanded (-1 = none)
}

const maxToolLog = 20

func (tl *toolLog) add(call toolCall) {
	tl.Calls = append(tl.Calls, call)
	if len(tl.Calls) > maxToolLog {
		// Drop oldest, keeping most recent
		n := len(tl.Calls) - maxToolLog
		tl.Calls = append([]toolCall(nil), tl.Calls[n:]...)
	}
}

func (tl *toolLog) findByAction(actionID string) int {
	// actionID doubles as Name for matching pending → started transitions
	for i := len(tl.Calls) - 1; i >= 0; i-- {
		if tl.Calls[i].Name == actionID {
			return i
		}
	}
	return -1
}

func (tl *toolLog) lastRunning() int {
	for i := len(tl.Calls) - 1; i >= 0; i-- {
		if tl.Calls[i].Status == toolRunning {
			return i
		}
	}
	return -1
}

func (tl *toolLog) clear() {
	tl.Calls = nil
	tl.DiffOpen = -1
}

// ── Render ──

// renderToolLog renders all tool calls in the log as viewport lines.
// Returns the rendered lines and the total line count.
func (m model) renderToolLog(innerCW int) []string {
	if len(m.toolLog.Calls) == 0 {
		return nil
	}

	var lines []string
	for i := range m.toolLog.Calls {
		tc := &m.toolLog.Calls[i]
		toolLines := m.renderToolLine(tc, innerCW, i == m.toolLog.DiffOpen)
		lines = append(lines, toolLines...)
		// Separator between tools
		if i < len(m.toolLog.Calls)-1 {
			lines = append(lines, "")
		}
	}
	return lines
}

// renderToolLine renders one tool call: icon+name+params+status, progress bar, optional diff.
func (m model) renderToolLine(tc *toolCall, cw int, diffOpen bool) []string {
	var lines []string
	t := Theme()

	// ── Row 1: icon name · params  status time ──
	icon := toolIcon(tc.Name)
	label := toolLabel(tc.Name)
	params := truncateToWidth(tc.Params, cw-30)
	if params == "" {
		params = tc.Params
	}

	statusStr := toolStatusStr(tc)
	timeStr := ""
	if tc.Status == toolRunning {
		timeStr = fmt.Sprintf("%.1fs", time.Since(tc.StartedAt).Seconds())
	} else if tc.Duration > 0 {
		timeStr = fmt.Sprintf("%dms", tc.Duration.Milliseconds())
	}

	// Left part: icon label params
	left := fmt.Sprintf("%s %s %s", icon, label, params)
	// Right part: status time
	right := fmt.Sprintf("%s %s", statusStr, timeStr)

	leftW := utf8.RuneCountInString(left)
	rightW := utf8.RuneCountInString(right)
	padW := cw - leftW - rightW - 4 // 4 = indent
	if padW < 1 {
		padW = 1
	}
	line := fmt.Sprintf("  %s%s%s", left, strings.Repeat(" ", padW), right)

	var style lipgloss.Style
	switch tc.Status {
	case toolDone:
		style = t.StyleDim.Copy().Foreground(lipgloss.Color("42"))
	case toolRunning:
		style = t.StyleDim.Copy().Foreground(lipgloss.Color(ColorTextLabel))
	default:
		style = t.StyleDim
	}

	lines = append(lines, style.Render(line))

	// ── Row 2: progress bar ──
	barW := cw - 4 // indent
	if barW > 60 {
		barW = 60
	}
	if barW < 12 {
		barW = 12
	}
	lines = append(lines, renderToolProgress(tc, barW, m.spinnerFrame))

	// ── Optional: diff (only for write/patch, when done) ──
	if tc.Status == toolDone && len(tc.DiffLines) > 0 {
		diffLines := tc.DiffLines
		if !diffOpen && len(diffLines) > 5 {
			diffLines = diffLines[:5]
		}
		for _, dl := range diffLines {
			lines = append(lines, "  │ "+dl)
		}
		if !diffOpen && len(tc.DiffLines) > 5 {
			remaining := len(tc.DiffLines) - 5
			lines = append(lines, fmt.Sprintf("  │ %s +%d lines · Enter expand", t.StyleDim.Render("▸"), remaining))
		}
	}

	return lines
}

// renderToolProgress draws the animated progress bar for a tool call.
func renderToolProgress(tc *toolCall, width int, frame int) string {
	barColor := lipgloss.Color(ColorTextDim) // dim gray for queued

	switch tc.Status {
	case toolDone:
		// Solid green bar
		return renderSolidBar(width, lipgloss.Color("42"))
	case toolRunning:
		// Animated gradient bar using mode color
		return renderOscillatingBar(width, frame, lipgloss.Color(ColorTextLabel))
	default:
		// Dim empty bar
		return renderSolidBar(width, barColor)
	}
}

// renderSolidBar returns a single-color bar of given width.
func renderSolidBar(width int, color lipgloss.Color) string {
	r, g, b := hexToRGB(string(color))
	var sb strings.Builder
	sb.WriteString("  ")
	for col := 0; col < width; col++ {
		sb.WriteString(fmt.Sprintf("\x1b[48;2;%d;%d;%dm \x1b[0m", uint8(r), uint8(g), uint8(b)))
	}
	return sb.String()
}

// renderOscillatingBar draws a gradient bar with oscillating dark valley.
// Pattern: full color → dark valley → full color, valley oscillates via sin().
func renderOscillatingBar(width int, frame int, color lipgloss.Color) string {
	r, g, b := hexToRGB(string(color))
	totalFrames := width * 3
	phase := float64(frame%totalFrames) / float64(totalFrames)
	pos := (math.Sin(phase*2.0*math.Pi) + 1.0) / 2.0 // 0..1
	center := pos * float64(width-1)

	var sb strings.Builder
	sb.WriteString("  ")
	for col := 0; col < width; col++ {
		dist := math.Abs(float64(col)-center) / (float64(width) * 0.5)
		if dist > 1.0 {
			dist = 1.0
		}
		rr := uint8(float64(r) * (1.0 - dist))
		gg := uint8(float64(g) * (1.0 - dist))
		bb := uint8(float64(b) * (1.0 - dist))
		if rr == 0 && gg == 0 && bb == 0 {
			sb.WriteByte(' ')
		} else {
			sb.WriteString(fmt.Sprintf("\x1b[48;2;%d;%d;%dm \x1b[0m", rr, gg, bb))
		}
	}
	return sb.String()
}

// ── Helpers ──

// toolParamsFromArgs extracts the most relevant parameter for display.
func toolParamsFromArgs(tool string, args map[string]any) string {
	switch tool {
	case "read_file", "write_file", "patch":
		if path, ok := args["path"].(string); ok {
			return path
		}
		if filePath, ok := args["file_path"].(string); ok {
			return filePath
		}
	case "search_files":
		if pattern, ok := args["pattern"].(string); ok {
			return pattern
		}
	case "terminal":
		if cmd, ok := args["command"].(string); ok {
			if len(cmd) > 40 {
				cmd = cmd[:40] + "…"
			}
			return cmd
		}
	case "web_search":
		if query, ok := args["query"].(string); ok {
			return query
		}
	case "delegate_task":
		if goal, ok := args["goal"].(string); ok {
			if len(goal) > 40 {
				goal = goal[:40] + "…"
			}
			return goal
		}
	case "memory":
		if content, ok := args["content"].(string); ok {
			if len(content) > 40 {
				content = content[:40] + "…"
			}
			return content
		}
	case "execute_code":
		return "python script"
	case "session_search":
		if query, ok := args["query"].(string); ok {
			return query
		}
	}
	return ""
}

var toolIcons = map[string]string{
	"read_file":      "📖",
	"write_file":     "📝",
	"patch":          "✏️",
	"search_files":   "🔍",
	"terminal":       "🖥️",
	"web_search":     "🌐",
	"memory":         "🧠",
	"session_search": "🔎",
	"vision_analyze": "👁️",
	"delegate_task":  "📋",
	"execute_code":   "⚡",
	"clarify":        "💬",
}

func toolIcon(name string) string {
	if icon, ok := toolIcons[name]; ok {
		return icon
	}
	return "🔧"
}

func toolLabel(name string) string {
	// Friendly name: "read_file" → "read_file"
	return name
}

func toolStatusStr(tc *toolCall) string {
	switch tc.Status {
	case toolRunning:
		return "⠋"
	case toolDone:
		return "✓"
	default:
		return "⏳"
	}
}
