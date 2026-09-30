#!/usr/bin/env bash
# render_docs.sh — render every published Markdown doc to doc/*.pdf.
#
# The PDFs are build artifacts, not source. They are gitignored and attached
# to each GitHub Release by .github/workflows/release.yml, which runs this
# script. Run it locally only when you want a PDF in hand.
#
# Do not call this script from the pre-commit hook, and do not commit the PDFs.
# A render adds about 300 KB of binary that git cannot delta to each commit
# that changes a document, and the hook would make pandoc and WeasyPrint a
# requirement for every commit.
#
# Requires pandoc and weasyprint on PATH (see CONTRIBUTING.md).

set -euo pipefail

cd "$(dirname "$0")/.."

DOCS=(README.md CONTRIBUTING.md doc/PROGRESS.md doc/CHANGELOG.md)

for doc in "${DOCS[@]}"; do
    ./scripts/render_md.sh "$doc"
done
