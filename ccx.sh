#!/usr/bin/env sh

if [ -z "${CCX_ROOT:-}" ]; then
  _ccx_script=""

  if [ -n "${BASH_SOURCE[0]:-}" ]; then
    _ccx_script="${BASH_SOURCE[0]}"
  elif [ -n "${ZSH_VERSION:-}" ]; then
    eval '_ccx_script=${(%):-%x}'
  fi

  if [ -n "$_ccx_script" ]; then
    CCX_ROOT="$(CDPATH= cd -- "$(dirname -- "$_ccx_script")" 2>/dev/null && pwd)"
  fi

  unset _ccx_script
fi

if [ -z "${CCX_ROOT:-}" ]; then
  echo "ccx: unable to determine CCX_ROOT; export CCX_ROOT before sourcing ccx.sh" >&2
  return 1 2>/dev/null || exit 1
fi

CCX_PROFILE_DIR="${CCX_PROFILE_DIR:-$CCX_ROOT/profiles}"
CCX_SYNC_SCRIPT="${CCX_SYNC_SCRIPT:-$CCX_ROOT/sync_ccswitch_profiles.sh}"

ccx_profile_file() {
  printf '%s/%s.json\n' "$CCX_PROFILE_DIR" "$1"
}

ccx_resolve_profile() {
  local input
  local profile
  local label
  local source

  input="$1"

  if [ -f "$CCX_PROFILE_DIR/.ccx-manifest.tsv" ]; then
    while IFS="$(printf '\t')" read -r profile label source; do
      [ -n "$profile" ] || continue

      if [ "$input" = "$profile" ]; then
        printf '%s\n' "$profile"
        return 0
      fi

      if [ "$input" = "$label" ]; then
        printf '%s\n' "$profile"
        return 0
      fi
    done < "$CCX_PROFILE_DIR/.ccx-manifest.tsv"
  fi

  if [ -f "$(ccx_profile_file "$input")" ]; then
    printf '%s\n' "$input"
    return 0
  fi

  return 1
}

ccx_has_settings_arg() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --settings)
        return 0
        ;;
      --settings=*)
        return 0
        ;;
    esac
    shift
  done

  return 1
}

ccx_list() {
  [ -n "${ZSH_VERSION:-}" ] && setopt local_options NULL_GLOB
  local file
  local found
  local profile
  local label
  local source

  if [ -f "$CCX_PROFILE_DIR/.ccx-manifest.tsv" ]; then
    found=0

    while IFS="$(printf '\t')" read -r profile label source; do
      [ -n "$profile" ] || continue
      found=1

      if [ -n "$label" ] && [ "$profile" != "$label" ]; then
        printf '%s -> %s\n' "$profile" "$label"
      else
        printf '%s\n' "$profile"
      fi
    done < "$CCX_PROFILE_DIR/.ccx-manifest.tsv"

    if [ "$found" -eq 0 ]; then
      echo "No profiles found in $CCX_PROFILE_DIR" >&2
      return 1
    fi

    return 0
  fi

  found=0

  for file in "$CCX_PROFILE_DIR"/*.json; do
    [ -e "$file" ] || continue
    found=1
    file="${file##*/}"
    printf '%s\n' "${file%.json}"
  done

  if [ "$found" -eq 0 ]; then
    echo "No profiles found in $CCX_PROFILE_DIR" >&2
    return 1
  fi
}

ccx_help() {
  cat <<'EOF'
ccx — per-terminal Claude Code profile switching

Commands:
  ccx_use <profile>            Switch active profile for this terminal
  ccx_list                     List all available profiles
  ccx_current                  Show the currently active profile
  ccx_reset                    Clear profile selection (revert to default)
  ccx_run <profile> [args...]  Run claude once with a specific profile
  ccx_sync                     Sync profiles from cc-switch database
  ccx_reload                   Reload profile shortcut functions
  ccx_help                     Show this help message

Each profile in profiles/ also registers a shortcut function
(e.g. profiles/foo.json -> type "foo" to switch).
EOF
}

ccx_current() {
  if [ -n "${CCX_PROFILE:-}" ]; then
    printf '%s\n' "$CCX_PROFILE"
  else
    echo "cc-switch default"
  fi
}

ccx_use() {
  local input
  local profile
  local file

  input="$1"

  if [ -z "$input" ]; then
    echo "Usage: ccx_use <profile>" >&2
    return 1
  fi

  profile="$(ccx_resolve_profile "$input" 2>/dev/null || true)"

  if [ -z "$profile" ]; then
    profile="$input"
  fi

  file="$(ccx_profile_file "$profile")"

  if [ ! -f "$file" ]; then
    echo "ccx: profile not found: $input" >&2
    return 1
  fi

  export CCX_PROFILE="$profile"
  export CCX_SETTINGS_FILE="$file"
  printf 'ccx: current profile -> %s\n' "$profile"
}

ccx_reset() {
  unset CCX_PROFILE
  unset CCX_SETTINGS_FILE
  echo "ccx: reset to cc-switch default"
}

ccx_run() {
  local input
  local profile
  local file

  if [ "$#" -eq 0 ]; then
    echo "Usage: ccx_run <profile> [claude args...]" >&2
    return 1
  fi

  input="$1"
  shift

  profile="$(ccx_resolve_profile "$input" 2>/dev/null || true)"

  if [ -z "$profile" ]; then
    profile="$input"
  fi

  file="$(ccx_profile_file "$profile")"

  if [ ! -f "$file" ]; then
    echo "ccx: profile not found: $input" >&2
    return 1
  fi

  if ccx_has_settings_arg "$@"; then
    command claude "$@"
  else
    command claude --settings "$file" "$@"
  fi
}

ccx_define_profile_shortcuts() {
  [ -n "${ZSH_VERSION:-}" ] && setopt local_options NULL_GLOB
  local file
  local name

  if [ -n "${CCX_SHORTCUTS:-}" ]; then
    for name in $CCX_SHORTCUTS; do
      unset -f "$name" 2>/dev/null || true
    done
  fi

  CCX_SHORTCUTS=""

  for file in "$CCX_PROFILE_DIR"/*.json; do
    [ -e "$file" ] || continue
    name="${file##*/}"
    name="${name%.json}"

    case "$name" in
      claude|ccx_*)
        continue
        ;;
      ''|*[!A-Za-z0-9_]*)
        continue
        ;;
    esac

    eval "${name}() { ccx_use '${name}'; }"

    if [ -z "$CCX_SHORTCUTS" ]; then
      CCX_SHORTCUTS="$name"
    else
      CCX_SHORTCUTS="$CCX_SHORTCUTS $name"
    fi
  done
}

ccx_reload() {
  ccx_define_profile_shortcuts

  if [ -n "${CCX_PROFILE:-}" ] && [ ! -f "$(ccx_profile_file "$CCX_PROFILE")" ]; then
    unset CCX_PROFILE
    unset CCX_SETTINGS_FILE
  fi
}

ccx_sync() {
  if [ ! -f "$CCX_SYNC_SCRIPT" ]; then
    echo "ccx: sync script not found: $CCX_SYNC_SCRIPT" >&2
    return 1
  fi

  CCX_ROOT="$CCX_ROOT" \
  CCX_PROFILE_DIR="$CCX_PROFILE_DIR" \
  CCX_CCSWITCH_DIR="${CCX_CCSWITCH_DIR:-}" \
  CCX_DB_PATH="${CCX_DB_PATH:-}" \
  CCX_SETTINGS_JSON="${CCX_SETTINGS_JSON:-}" \
  sh "$CCX_SYNC_SCRIPT" "$@" || return $?
  ccx_reload
}

claude() {
  if [ -n "${CCX_SETTINGS_FILE:-}" ] && [ -f "${CCX_SETTINGS_FILE:-}" ] && ! ccx_has_settings_arg "$@"; then
    command claude --settings "$CCX_SETTINGS_FILE" "$@"
    return $?
  fi

  command claude "$@"
}

ccx_define_profile_shortcuts
