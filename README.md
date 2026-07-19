# Engineering Manager (`em`)

Coordinate multiple AI coding CLIs from one YAML file.

You define the tasks and dependencies. `em` starts agents, waits for them,
runs the next steps, retries failures, and resumes if you interrupt — so you
don’t babysit each worker.

Works with any supported agent CLI on your machine (Cursor Agent, Claude Code,
Codex, Gemini, or a custom shell command).

## Install (recommended)

Works on **macOS**, **Linux**, and **Windows**.

### macOS / Linux

```bash
curl -fsSL https://raw.githubusercontent.com/enamulhaque028/ai-orchestration/main/install.sh | bash
```

Then open a **new terminal** (or `export PATH="$HOME/.local/bin:$PATH"`):

```bash
em --help
em doctor
```

### Windows (PowerShell)

```powershell
irm https://raw.githubusercontent.com/enamulhaque028/ai-orchestration/main/install.ps1 | iex
```

Open a **new** PowerShell window, then:

```powershell
em --help
em doctor
```

If scripts are blocked:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Install once — use `em` in any project. You do **not** need this repo inside each project.

Upgrade later: re-run the installer for your OS, or:

```bash
pipx install --force git+https://github.com/enamulhaque028/ai-orchestration.git
```

### If `em` is not found

**macOS / Linux**

```bash
export PATH="$HOME/.local/bin:$PATH"
# permanent: add that line to ~/.zshrc or ~/.bashrc
```

**Windows**

Ensure `%USERPROFILE%\.local\bin` is on your User PATH  
(Settings → System → About → Advanced system settings → Environment Variables),  
then open a new terminal.

```bash
em doctor
```

### Development install (contributors only)

```bash
git clone https://github.com/enamulhaque028/ai-orchestration.git
cd ai-orchestration
python3 -m venv .venv          # Windows: py -3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e .
em doctor
```

## Prerequisites

The **installer** handles Python + pipx for you when possible.

**Agent CLIs** — install only what your workflow uses (the installer does not
auto-install these; they need their own login):

| Provider | CLI | Setup |
|----------|-----|--------|
| Cursor | `agent` / `cursor-agent` | Install Cursor Agent → `agent login` |
| Claude Code | `claude` | Install + log in |
| Codex | `codex` | Install + log in |
| Gemini | `gemini` | Install + log in |
| Shell | any command | On `PATH` |

```bash
em doctor    # shows which agent CLIs are available
```

**Optional:** Flutter SDK — only for the [Flutter demo](examples/sample_flutter_app/workflow.yaml).

## Quick start

A workflow is just a YAML file that lives **in your project**. Point `em run` at it.

**1. Go to your project and create a workflow file:**

```bash
cd /path/to/your/repo
```

Create a starter `workflow.yaml` there:

```bash
em init
```

Edit the prompts to describe your feature (see [Write a workflow](#write-a-workflow))
and keep `cwd: .`.

**2. Run it from inside your project:**

```bash
em run workflow.yaml
em status
```

**Full Flutter demo** (needs Flutter SDK + Cursor Agent):

```bash
cd ai-orchestration/examples/sample_flutter_app
em run workflow.yaml
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
em init                           # create a starter workflow.yaml
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
| [`examples/sample_flutter_app/workflow.yaml`](examples/sample_flutter_app/workflow.yaml) | Real Flutter feature pipeline (lives in the app) |

`em init` writes a starter workflow (mixed Claude + Cursor) into your project.

Flutter app notes: [`examples/sample_flutter_app/README.md`](examples/sample_flutter_app/README.md).

## Development

```bash
pip install -e ".[dev]"
pytest
```
