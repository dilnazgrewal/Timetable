#!/usr/bin/env bash
# Publish the current commit to a Hugging Face Space (the public demo link).
# Hugging Face refuses binary files that aren't in Git LFS, and docs/progress (report PDFs, screenshots) is in
# this repo's history. So this pushes ONE fresh commit of the current code without docs/progress. Your branch,
# your working folder and GitHub are not touched.
#
# Usage (Git Bash, from the repo folder):   bash deploy/push_to_space.sh <hf-username>/<space-name>
# When asked for a password, paste a Hugging Face access token with "write" permission.
# DRY=1 bash deploy/push_to_space.sh <...>  only builds the commit and lists what would be sent.
set -euo pipefail
SPACE="${1:?usage: bash deploy/push_to_space.sh <hf-username>/<space-name>}"

INDEX="$(mktemp)"
trap 'rm -f "$INDEX"' EXIT
GIT_INDEX_FILE="$INDEX" git read-tree HEAD
GIT_INDEX_FILE="$INDEX" git rm -r -q --cached --ignore-unmatch docs/progress
TREE="$(GIT_INDEX_FILE="$INDEX" git write-tree)"
COMMIT="$(git commit-tree "$TREE" -m "TimeWeave demo from $(git rev-parse --short HEAD)")"

echo "Commit $COMMIT: $(git ls-tree -r --name-only "$COMMIT" | wc -l) files, from $(git rev-parse --short HEAD)"
if [ "${DRY:-0}" = "1" ]; then
  git ls-tree -r --name-only "$COMMIT" | grep -iE '\.(pdf|png|jpe?g|gif|zip|xlsx|docx)$' && echo "binary files found!" || echo "no binary files: OK"
  exit 0
fi
git push --force "https://huggingface.co/spaces/$SPACE" "$COMMIT:refs/heads/main"
echo "Pushed. The Space builds in a few minutes: https://huggingface.co/spaces/$SPACE"
