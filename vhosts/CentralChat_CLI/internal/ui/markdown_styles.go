package ui

// Central markdown ANSI styles for Glamour (aligned with theme.go palette).
// Colours use xterm-256 IDs unless hex in chroma blocks.

const centralMarkdownStyleDark = `{
  "document": {
    "block_prefix": "",
    "block_suffix": "\n",
    "color": "252",
    "margin": 0
  },
  "block_quote": {
    "indent": 1,
    "indent_token": "▌ ",
    "color": "245",
    "italic": true
  },
  "paragraph": {},
  "list": {
    "level_indent": 2
  },
  "heading": {
    "block_suffix": "\n",
    "color": "39",
    "bold": true
  },
  "h1": {
    "prefix": "",
    "suffix": "",
    "color": "252",
    "bold": true
  },
  "h2": {
    "prefix": "## ",
    "color": "39",
    "bold": true
  },
  "h3": {
    "prefix": "### ",
    "color": "245",
    "bold": true
  },
  "h4": {
    "prefix": "#### ",
    "color": "245"
  },
  "h5": {
    "prefix": "##### ",
    "color": "245"
  },
  "h6": {
    "prefix": "###### ",
    "color": "245",
    "bold": false
  },
  "text": {},
  "strikethrough": {
    "crossed_out": true
  },
  "emph": {
    "italic": true,
    "color": "252"
  },
  "strong": {
    "bold": true,
    "color": "255"
  },
  "hr": {
    "color": "238",
    "format": "\n────────────────\n"
  },
  "item": {
    "block_prefix": "• "
  },
  "enumeration": {
    "block_prefix": ". "
  },
  "task": {
    "ticked": "[✓] ",
    "unticked": "[ ] "
  },
  "link": {
    "color": "39",
    "underline": true
  },
  "link_text": {
    "color": "39",
    "underline": true
  },
  "image": {
    "color": "245",
    "underline": true
  },
  "image_text": {
    "color": "245",
    "format": "🖼 {{.text}}"
  },
  "code": {
    "prefix": " ",
    "suffix": " ",
    "color": "229",
    "background_color": "236"
  },
  "code_block": {
    "color": "252",
    "margin": 0,
    "chroma": {
      "text": { "color": "#DCDCDC" },
      "comment": { "color": "#6A6A6A" },
      "keyword": { "color": "#5FAFFF" },
      "keyword_type": { "color": "#8A8AE6" },
      "literal_string": { "color": "#CE9F7F" },
      "name_function": { "color": "#5FD7AF" },
      "literal_number": { "color": "#6EEFC0" },
      "operator": { "color": "#EF8080" },
      "punctuation": { "color": "#C4C4A8" }
    }
  }
}`

const centralMarkdownStyleLight = `{
  "document": {
    "block_prefix": "",
    "block_suffix": "\n",
    "color": "236",
    "margin": 0
  },
  "block_quote": {
    "indent": 1,
    "indent_token": "▌ ",
    "color": "240",
    "italic": true
  },
  "paragraph": {},
  "list": {
    "level_indent": 2
  },
  "heading": {
    "block_suffix": "\n",
    "color": "25",
    "bold": true
  },
  "h1": {
    "color": "236",
    "bold": true
  },
  "h2": {
    "prefix": "## ",
    "color": "25",
    "bold": true
  },
  "h3": {
    "prefix": "### ",
    "color": "240",
    "bold": true
  },
  "h4": { "prefix": "#### ", "color": "240" },
  "h5": { "prefix": "##### ", "color": "240" },
  "h6": { "prefix": "###### ", "color": "240" },
  "text": {},
  "strikethrough": { "crossed_out": true },
  "emph": { "italic": true },
  "strong": { "bold": true },
  "hr": {
    "color": "250",
    "format": "\n────────────────\n"
  },
  "item": { "block_prefix": "• " },
  "enumeration": { "block_prefix": ". " },
  "task": { "ticked": "[✓] ", "unticked": "[ ] " },
  "link": { "color": "25", "underline": true },
  "link_text": { "color": "25", "underline": true },
  "image": { "color": "240", "underline": true },
  "image_text": { "color": "240", "format": "🖼 {{.text}}" },
  "code": {
    "prefix": " ",
    "suffix": " ",
    "color": "236",
    "background_color": "252"
  },
  "code_block": {
    "color": "236",
    "margin": 0,
    "chroma": {
      "text": { "color": "#333333" },
      "comment": { "color": "#888888" },
      "keyword": { "color": "#0066CC" },
      "literal_string": { "color": "#997755" },
      "name_function": { "color": "#228855" }
    }
  }
}`

func centralMarkdownStyleJSON(themeName string) []byte {
	if themeName == "light" {
		return []byte(centralMarkdownStyleLight)
	}
	return []byte(centralMarkdownStyleDark)
}
