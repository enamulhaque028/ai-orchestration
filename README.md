# Engineering Manager (`em`)

Coordinate multiple AI coding CLIs from one YAML file.

You define the tasks and dependencies. `em` starts agents, waits for them,
runs the next steps, retries failures, and resumes if you interrupt — so you
don’t babysit each worker.

Works with any supported agent CLI on your machine (Cursor Agent, Claude Code,
Codex, Gemini, or a custom shell command).

## Prerequisites

**Required**

| Requirement | Notes |
|-------------|--------|
| Python **3.11+** | Check with `python3 --version`. macOS system Python is often too old — use [Homebrew](https://brew.sh) (`brew install python`). |
| [pipx](https://pipx.pypa.io/) | Recommended installer so `em` is available globally. `brew install pipx` then `pipx ensurepath`. |
| Terminal | `em` is a command-line tool |

**Agent CLIs** (install only what your workflow uses)

| Provider | CLI binary | Setup |
|----------|------------|--------|
| Cursor | `agent` or `cursor-agent` | Install Cursor Agent (often `~/.local/bin`). Then `agent login`. |
| Claude Code | `claude` | Install Claude Code; log in once. |
| Codex | `codex` | Install Codex CLI; log in once. |
| Gemini | `gemini` | Install Gemini CLI; log in once. |
| Shell / custom | your command | On `PATH`, or use an absolute path in the YAML. |

```bash
python3 --version          # must be 3.11+
which pipx
which agent claude         # whichever you plan to use
```

**Optional (examples only)**

| Requirement | When needed |
|-------------|-------------|
| Flutter SDK | Running [`examples/workflows/flutter-checkout.yaml`](examples/workflows/flutter-checkout.yaml) |

## Install

Install **once**. After that, `em` works in any project — you do **not** need to clone this repo into each project.

### Recommended: pipx (global `em` command)

```bash
# 1) pipx (macOS example)
brew install pipx
pipx ensurepath

# 2) Restart the terminal (or open a new tab), then:
pipx install git+https://github.com/enamulhaque028/ai-orchestration.git

# 3) Confirm
em --help
```

`pipx ensurepath` adds `~/.local/bin` to your shell `PATH`. If you still get `command not found: em`:

```bash
# Put this in ~/.zshrc (or ~/.bashrc), then restart the terminal:
export PATH="$HOME/.local/bin:$PATH"

# Or run once in the current session:
export PATH="$HOME/.local/bin:$PATH"
em --help
```

Upgrade later:

```bash
pipx upgrade em
# or reinstall from git:
pipx install --force git+https://github.com/enamulhaque028/ai-orchestration.git
```

### Development (local clone)

Only needed if you are changing `em` itself:

```bash
git clone https://github.com/enamulhaque028/ai-orchestration.git
cd ai-orchestration
python3 -m venv .venv
source .venv/bin/activate   # required each new shell while developing
pip install -e .
em --help
```

Without activating `.venv`, `em` will not be found from that install.

## Quick start

Dry-run (no real agent):

```bash
em run workflows/example-feature.yaml
em status
```

Real agents on a project:

```bash
# 1) Log into the CLI(s) you use, e.g.:
#    agent login          # Cursor Agent
#    claude               # Claude Code (follow login)

# 2) Edit a workflow: set provider + prompts, set cwd to your repo

# 3) Run
em run path/to/workflow.yaml
```

Flutter demo (Cursor Agent CLI by default):

```bash
export PATH="$HOME/.local/bin:$PATH"
em run examples/workflows/flutter-checkout.yaml
```

## Supported providers

Set `provider` on each agent. Auth is whatever that CLI already uses (login /
session) — `em` does not require you to paste API keys for CLI mode.

| `provider` | CLI | Typical setup |
|------------|-----|----------------|
| `cursor` | `agent` / `cursor-agent` | `agent login` |
| `claude` | `claude` | Claude Code login |
| `codex` | `codex` | Codex login |
| `gemini` | `gemini` | Gemini CLI login |
| `shell` | any command | your own script/binary |
| `mock` | (built-in) | tests / dry-run |

Mix providers in one workflow (e.g. Cursor for UI, Claude for QA).

## Write a workflow

```yaml
name: my-feature
cwd: /path/to/your/repo
max_parallel: 2
defaults:
  on_failure: retry
  max_retries: 1

agents:
  coder:
    provider: cursor        # or claude / codex / gemini / shell
    model: composer-2.5
  qa:
    provider: claude
    model: sonnet

tasks:
  - id: implement
    agent: coder
    prompt: |
      Implement the feature described below...

  - id: test
    agent: qa
    depends_on: [implement]
    prompt: |
      Write and run tests.
      Upstream: {{upstream.summary}}

  - id: fix
    agent: coder
    depends_on: [test]
    when: on_upstream_failure
    prompt: |
      Fix failing tests.
      {{upstream.summary}}
```

**Rules**

- No `depends_on` → can start immediately (up to `max_parallel`).
- With `depends_on` → starts after those tasks finish.
- `when: on_upstream_failure` → recovery task if a dependency failed.
- `when: on_upstream_success` → only if dependencies succeeded.
- Placeholders: `{{cwd}}`, `{{workflow.name}}`, `{{upstream.summary}}`,
  `{{task.<id>.summary}}`, `{{task.<id>.output}}`.

**Shell provider** (custom CLI / script):

```yaml
agents:
  lint:
    provider: shell
tasks:
  - id: lint
    agent: lint
    command: npm run lint
    prompt: ""
```

## Commands

```bash
em run workflow.yaml              # start
em status                         # latest run
em status <run_id>                # one run
em resume                         # continue latest
em resume <run_id>
em cancel <run_id>
```

Useful flags: `--cwd`, `--state-dir`, `--no-live`.

Ctrl+C stops the process; `em resume` continues pending work.

State and logs (default under the project `cwd`):

```
.em/
  latest
  runs/<run_id>.json
  logs/<run_id>/<task>.log
```

## Examples

| File | Purpose |
|------|---------|
| [`workflows/example-feature.yaml`](workflows/example-feature.yaml) | Mock agents (no CLI needed) |
| [`workflows/example-real-agents.yaml`](workflows/example-real-agents.yaml) | Mixed Claude + Cursor |
| [`examples/workflows/flutter-checkout.yaml`](examples/workflows/flutter-checkout.yaml) | Real Flutter feature pipeline |

Flutter app notes: [`examples/sample_flutter_app/README.md`](examples/sample_flutter_app/README.md).

## Development

```bash
pip install -e ".[dev]"
pytest
```
