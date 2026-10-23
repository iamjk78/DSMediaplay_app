#!/usr/bin/env bash
# Takes the pictures of the documentation (macOS). Run from the repository root with the application's Python:
#   tools/capture_documentation_images.sh
set -eu
mkdir -p documentation/web_assets/images
for language in cz en; do
  python tools/capture_documentation_images.py "$language" | while read -r _ name box; do
    screencapture -x -R"$box" "documentation/web_assets/images/$name" </dev/null
    echo "took $name"
  done
done
