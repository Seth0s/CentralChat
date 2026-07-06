package ui

// chatViewportLine is one row in the message viewport with paint hints.
type chatViewportLine struct {
	text        string
	assistant   bool // true → paintAssistantRow (markdown); false → standard canvas row
	turnUserIdx int  // index in m.messages of the user message that started this turn (-1 = sticky/unknown)
}

func appendViewportBlock(dst []chatViewportLine, block string, assistant bool) []chatViewportLine {
	return appendViewportBlockWithTurn(dst, block, assistant, -1)
}

func appendViewportBlockWithTurn(dst []chatViewportLine, block string, assistant bool, turnUserIdx int) []chatViewportLine {
	lines := splitRenderedLines(block)
	if len(lines) == 0 {
		return dst
	}
	for _, ln := range lines {
		dst = append(dst, chatViewportLine{text: ln, assistant: assistant, turnUserIdx: turnUserIdx})
	}
	return append(dst, chatViewportLine{turnUserIdx: turnUserIdx})
}
