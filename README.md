# `ccx`

`ccx` is a shell-only session override for Claude Code.

It does not modify `cc-switch` or your global Claude settings. It only adds a
per-terminal override by wrapping `claude` with `--settings <profile.json>`.

## Files

- `ccx.sh`: source this into your shell.
- `sync_ccswitch_profiles.sh`: pull profiles from your `cc-switch` data store.
- `profiles/*.json`: one Claude settings override per profile.

## Install

Add this to `~/.zshrc`:

```sh
export CCX_ROOT="/path/to/ccx"
source "$CCX_ROOT/ccx.sh"
```

Or load it in the current shell only:

```sh
export CCX_ROOT="/Users/cliffkai/Code/ccx"
source "$CCX_ROOT/ccx.sh"
```

## Usage

- `ccx_list`
  List profile aliases from `profiles/*.json`. When imported from `cc-switch`,
  it shows `alias -> original name`. The alias is the command you can type.

- `ccx_sync`
  Import all Claude providers from your `cc-switch` directory into
  `profiles/*.json`, then refresh shell shortcuts.

- `openrouter`
- `googleaistudio`
  Switch the current terminal window to that profile.

For names imported from `cc-switch` that are not shell-safe, use the alias shown
on the left side of `ccx_list`, for example:

```sh
openrouter            # use the alias
ccx_use "Google AI Studio"  # names with spaces need quotes
```

- `claude`
  When a profile is selected, `ccx` automatically runs:

```sh
claude --settings /path/to/profile.json
```

  When no profile is selected, it behaves exactly like the original `claude`.

- `ccx_current`
  Show the current profile, or `cc-switch default` when no override is active.

- `ccx_reset`
  Clear the session override and go back to the `cc-switch` default behavior.

- `ccx_run <profile> [claude args...]`
  Run one Claude command with a profile without changing the current shell.

- `ccx_reload`
  Re-scan `profiles/*.json` and register shortcut commands for newly added
  profiles in the current shell.

## How It Works

`claude --settings` loads an extra settings JSON file for that run. Because the
override lives only in the current shell function, different terminal windows
can use different profiles at the same time.

## Editing Profiles

If you want to sync directly from `cc-switch`, the default source directory is:

```sh
~/Library/Mobile Documents/com~apple~CloudDocs/密钥/cc-switch
```

You can override it before running `ccx_sync`:

```sh
export CCX_CCSWITCH_DIR="/another/path/to/cc-switch"
```

Imported profile files are normal Claude settings JSON snippets, so they can
include fields such as:

- `env`
- `model`
- `effortLevel`
- `enabledPlugins`
- `permissions`

If a setting is omitted from a profile, Claude continues to use your existing
defaults from `cc-switch` and other normal setting sources.
