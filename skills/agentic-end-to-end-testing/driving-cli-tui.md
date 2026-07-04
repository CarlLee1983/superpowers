# Driving a CLI / TUI (tmux)

Each scenario gets its own named tmux session (cleanup needs a deterministic
name). Fix the size for deterministic capture; prefer the app's plain-text/inline
mode if it has one.

## The four-command recipe

```bash
tmux new-session -d -s <name> -x 200 -y 50 "<cmd> 2>/tmp/<name>-stderr.log"
tmux send-keys -t <name> -l "literal text"   # -l = no key-name parsing (paths, slashes)
tmux send-keys -t <name> Enter
tmux capture-pane -t <name> -p                # -p = plain text; add -e only for styling
```

- `-x 200 -y 50` fixes the pane size so `capture-pane` output is deterministic
  run to run — a resized pane reflows text differently.
- Always `-l` for user-typed strings; without it a literal path like
  `/foo/bar` gets parsed as arrow-key escapes instead of typed characters.
- Redirect stderr to a file — panics, log lines, and debug probes land there,
  not in the pane, so they won't show up in a `capture-pane` snapshot at all.

Kill any leftover session with the same name before starting a new one, so
reruns don't attach to a stale process:

```bash
tmux kill-session -t <name> 2>/dev/null   # idempotent: fine if nothing to kill
```

## Form fill: send-keys patterns

`send-keys` parses keystrokes by name (`Enter`, `BTab`, `C-u`) unless you pass
`-l` for literal text. A typical field-by-field fill mixes both:

```bash
tmux send-keys -t <name> "n"                  # tap a key to open the form
sleep 1
tmux send-keys -t <name> BTab                 # shift-tab back one field
sleep 0.3
tmux send-keys -t <name> C-u                  # clear the current line
sleep 0.3
tmux send-keys -t <name> -l "some/literal/path"   # literal — no key parsing
sleep 0.3
tmux send-keys -t <name> Tab                  # forward to next field
sleep 0.3
tmux send-keys -t <name> -l "text the user would type"
sleep 0.3
tmux send-keys -t <name> Enter                # submit
```

`sleep 0.3` between keys is usually enough; bump to 0.5–1.0s for field
transitions where the UI re-renders.

## Polling capture-pane for state

Poll `capture-pane -p` for a state string and grep the **glyph or word**, not
the color — `-p` drops ANSI styling by default (add `-e` only if you need
styling), and colors are also just harder to grep reliably than a fixed
glyph:

```bash
for i in $(seq 1 30); do
  pane=$(tmux capture-pane -t <name> -p)
  echo "$pane" | grep -q "state: processing" && break
  sleep 1
done
```

TUIs commonly use a distinct glyph per state, e.g. a Braille spinner (`⠋`)
while pending and an X mark (`✗`) on failure, with the glyph simply removed
once reconciled. Grep for the glyph itself, not for a color code.

## Two captures for optimistic UI

Mirror the web sync/async pattern: capture the pane immediately after the
triggering keypress, then again after a reconcile window. Without the
immediate capture you can't tell "rendered then reconciled" from "never
rendered":

```bash
tmux send-keys -t <name> -l "trigger the optimistic action"
tmux send-keys -t <name> Enter
echo "=== synchronous ===" ; tmux capture-pane -t <name> -p | grep -E "pending-glyph"
sleep 6
echo "=== reconciled  ===" ; tmux capture-pane -t <name> -p | grep -E "pending-glyph" || echo "[no pending — reconciled]"
```

## Plain-text mode over the alt-screen buffer

If the TUI has a flag that disables its alternate-screen buffer (a debug or
plain-output mode), use it when launching under tmux. `capture-pane` then sees
plain scrollback text instead of raw escape sequences from a full-screen
redraw, which is much easier to grep.

## Non-interactive CLIs don't need tmux

If the surface under test is a one-shot command rather than an interactive
session, skip tmux entirely — run the command and capture its stdout/stderr
directly. The tmux machinery exists for interaction, not for driving a binary
in general. Still run it against a real, freshly built instance, not a stale
one left over from an earlier session.
