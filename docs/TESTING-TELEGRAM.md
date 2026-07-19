# Test Telegram remote control (from scratch)

Start here if you do **not** have `em` installed yet.

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

You need **Cursor Agent** logged in for the Flutter test:

```bash
agent login
agent status
```

Optional: Flutter SDK if you run the sample app (`flutter --version`).

## B. Telegram (one-time)

1. Telegram → [@BotFather](https://t.me/BotFather) → `/newbot` → copy the **token**
2. Run:

```bash
em config telegram
```

3. Paste the token  
4. When asked: open **your new bot** in Telegram and send `hi`  
5. `em` detects your chat id and sends a setup message to your phone  

That is all for Telegram.

## C. Real pipeline test

```bash
cd examples/sample_flutter_app
```

In `workflow.yaml`, on the `review` task, add:

```yaml
    requires_approval: true
```

Then:

```bash
em run workflow.yaml
```

What to expect:

- Telegram message after each finished task  
- Pause before `review` with **Approve / Reject** on Telegram  
- Tap **Approve** → review runs → final run summary on Telegram  

Desk fallback: `em approve <run_id> review` (see `em status` for the run id).
