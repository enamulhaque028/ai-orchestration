# Sample Flutter app for `em`

Demo project for the Engineering Manager. The workflow builds a store +
checkout feature using [Fake Store API](https://fakestoreapi.com).

Default workflow uses **Cursor Agent CLI**. Change `provider:` in the YAML to
`claude`, `codex`, or `gemini` if you prefer another CLI.

## Run

From the **repo root**:

```bash
source .venv/bin/activate
export PATH="$HOME/.local/bin:$PATH"   # if using Cursor Agent

# Log into your chosen CLI once (examples):
#   agent login
#   claude

em run examples/workflows/flutter-checkout.yaml
em status --state-dir examples/sample_flutter_app/.em
```

Pipeline: API → UI → QA → (fix if needed) → review.

After a successful run:

```bash
cd examples/sample_flutter_app
flutter test
flutter run
cat docs/REVIEW.md
```
