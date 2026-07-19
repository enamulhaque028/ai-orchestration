# Test Telegram remote control (from scratch)

Hands-on checklist. For full feature documentation (how it works, ask types, config, security), see **[`REMOTE-CONTROL.md`](REMOTE-CONTROL.md)**.

## A. Install `em` (this feature branch)

```bash
git clone https://github.com/enamulhaque028/ai-orchestration.git
cd ai-orchestration
git checkout feature/telegram-remote-control

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .

export PATH="$HOME/.local/bin:$PATH"
em doctor
```

Cursor Agent (for the Flutter sample):

```bash
agent login
agent status
```

Optional: Flutter SDK (`flutter --version`).

## B. Telegram (one-time)

1. Telegram → [@BotFather](https://t.me/BotFather) → `/newbot` → copy the **token**
2. Run `em config telegram`
3. Paste the token → message your bot `hi` → `em` detects chat id and sends a setup message

```bash
em notify test    # optional extra ping
```

## C. Real pipeline test

```bash
cd examples/sample_flutter_app
```

On the `review` task in `workflow.yaml`, add:

```yaml
    requires_approval: true
```

Run:

```bash
em run workflow.yaml
```

Expect:

- Telegram summary after each finished task  
- Pause before `review` (`waiting_approval`) with Approve / Reject  
- Tap **Approve** → review runs → run-finished summary  

Desk: `em approve <run_id> review` (`em status` for the id).

### Agent-raised ask (optional check)

If an agent prints:

```text
EM_ASK:{"type":"choice","question":"Which color?","options":["red","blue"]}
```

Answer in Telegram or:

```bash
em answer <run_id> <task_id> --text "blue"
```

`em` re-runs that task with your answer. Details: [Agent-raised asks](REMOTE-CONTROL.md#8-agent-raised-asks-em_ask).
