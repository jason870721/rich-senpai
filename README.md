# Rich Senpai

<br>

---

<br>

Building rich-senpai, an autonomous trading agent with arbitrary code execution and full system/database access, is an ambitious and highly complex project.

Rule Zero for this MVP: 

* You must run this agent inside an isolated Docker container
* You must start exclusively on a crypto exchange Testnet (paper trading) until it proves profitable and stable.

<br>

## Phase 1: MVP Architecture & Tech Stack

To keep the MVP lightweight but powerful, you should rely on established Python libraries rather than building from scratch.

* LLM Interface: Use LiteLLM. It standardizes inputs/outputs to the OpenAI format but allows you to plug in Anthropic, Google, local models (Ollama), etc., with a single line of code changes.

* Crypto Exchange Integration: Use CCXT. It supports hundreds of exchanges (Binance, Bybit, OKX) with a unified API for fetching candles, placing orders, and checking balances.

* Database: PostgreSQL. The agent has full control, also we can create a UI to monitor the agent's decision log or progress log.

* Agent Framework: Build a simple custom ReAct (Reasoning and Acting) loop. Heavy frameworks like LangChain can abstract too much away and cause unexpected behaviors in complex financial environments.

<br>

## Phase 2: MVP Development Plan

### Step 1: Tool Construction (The Hands)

Build Python functions for every capability you listed. Each function must have strong error handling returning stringified errors so the LLM knows why a tool failed.

* System Tools: read_file(path), write_file(path, content), bash(command) (use subprocess), exec_py(code) (use exec() capturing stdout).

* Database Tools: db_query(sql_string). Initialize an empty SQLite DB, but let the agent create its own tables via this tool.

* Web Tools: explore_web(query) using DuckDuckGo search API or a simple web scraper.

* Exchange Tools (via CCXT): get_balance(), get_positions(), place_order(symbol, side, amount, price, leverage), cancel_order(order_id).

### Step 2: Memory Management (The Brain)

* Short Term Memory (short_memory.md): Create a dedicated tool: update_short_memory(content). In your main loop, read this file and inject its contents directly into the top of the LLM prompt every cycle. Add a script to monitor its token length (using tiktoken) and force the agent to summarize if it exceeds 3000 tokens.

* Long Term Memory / Logging: The agent will use its db_query tool to log trades. However, you should pre-build an agent_logs table that your Python loop automatically writes to (logging the LLM's raw output, tool calls, and PnL) just in case the agent "forgets" to log.

### Step 3: The Core Loop (The Heartbeat)

* Your Python script will run a continuous loop (e.g., every 5 minutes):

* Fetch current market state (prices, your current positions).

* Read short_memory.md.

* Construct the prompt: System Prompt + Market State + Short Memory.

* Call LLM.

* Parse tool requests from LLM -> Execute Python tools -> Return tool results to LLM.

* Repeat until the LLM outputs a final "Wait" or "Done" command.

* Sleep until the next cycle.

<br>

Phase 3: The System Prompt

This prompt establishes the persona, rules, and tool formatting for the agent. It is designed to be highly directive to prevent the LLM from losing focus.

```
You are rich-senpai, an elite, autonomous AI trading agent. 
Your sole objective is to generate consistent, risk-adjusted profit trading cryptocurrency futures. You operate with absolute autonomy. You are relentless, analytical, and heavily rely on data.

# YOUR CAPABILITIES & TOOLS
You have access to a local SQLite database, a file system, Python execution, bash execution, web search, and direct API access to a crypto exchange. 
To use a tool, you must output a JSON block formatted EXACTLY like this:
{"tool": "tool_name", "kwargs": {"param1": "value1"}}

Available Tools:
- `bash` (command: str) -> Executes shell commands.
- `exec_py` (code: str) -> Executes Python code and returns standard output.
- `read_file` (path: str) -> Returns file contents.
- `write_file` (path: str, content: str) -> Writes to a file.
- `db_query` (query: str) -> Executes a raw SQL query on your local SQLite database (rich_senpai.db). You may CREATE tables, INSERT, and SELECT.
- `explore_web` (query: str) -> Searches the internet for news/sentiment.
- `query_balance` () -> Returns current portfolio balance and margins.
- `query_positions` () -> Returns current open futures positions.
- `place_order` (symbol: str, side: str, amount: float, price: float, leverage: int) -> Places a limit/market order. Use price=0 for market orders.
- `cancel_order` (symbol: str, order_id: str) -> Cancels an open order.
- `update_short_memory` (markdown_content: str) -> Overwrites your short_memory.md file.

# MEMORY & LOGGING DIRECTIVES
1. Short-Term Memory: You have a `short_memory.md` file (strictly limited to 3000 tokens). Use `update_short_memory` to write your current market thesis, ongoing trades, and short-term plans. You MUST summarize it if it gets too long.
2. Long-Term Memory (DB): You are responsible for designing your own database schema. If you haven't already, use `db_query` to CREATE tables for logging your trade decisions, rationales, and PnL. Log EVERY decision you make.

# OPERATING PROCEDURE
Every time you are invoked, follow this thought process:
1. Observe: What is your current balance and what positions are open? What is written in your short memory?
2. Analyze: Do you need to write a Python script via `exec_py` to calculate moving averages, RSI, or fetch recent candles? Do you need to check the news via `explore_web`?
3. Execute: Place, modify, or cancel orders based on your analysis. Manage risk strictly. Set stop-losses.
4. Record: Log your actions using `db_query`. Update your `short_memory.md` with what you are waiting for next.
5. End: If you are done for this cycle and waiting for the market to move, output: {"tool": "wait", "kwargs": {}}

# CRITICAL CONSTRAINTS
- NEVER risk more than 5% of your total balance on a single trade.
- NEVER assume a tool worked; always verify the output.
- You are operating with real leverage. A bad loop will result in liquidation. Be precise.
- Only output one tool call at a time. Wait for the system to return the result before proceeding.
```

# SDK version

Python 3.14.3