# Agent Tools

<br>

---

<br>

## What is this package?

* `tool_register.py`: Registers all agent tools in a single map and dispatches calls by name. Exposes `SYS_TOOL_PROMPT`, `TOOL_SPECS` (Anthropic tool-spec format), `TOOL_HANDLERS`, and `call_tool(name, arguments)`.

* `read_file.py`: Reads a local text file and returns its contents. Handles missing files, non-regular paths, and decoding errors.

* `write_file.py`: Creates or overwrites a local file with the given content. Requires the parent directory to already exist.

* `bash.py`: Executes a shell command via `/bin/bash` with a timeout and optional `cwd`, returning exit code, stdout, and stderr.

* `http_request.py`: Sends an HTTP request (GET/POST/PUT/PATCH/DELETE) with optional headers and a JSON or text body, returning status, headers, and response body.

<br>

---

<br>

## How tools are registered

Each tool module exports two things:

* `SPEC` — an Anthropic tool spec dict: `{ "name", "description", "input_schema" }`.
* A handler function whose signature matches the `input_schema`.

`tool_register.py` imports every tool module and wires them into:

* `TOOL_SPECS: list[dict]` — pass directly as `tools=` to `client.messages.create`.
* `TOOL_HANDLERS: dict[str, Callable]` — name → handler.
* `call_tool(name, arguments)` — dispatches a tool call, returning the handler's string output (or an error string for unknown tools / invalid arguments).

To add a new tool: create `tools/<your_tool>.py` with a `SPEC` and a handler, then append both to `TOOL_SPECS` and `TOOL_HANDLERS` in `tool_register.py`.

<br>

---

<br>

## Usage

```python
from tools import tool_register

# Pass to the Anthropic API
client.messages.create(
    model="claude-opus-4-7",
    system=tool_register.SYS_TOOL_PROMPT,
    tools=tool_register.TOOL_SPECS,
    messages=[...],
)

# Dispatch a tool_use block returned by the model
result = tool_register.call_tool("read_file", {"path": "main.py"})
```

<br>

---

<br>

## Module spec

The agent core that consumes these tools is specified under
[`.claude/spec/agent-core/`](../.claude/spec/agent-core/). See `SPEC.md` for
the public interface, `PLAN.md` for phased work, and `PROGRESS.md` for
current status.
