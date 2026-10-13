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

echo "Deleting all GitHub releases (including tagless drafts)..."
gh api "repos/$REPO/releases" --paginate --jq '.[].id' | while read -r id; do
  echo "  - release id $id"
  gh api -X DELETE "repos/$REPO/releases/$id"
done

echo "Done. Optional: gh repo delete $REPO --yes && recreate empty repo, then push main."
