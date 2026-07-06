// Standalone spinner visual test — renders the rotating gradient circle
// in a terminal loop so you can iterate on size, color, and animation.
//
// Usage: go run ./cmd/spinnerdemo/ [--width=16] [--height=7] [--color=39] [--fps=8]
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
	width := flag.Int("width", 16, "spinner width in terminal columns")
	height := flag.Int("height", 9, "spinner height in terminal rows")
	color := flag.String("color", "39", "256-color name (39=blue, 214=orange, 1=red, 135=purple, 42=green)")
	fps := flag.Int("fps", 10, "frames per second")
	flag.Parse()

	fmt.Print("\033[?25l")       // hide cursor
	defer fmt.Print("\033[?25h") // show cursor on exit
	fmt.Print("\033[2J")         // clear screen

	// Handle Ctrl+C
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, os.Interrupt)

	frame := 0
	ticker := time.NewTicker(time.Second / time.Duration(*fps))
	defer ticker.Stop()

	for {
		select {
		case <-sig:
			fmt.Print("\033[2J\033[H")
			return
		case <-ticker.C:
			render(*width, *height, frame, *color)
			frame++
		}
	}
}

func render(w, h, frame int, color string) {
	r, g, b := hexToRGB(color)
	cx := float64(w)/2.0 - 0.5
	cy := float64(h)/2.0 - 0.5
	// Outer circle radius — uses aspect-corrected effective height
	effH := float64(h) * 2.0
	outerR := math.Min(float64(w), effH)/2.0 - 0.8
	if outerR < 1.2 {
		outerR = 1.2
	}
	// Black inner circle: fixed radius 3
	innerR := 3.0
	if innerR >= outerR-0.3 {
		innerR = outerR * 0.7 // fallback if spinner too small
	}
	ringW := outerR - innerR
	// 8 frames per full rotation
	rot := float64(frame%8) / 8.0

	var sb strings.Builder
	sb.WriteString("\033[H") // home cursor

	// Draw a border box
	bar := strings.Repeat("─", w+4)
	sb.WriteString(fmt.Sprintf("\033[38;5;240m┌%s┐\n", bar))
	for row := 0; row < h; row++ {
		sb.WriteString("\033[38;5;240m│\033[0m ")
		for col := 0; col < w; col++ {
			dx := float64(col) - cx
			dy := (float64(row) - cy) * 2.0     // aspect ratio
			dist := math.Sqrt(dx*dx + dy*dy)     // Euclidean = circle

			if dist > innerR && dist <= outerR {
				angle := math.Atan2(dy, dx)
				angularNorm := (angle + math.Pi) / (2.0 * math.Pi)
				angularNorm = math.Mod(angularNorm+rot, 1.0)
				radialAlpha := (dist - innerR) / ringW
				if radialAlpha > 1.0 {
					radialAlpha = 1.0
				}
				brightness := radialAlpha * (1.0 - angularNorm)
				rr := uint8(float64(r) * brightness)
				gg := uint8(float64(g) * brightness)
				bb := uint8(float64(b) * brightness)
				sb.WriteString(fmt.Sprintf("\033[48;2;%d;%d;%dm \033[0m", rr, gg, bb))
			} else {
				sb.WriteString(" ")
			}
		}
		sb.WriteString(fmt.Sprintf(" \033[38;5;240m│\033[0m\n"))
	}
	sb.WriteString(fmt.Sprintf("\033[38;5;240m└%s┘\033[0m\n", bar))

	sb.WriteString(fmt.Sprintf("\n  circle | color=%s  size=%dx%d  frame=%d  (Ctrl+C to quit)\n", color, w, h, frame))
	sb.WriteString("  mode colors: 39=blue  214=orange  1=red  135=purple  42=green\n")

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
