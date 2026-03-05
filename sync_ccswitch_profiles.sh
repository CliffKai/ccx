#!/usr/bin/env sh

set -eu

if [ -z "${CCX_ROOT:-}" ]; then
  CCX_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd)"
fi

CCX_PROFILE_DIR="${CCX_PROFILE_DIR:-$CCX_ROOT/profiles}"
CCX_CCSWITCH_DIR="${CCX_CCSWITCH_DIR:-/Users/cliffkai/Library/Mobile Documents/com~apple~CloudDocs/密钥/cc-switch}"
CCX_DB_PATH="${CCX_DB_PATH:-$CCX_CCSWITCH_DIR/cc-switch.db}"
CCX_SETTINGS_JSON="${CCX_SETTINGS_JSON:-$CCX_CCSWITCH_DIR/settings.json}"
CCX_GENERATED_LIST="$CCX_PROFILE_DIR/.ccx-generated.list"
CCX_MANIFEST="$CCX_PROFILE_DIR/.ccx-manifest.tsv"

mkdir -p "$CCX_PROFILE_DIR"

if [ ! -f "$CCX_DB_PATH" ]; then
  echo "ccx: cc-switch database not found: $CCX_DB_PATH" >&2
  exit 1
fi

if [ ! -f "$CCX_SETTINGS_JSON" ]; then
  echo "ccx: cc-switch settings.json not found: $CCX_SETTINGS_JSON" >&2
  exit 1
fi

ccx_cleanup_generated() {
  local file

  if [ ! -f "$CCX_GENERATED_LIST" ]; then
    return 0
  fi

  while IFS= read -r file; do
    [ -n "$file" ] || continue
    rm -f "$CCX_PROFILE_DIR/$file"
  done < "$CCX_GENERATED_LIST"
}

ccx_slugify() {
  local raw
  local fallback
  local slug

  raw="$1"
  fallback="$2"

  case "$raw" in
    "咸鱼学院路开店店")
      echo "xianyu_shop"
      return 0
      ;;
    "咸鱼秃头男孩")
      echo "xianyu_bald_boy"
      return 0
      ;;
    "蓝星")
      echo "lanxing"
      return 0
      ;;
  esac

  slug="$(printf '%s' "$raw" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/_/g; s/^_+//; s/_+$//; s/_+/_/g')"

  if [ -z "$slug" ]; then
    slug="provider_${fallback%%-*}"
  fi

  echo "$slug"
}

ccx_write_profile() {
  local base_json
  local overlay_json
  local profile
  local label
  local source
  local target

  base_json="$1"
  overlay_json="$2"
  profile="$3"
  label="$4"
  source="$5"
  target="$CCX_PROFILE_DIR/$profile.json"

  printf '%s\n%s\n' "$base_json" "$overlay_json" | jq -s '.[0] * .[1]' > "$target"
  printf '%s\n' "$profile.json" >> "$TMP_GENERATED"
  printf '%s\t%s\t%s\n' "$profile" "$label" "$source" >> "$TMP_MANIFEST"
}

TMP_GENERATED="$(mktemp "${TMPDIR:-/tmp}/ccx-generated.XXXXXX")"
TMP_MANIFEST="$(mktemp "${TMPDIR:-/tmp}/ccx-manifest.XXXXXX")"

cleanup() {
  rm -f "$TMP_GENERATED" "$TMP_MANIFEST"
}

trap cleanup EXIT INT TERM

ccx_cleanup_generated

COMMON_JSON="$(sqlite3 "$CCX_DB_PATH" "select value from settings where key = 'common_config_claude';")"

if [ -z "$COMMON_JSON" ]; then
  COMMON_JSON='{}'
fi

SETTINGS_JSON_CONTENT="$(cat "$CCX_SETTINGS_JSON")"
ccx_write_profile "$COMMON_JSON" "$SETTINGS_JSON_CONTENT" "ccswitch_current" "cc-switch settings.json" "settings.json"

PROVIDERS_JSON="$(sqlite3 -json "$CCX_DB_PATH" "select id, name, is_current, settings_config from providers where app_type = 'claude' order by sort_index, name;")"

printf '%s' "$PROVIDERS_JSON" | jq -rc '.[] | @base64' | while IFS= read -r row; do
  [ -n "$row" ] || continue

  ROW_JSON="$(printf '%s' "$row" | base64 -d)"
  PROVIDER_ID="$(printf '%s' "$ROW_JSON" | jq -r '.id')"
  PROVIDER_NAME="$(printf '%s' "$ROW_JSON" | jq -r '.name')"
  PROVIDER_IS_CURRENT="$(printf '%s' "$ROW_JSON" | jq -r '.is_current')"
  OVERLAY_JSON="$(printf '%s' "$ROW_JSON" | jq -c '.settings_config | fromjson')"
  PROFILE_NAME="$(ccx_slugify "$PROVIDER_NAME" "$PROVIDER_ID")"

  ccx_write_profile "$COMMON_JSON" "$OVERLAY_JSON" "$PROFILE_NAME" "$PROVIDER_NAME" "providers"

  if [ "$PROVIDER_IS_CURRENT" = "1" ]; then
    ccx_write_profile "$COMMON_JSON" "$OVERLAY_JSON" "ccswitch_active" "$PROVIDER_NAME" "providers.current"
  fi
done

mv "$TMP_GENERATED" "$CCX_GENERATED_LIST"
mv "$TMP_MANIFEST" "$CCX_MANIFEST"

echo "ccx: synced profiles into $CCX_PROFILE_DIR"
