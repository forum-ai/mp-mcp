#!/usr/bin/env bash
# Post one comment on an issue or PR, only if it is short enough: at most
# max_comment_words (in autotriage.conf, next to this script) outside its
# <details> section. This is the triage bot's only way to comment.
#
#   .github/autotriage_comment.sh <issue or PR number> "<markdown body>"
set -euo pipefail

here="$(dirname "$0")"
source "$here/autotriage_lib.sh"

usage="usage: autotriage_comment.sh <issue or PR number> <body>"
number="${1:?$usage}"
body="${2:?$usage}"
[[ "$number" =~ ^[0-9]+$ ]] || fail "'$number' is not an issue or PR number"
who="#$number"

load_conf "$here/autotriage.conf"
[[ "$max_comment_words" =~ ^[1-9][0-9]*$ ]] || fail "bad max_comment_words '$max_comment_words'"

# Count the words outside <details> sections. Only a closed section is left
# out, so a stray <details> can't hide the rest of the comment.
# <details open> shows expanded, so its words count too.
# (authored by claude, not human ardunn)
words=$(perl -0pe 's{<details\b(?![^>]*\bopen\b).*?</details>}{}gs' <<<"$body" | wc -w | tr -d ' ')
[[ "$words" -le "$max_comment_words" ]] ||
  fail "$words words outside <details> (limit $max_comment_words). Shorten it, or move detail into one <details> section, and post again."

gh issue comment "$number" --body "$body"
