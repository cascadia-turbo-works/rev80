#!/usr/bin/env bash
# render_progress.sh — Convert PROGRESS.md (or any .md) to PDF
# via pandoc → styled HTML → weasyprint
#
# Usage:
#   ./render_progress.sh                       # outputs doc/PROGRESS.pdf
#   ./render_progress.sh path/to/file.md       # any markdown file
#   ./render_progress.sh file.md output.pdf    # explicit output path

set -euo pipefail

INPUT="${1:-PROGRESS.md}"
OUTPUT="${2:-doc/PROGRESS.pdf}"

CSS_FILE="$(mktemp /tmp/vibechecker_XXXXXX.css)"
HTML_FILE="$(mktemp /tmp/vibechecker_XXXXXX.html)"
trap 'rm -f "$CSS_FILE" "$HTML_FILE"' EXIT

command -v pandoc    >/dev/null || { echo "ERROR: pandoc not found";    exit 1; }
command -v weasyprint >/dev/null || { echo "ERROR: weasyprint not found"; exit 1; }
[[ -f "$INPUT" ]] || { echo "ERROR: $INPUT not found"; exit 1; }
mkdir -p "$(dirname "$OUTPUT")"

cat > "$CSS_FILE" << 'EOF'
@page {
  margin: 20mm 18mm;
  size: A4;
  @top-right   { content: "vibechecker"; font-size: 8pt; color: #999; }
  @bottom-center { content: counter(page) " / " counter(pages); font-size: 8pt; color: #999; }
}

body {
  font-family: "Helvetica Neue", Arial, sans-serif;
  font-size: 9.5pt;
  line-height: 1.5;
  color: #1a1a1a;
}

h1 { font-size: 18pt; border-bottom: 2px solid #3a3a5c; padding-bottom: 4px; margin-top: 0; }
h2 { font-size: 13pt; border-bottom: 1px solid #ccc; padding-bottom: 3px; margin-top: 1.4em; color: #2c2c4a; }
h3 { font-size: 10.5pt; margin-top: 1.2em; color: #3a3a5c; }
h4 { font-size: 9.5pt; margin-top: 1em; font-style: italic; color: #555; }

p { margin: 0.4em 0 0.8em 0; }
a { color: #3a3a5c; }

code {
  font-family: "Courier New", Courier, monospace;
  font-size: 8.5pt;
  background: #f4f4f8;
  padding: 1px 4px;
  border-radius: 3px;
}

pre {
  background: #f4f4f8;
  padding: 8px 10px;
  border-left: 3px solid #3a3a5c;
  font-size: 8pt;
  line-height: 1.4;
  white-space: pre-wrap;
}

pre code { background: none; padding: 0; }

table {
  border-collapse: collapse;
  width: 100%;
  font-size: 8.5pt;
  margin: 0.6em 0 1em 0;
}

thead tr { background: #3a3a5c; color: #fff; }
thead th { padding: 5px 8px; text-align: left; font-weight: 600; }

tbody tr:nth-child(even) { background: #f4f4f8; }
tbody td { padding: 4px 8px; border-bottom: 1px solid #ddd; vertical-align: top; }

tr { page-break-inside: avoid; }

hr { border: none; border-top: 1px solid #ddd; margin: 1.2em 0; }

blockquote {
  margin: 0.6em 0 0.6em 1em;
  padding: 0.4em 0.8em;
  border-left: 3px solid #aaa;
  color: #555;
  font-style: italic;
}
EOF

echo "Rendering: $INPUT → $OUTPUT"

pandoc "$INPUT" \
  --standalone \
  --css="$CSS_FILE" \
  --embed-resources \
  --highlight-style=tango \
  -o "$HTML_FILE"

weasyprint "$HTML_FILE" "$OUTPUT" 2>&1 | grep -v "^WARNING" || true

echo "Done: $OUTPUT"
