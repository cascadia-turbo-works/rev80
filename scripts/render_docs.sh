#!/usr/bin/env bash
# render_docs.sh — render every published Markdown doc to doc/*.pdf.
#
# The PDFs are build artifacts, not source. They are gitignored and attached
# to each GitHub Release by .github/workflows/release.yml, which runs this
# script. Run it locally only when you want a PDF in hand.
#
# They used to be re-rendered by the pre-commit hook and committed. That put
# ~300 KB of binary that cannot delta into every doc-touching commit -- 10.3 MB
# across 34 commits, against 13.4 MB for every version of every source file --
# and made pandoc + WeasyPrint a requirement for anyone making a commit.
#
# Requires pandoc and weasyprint on PATH (see CONTRIBUTING.md).

set -euo pipefail

cd "$(dirname "$0")/.."

DOCS=(README.md CONTRIBUTING.md doc/PROGRESS.md doc/CHANGELOG.md)

for doc in "${DOCS[@]}"; do
    ./scripts/render_md.sh "$doc"
done
