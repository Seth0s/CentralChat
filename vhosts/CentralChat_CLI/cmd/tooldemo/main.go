// Tool progress bar visual test — animated oscillating gradient
// Pattern: full color → fades to black at center → full color at edge
// The black "valley" oscillates left ↔ right continuously.
//
// Usage: go run ./cmd/tooldemo/ [--width=40] [--color=39] [--fps=15]
package main

import (
	"flag"
	"fmt"
	"math"
	"os"
	"os/signal"
	"strings"
	"time"
)

func main() {
	width := flag.Int("width", 12, "bar width in terminal columns")
	color := flag.String("color", "39", "256-color (39=blue, 214=orange, 1=red, 135=purple, 42=green)")
	fps := flag.Int("fps", 20, "frames per second")
	flag.Parse()

	fmt.Print("\033[?25l")
	defer fmt.Print("\033[?25h")
	fmt.Print("\033[2J")

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, os.Interrupt)

	frame := 0
	totalFrames := *width * 3 // one full oscillation cycle
	ticker := time.NewTicker(time.Second / time.Duration(*fps))
	defer ticker.Stop()

	for {
		select {
		case <-sig:
			fmt.Print("\033[2J\033[H")
			return
		case <-ticker.C:
			render(*width, frame, totalFrames, *color)
			frame = (frame + 1) % totalFrames
		}
	}
}

func render(width, frame, totalFrames int, color string) {
	r, g, b := hexToRGB(color)

	// Oscillating position: sin wave 0→1→0
	phase := float64(frame) / float64(totalFrames)
	pos := (math.Sin(phase*2.0*math.Pi) + 1.0) / 2.0 // 0..1
	center := pos * float64(width-1)

	var sb strings.Builder
	sb.WriteString("\033[H")

	// Title
	sb.WriteString(fmt.Sprintf("\033[38;5;240mTool progress bar — color=%s  width=%d  frame=%d/%d\033[0m\n\n", color, width, frame, totalFrames))

	// Border
	bar := strings.Repeat("─", width+2)
	sb.WriteString(fmt.Sprintf("\033[38;5;240m┌%s┐\033[0m\n", bar))

	// The progress bar
	sb.WriteString("\033[38;5;240m│\033[0m")
	for col := 0; col < width; col++ {
		// Distance from oscillating center, normalized to [0, 1]
		// divisor=0.5 spreads gradient across all columns with only 1-2 truly black
		dist := math.Abs(float64(col)-center) / (float64(width) * 0.5)
		if dist > 1.0 {
			dist = 1.0
		}
		// Brightest at edges (dist=1), darkest at center (dist=0)
		// Invert: brightest at center, darkest at edges → use (1-dist)
		// But user wants: dark at center, bright at edges → use dist
		rr := uint8(float64(r) * dist)
		gg := uint8(float64(g) * dist)
		bb := uint8(float64(b) * dist)
		if rr == 0 && gg == 0 && bb == 0 {
			sb.WriteString(" ")
		} else {
			sb.WriteString(fmt.Sprintf("\033[48;2;%d;%d;%dm \033[0m", rr, gg, bb))
		}
	}
	sb.WriteString(fmt.Sprintf("\033[38;5;240m│\033[0m\n"))

	sb.WriteString(fmt.Sprintf("\033[38;5;240m└%s┘\033[0m\n", bar))

	// V-shape indicator
	sb.WriteString(fmt.Sprintf("\n  pattern: \033[48;2;%d;%d;%dm  \033[0m → black → \033[48;2;%d;%d;%dm  \033[0m  (valley at col %.0f)\n",
		r, g, b, r, g, b, center))
	sb.WriteString("  Ctrl+C to quit\n")

	fmt.Print(sb.String())
}

func hexToRGB(hex string) (r, g, b int) {
	switch hex {
	case "214", "208":
		return 255, 170, 0
	case "1", "196":
		return 255, 51, 51
	case "135":
		return 175, 95, 255
	case "42", "46":
		return 0, 204, 102
	case "39":
		return 51, 153, 255
	default:
		return 128, 128, 128
	}
}
