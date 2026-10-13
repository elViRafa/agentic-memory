#!/usr/bin/env bash
# One-shot GitHub cleanup: delete non-main branches and all releases.
# Run from repo root with gh authenticated. Does not delete the repository.
set -euo pipefail
REPO="${GITHUB_REPO:-elViRafa/agentic-memory}"

echo "Repository: $REPO"

echo "Deleting remote branches except main..."
gh api "repos/$REPO/branches" --jq '.[].name' | while read -r branch; do
  if [[ "$branch" == "main" ]]; then
    continue
  fi
  echo "  - $branch"
  gh api -X DELETE "repos/$REPO/git/refs/heads/$branch"
done

echo "Deleting all GitHub releases..."
gh release list -R "$REPO" --limit 500 | awk '{print $1}' | while read -r tag; do
  [[ -z "$tag" ]] && continue
  echo "  - $tag"
  gh release delete "$tag" -R "$REPO" --yes --cleanup-tag 2>/dev/null || \
    gh release delete "$tag" -R "$REPO" --yes
done

echo "Done. Optional: gh repo delete $REPO --yes && recreate empty repo, then push main."
