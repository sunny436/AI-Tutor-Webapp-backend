# shellcheck shell=bash
# The lines every deploy, rollback and status ends with. Sourced by deploy.sh and status.sh.
#   print_summary <GitHub main> <the host's "@@STATUS ..." line>   (sets SUMMARY_MATCH=1 or 0)
print_summary() {
  local main=$1 line=" $2" checkout backend frontend bcur fcur reasons=()
  field() { sed -n "s/.* $1=\([^ ]*\).*/\1/p" <<<"$line"; }
  checkout=$(field checkout) backend=$(field backend) frontend=$(field frontend)
  bcur=$(field backend_current) fcur=$(field frontend_current)
  same() { [ "$1" = yes ] && [ -n "$2" ] && [ "$2" != "$checkout" ] && printf '  (same %s code as the checkout)' "$3"; }
  printf 'GitHub main SHA:          %s\n' "${main:-unknown}"
  printf 'Production checkout SHA:  %s\n' "${checkout:-unknown}"
  printf 'Backend running SHA:      %s%s\n' "${backend:-unknown}" "$(same "$bcur" "$backend" backend)"
  printf 'Frontend running SHA:     %s%s\n' "${frontend:-unknown}" "$(same "$fcur" "$frontend" frontend)"
  [ -n "$checkout" ] && [ "$checkout" = "$main" ] || reasons+=("the production checkout is not GitHub main")
  [ "$bcur" = yes ] || reasons+=("the backend does not run the checkout's backend code")
  [ "$fcur" = yes ] || reasons+=("the frontend does not run the checkout's frontend code")
  if [ ${#reasons[@]} = 0 ]; then
    SUMMARY_MATCH=1
    echo "Status: MATCH"
  else
    SUMMARY_MATCH=0
    local joined
    joined=$(printf '%s; ' "${reasons[@]}")
    echo "Status: MISMATCH (${joined%; })"
  fi
}
