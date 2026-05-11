# session_tui

The Textual REPL that talks to `core.AgentCore`. This is the only
human-facing surface of rich-senpai; if you're touching how the user
sees / interacts with the agent, you're in the right place.

This README is for developers extending the TUI. For the user-facing
keymap and slash commands, type `/help` inside the running app.

---

## How a turn flows

```
  user types in HistoryInput
        │
        ▼
  on_history_input_submitted   ─►  /quit alias?  ─► app.exit()
        │                          /xxx command? ─► commands.dispatch(app, …)
        ▼ (otherwise)
  format_user_echo  →  log
        │
        ▼
  run_worker(_run_turn_async)
        │
        ▼
  AgentCore.run_turn(messages, text)
        │           │
        │           └── on_event(event)   ─►  events.render_event(app, event)
        │                                      ├─ paints into RichLog
        │                                      └─ updates spinner status
        ▼
  CycleResult
        │
        ▼
  _on_turn_done       ─►  format_turn_footer → log
                          accumulate session counters
                          _refresh_input_stats
                          _set_busy(False)
```

Two important invariants:

1. **The agent runs on the same asyncio loop as Textual.** `on_event`
   callbacks mutate widgets directly — no thread hop. If you ever
   spawn a background thread that needs to write to the log, marshal
   it through `app.call_from_thread(...)`.
2. **`AgentCore` knows nothing about Textual.** It emits dict events
   through `on_event` and that's the contract. Don't import Textual
   types into `core/`.

---

## Module map

| File | Responsibility | When you edit it |
|---|---|---|
| `tui.py` | `SenpaiApp` — the Textual `App`. Composes the widget tree, wires agent events, owns timers, runs workers. | Adding a widget, changing event/turn lifecycle, adjusting timers. |
| `styles.tcss` | All CSS. Loaded via `App.CSS_PATH`. | Spacing, colors, dock heights, focus borders. |
| `widgets.py` | `HistoryInput` — multi-line `TextArea` with submit-on-enter, history nav, paste-collapse. | Anything about the *input box* itself (key bindings, paste handling, history persistence). |
| `panels.py` | `TodosPanel`, `BackgroundPanel`, `CoworkerPanel` — docked status panels. | Adding a new live status panel. |
| `live_panel.py` | `LivePanel[T]` — the scaffold every panel inherits. Snapshot → signature → all-settled? → archive / hide lifecycle. | Adding capability to the panel framework itself. Rare. |
| `events.py` | Per-event renderers (`assistant_text`, `tool_use`, `tool_result`, …). `EVENT_RENDERERS` dispatch table. | Adding a new agent-event kind, or changing how an existing one looks. |
| `render.py` | Pure rendering primitives — `block`, `bar_line`, `format_input_stats`, `format_status_line`, etc. **No widget access, no app state.** | Adding a new reusable Rich-renderable factory. |
| `commands.py` | Slash-command registry — `Command` records, free-function handlers, `dispatch(app, alias)`. | Adding `/foo`, changing `/help` content, swapping a handler. |
| `clipboard.py` | `copy_to_clipboard(text)` — `pbcopy / wl-copy / xclip` adapter. | Replacing the clipboard backend. |
| `welcome.py` | The intro panel painted on `on_mount` and `/clear`. | Splash / banner changes. |
| `style.py` | Palette, spinner frames, history path, quit aliases, tool-result preview cap. | Brand color changes, spinner tweaks. |
| `assets/` | `banner.txt` and any other static assets. | Swapping the ASCII banner. |
| `__init__.py` | Re-exports `SenpaiApp` and `main`. | Don't usually touch. |

The `core/` package is **upstream** — `session_tui` imports from it,
never the reverse.

---

## Visual layout

```
┌──────────────── Header (model_label) ────────────────────────────┐
│  RichLog (id="log")  ── 1fr, fills available space               │
│  ▸ assistant text                                                │
│  ⏺ tool_use(...)  iter N                                          │
│  ⎿ tool_result body                                               │
│  …                                                                │
├───────────────────────────────────────────────────────────────────┤
│  TodosPanel  (id="todos")  ── auto-hides when no todos           │
│  BackgroundPanel  (id="bg")                                       │
│  CoworkerPanel  (id="coworkers")                                  │
├───────────────────────────────────────────────────────────────────┤
│  ⠋ thinking…   iter 3   1.2s   ollama (qwen3.6:latest)   esc to interrupt  ← #status (busy only)
├──── #input_dock ─────────────────────────────────────────────────┤
│  /help · /clear · /compact · /tasks · /team · /inbox · /copy · /quit  ← #input_hint
├───────────────────────────────────────────────────────────────────┤
│  ❯  user types here, 3-6 rows tall, multi-line via shift+enter  │
├───────────────────────────────────────────────────────────────────┤
│  ollama (qwen3.6:latest)  ·  in 1,234  out 567 tok  ·  iter 23  ·  up 0d 1h 24m  ← #input_stats
└───────────────────────────────────────────────────────────────────┘
```

`#input_dock` is a `Vertical` with `dock: bottom`. Panels above it
flow normally because `RichLog` has `height: 1fr` and absorbs leftover
space.

---

## Common tasks

### Add a slash command

1. Open `commands.py`.
2. Write a free function:
   ```python
   def cmd_foo(app: "SenpaiApp") -> None:
       app.write(Text("foo", style="bold green"))
   ```
3. Append a registry entry:
   ```python
   Command("/foo", "do the foo thing", cmd_foo),
   ```

That's it. The placeholder hint above the input picks the new alias
up automatically (`commands.placeholder_summary()`), and `/help`
generates its body from the same registry.

If your command needs to read App state, expose a public method or
property on `SenpaiApp` (see `last_assistant_text`, `compact_history`).

### Add a docked status panel

1. Open `panels.py`. Subclass `LivePanel[T]` and implement four hooks:
   - `snapshot() -> list[T]` — pull current items from the source of truth.
   - `signature(items) -> tuple` — hashable identity for archive dedupe.
   - `all_settled(items) -> bool` — when True, archive once + hide.
   - `build_body(items) -> Text` — render the items.
2. Optionally override `header_meta(items) -> str` for a one-line
   summary next to the title.
3. In `tui.py`:
   - Add the widget to `compose()`: `yield Static("", id="my_panel")`.
   - Add a CSS rule in `styles.tcss`:
     ```
     #my_panel { height: auto; max-height: 12; padding: 0 2; }
     ```
   - Instantiate in `__init__`: `self.my_panel = MyPanel()`.
   - Refresh on mount + on `/clear`.
   - If the source mutates outside the agent thread, refresh in
     `_tick_panels` (1Hz). Set `skip_unchanged=True` on the panel
     so the tick is cheap.

### Add an agent-event renderer

Agent events are dicts with `{"type": ..., "iteration": ...}`. To
render a new event type:

1. Open `events.py`.
2. Write `def render_my_event(app, event): ...` using helpers from
   `render.py`.
3. Add to the dispatch table:
   ```python
   EVENT_RENDERERS = {
       ...
       "my_event": render_my_event,
   }
   ```
4. If the event should also drive the spinner label, add a branch in
   `status_label_for(event)`.

The agent emits the event from `core/agent_core.py` via `self._emit(...)`.

### Tweak layout / colors

`styles.tcss`. Real `.tcss` syntax — your editor will highlight it.
Hot-reload during development by quitting and restarting the app
(Textual doesn't reload CSS at runtime).

Palette is in `style.py` — `BRAND`, `ACCENT`, `GOLD`, `OK`,
`TOOL_USE`, `SUBTLE`. Reference these from CSS via Textual variables
*won't* work; reference them from Python (`Text.assemble`, etc.)
using the constants. CSS color values stay literal.

### Add a key binding

Two scopes:

- **Global** (works regardless of focus): add to `SenpaiApp.BINDINGS`
  in `tui.py` and define `action_xxx` on the App.
- **Input-only** (when `HistoryInput` has focus): add to
  `HistoryInput.BINDINGS` in `widgets.py` and define `action_xxx`
  on the widget.

Use `priority=True` on the binding when you need to override one of
TextArea's defaults (e.g. `enter` for submit instead of newline).

### Change paste-collapse thresholds

`widgets.py`:
```python
_PASTE_CHAR_THRESHOLD = 200
_PASTE_LINE_THRESHOLD = 4
```
Pastes below both drop in verbatim; pastes above either threshold
collapse to a `[paste #N: NNN chars, M lines]` marker. The original
text is stashed in `HistoryInput._paste_stash` and re-substituted
by `expanded_text()` on submit.

---

## Testing

There is no traditional test suite for the TUI. Use Textual's
`App.run_test()` with `Pilot` for headless smoke tests:

```python
import asyncio
from session_tui import SenpaiApp
from session_tui.widgets import HistoryInput

async def main():
    app = SenpaiApp()
    async with app.run_test(size=(120, 40)) as pilot:
        prompt = app.query_one(HistoryInput)
        prompt.focus()
        await pilot.pause()
        await pilot.press(*"hello")
        await pilot.press("shift+enter")
        await pilot.press(*"world")
        await pilot.press("enter")
        # …assert on widget state…
        await app.action_quit()

asyncio.run(main())
```

For end-to-end runs that involve the agent, stub out the LLM by
patching `AgentCore.__init__` to inject a `StubLLM` that returns a
fixed `LLMResponse`. Don't burn real API tokens in a smoke test.

To read a `Static`'s rendered text:

```python
def textof(static):
    r = static.render()
    return r.plain if hasattr(r, "plain") else str(r)
```

---

## Conventions

- **Pure render functions go in `render.py`.** No widget access, no
  app state — they take primitives in, return Rich renderables out.
  This keeps them trivially unit-testable.
- **`render_event` is the *only* way agent events become UI.** Don't
  reach into the App from inside the agent. If you need new UI
  behavior on a turn, extend the event payload in `core/agent_core.py`
  and add a renderer in `events.py`.
- **The App is the orchestrator.** Lifecycle (`on_mount`,
  `on_unmount`, `_set_busy`, `_tick_panels`), event wiring, and
  worker scheduling live in `tui.py`. Anything else is delegated.
- **Public API on `SenpaiApp` is what `commands.py` and panels touch:**
  `write(renderable)`, `last_assistant_text`, `compact_history()`,
  `action_clear_history()`, `action_interrupt()`,
  `suppress_tool_id()`, `consume_suppressed()`. Treat the rest as
  private; rename freely.
- **No emoji in code comments.** (Project-wide rule — see system
  prompt.) Glyphs in *rendered output* are fine; that's the brand.
- **Default to no comments on UI rendering code.** A well-named
  `format_input_stats` doesn't need to be explained. Comments are
  for non-obvious *whys* — race conditions, surprising layout rules,
  workarounds for upstream Textual quirks.

---

## Gotchas

- **`TextArea.Changed` auto-routes to `on_text_area_changed`, not
  `on_history_input_changed`.** Textual's auto-dispatch keys off the
  message class's *owning widget*, not the subclass it bubbled
  through. If you subclass another Textual widget and want to listen
  to its events, use the parent's name.
- **Multi-line paste arrives as a single `Paste` event.** Don't try
  to debounce keystrokes to detect pastes — Textual already gives
  you the whole thing at once via bracketed-paste.
- **CSS specificity.** `HistoryInput` (a TextArea subclass) inherits
  Textual's default `TextArea { ... }` rules. Set explicit
  `min-height` / `max-height` / `overflow` / `scrollbar-size` on
  `HistoryInput` to override — relying on parent constraints won't
  work because TextArea declares its own height.
- **Don't print().** A stray `print` from inside a teammate or tool
  scrambles the rendered screen. Route everything through
  `core.logging_setup.get_logger()` (writes to a session file) or
  through the `app.write(renderable)` log path.
- **`exclusive=True` on `run_worker` is per-name, not global.** Two
  workers with different names can run simultaneously. We do this
  intentionally: the agent turn worker (`name="agent_turn"`) and the
  compact worker (`name="compact_history"`) are mutually exclusive
  via the `_busy` flag, not the worker scheduler.

---

## Further reading

- Textual docs: https://textual.textualize.io/
- Project-wide guidance: `core/sys_prompt.py` (the agent's own
  system prompt — useful for understanding what events the agent
  emits and what behaviors it expects).
- Logging: `core/logging_setup.py` — every TUI event has a matching
  log line in `.senpai/logs/session-*.log` when `LOG_LEVEL=DEBUG`.
