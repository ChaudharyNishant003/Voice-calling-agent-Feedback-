# Patient Feedback Voice Agent (PFA)

A multilingual (English + Hindi + Hinglish) patient-listening system for Indian hospitals. See
[`CLAUDE.md`](CLAUDE.md) and [`docs/`](docs/) for the full product/architecture spec.

This README covers the **Demo MVP**: a browser-based, no-login voice feedback conversation you can
run yourself in Chrome to try the product end to end. The full telephony/production system
(Sprints 1–8, [`docs/11_BUILD_PLAN.md`](docs/11_BUILD_PLAN.md)) is being built alongside it.

## Prerequisites

- Docker Desktop
- A Gemini and/or OpenAI API key (get one yourself — this app never asks you to paste a key into
  chat with an AI assistant; you enter it directly into the app's own Settings page)

## 1. Start the stack

```bash
cp .env.example .env
```

Open `.env` and set:

```
DEMO_MODE=true
```

(`DEMO_MODE` defaults to `false` and is refused outright if `APP_ENV=production` — it's meant for
your own machine only.)

```bash
make up
```

This starts Postgres, Redis, the API, worker, beat, agent, dashboard, Mailpit, MinIO, and
LiveKit. First boot takes a few minutes while images build.

```bash
make migrate
```

## 2. Open the demo

Go to **http://localhost:3000/demo**.

### Configure a provider

Click **Settings**. For Gemini and/or OpenAI:

1. Paste your API key into the field for that provider.
2. Pick a model from the dropdown.
3. Click **Save & Test** — this makes one real call to the provider to confirm the key actually
   works, and only then marks it "Connected". A key that's saved but fails validation shows
   "Invalid" (bad key) or "Error" (something else went wrong) — either way it's never silently
   treated as working.

Your key is encrypted before it's stored and is never shown again, logged, or sent back to the
browser in full — only a status (Connected/Invalid/Error) and the model name.

While you're on the Settings page, also set the **hospital name**, **agent name**, and **agent
voice** (female/male) for the demo. The page tells you if your browser doesn't have a matching
voice for the language + gender you picked (common for male Hindi voices) — it'll fall back to the
closest one available rather than fail.

### Start a call

Back on the main page, pick a connected provider and click **Start Demo Call**. Allow microphone
access when Chrome asks. The agent greets you in Hinglish; reply out loud, or type in the text box
if you'd rather not use the mic (or if speech recognition isn't available) — both go through the
exact same backend conversation engine.

A short script to try the language-switching behavior (spec-verified):

1. Reply in Hindi/Hinglish — the conversation locks to that.
2. Reply once in English — it stays locked to Hindi/Hinglish (a single off-family reply doesn't
   switch it).
3. Reply in English three times in a row — *now* it switches to English.
4. Say "Hindi mein baat karo" — it switches back immediately, no waiting for a streak.

The call closes itself after enough feedback is collected (or after 8 turns regardless, as a hard
ceiling) — you don't need to do anything to end it, though an **End Call** button is there too.

### Debug a call

Every call has a **Debug** link (top right once a call is running) showing the full event
timeline: call/session state, provider/model, locked language, and every step with its
input/output/timestamps. If a step fails, it shows up in red so it's obvious what broke.

## Troubleshooting

- **A dashboard code change doesn't seem to show up.** Docker Desktop on Windows doesn't always
  forward file-change notifications across the bind-mounted `dashboard/` folder to the Next.js dev
  server. The dev server is configured to poll for changes (`dashboard/next.config.mjs`), which
  should cover this, but if you still don't see an update: `docker restart pfa-dashboard-1`.
- **Microphone doesn't work / permission denied.** Check Chrome's site settings for
  `localhost:3000` and allow the microphone, then reload. The text box always works as a fallback
  regardless.
- **"Not Configured" / "Invalid" won't go away.** The status only flips to "Connected" after a real
  test call to the provider succeeds — check the key, and check the model you picked is one your
  key actually has access to.
- **The whole `/demo` page 404s.** `DEMO_MODE` is off, or `APP_ENV=production`. Check `.env`.
- **Something crashed mid-call.** It shouldn't — LLM failures are caught, retried once, and fall
  back to a generic response so the call keeps going. Check the call's Debug page for the exact
  failed step; check `docker logs pfa-api-1` for anything unexpected.

## Full backend/dashboard development

```bash
make lint          # ruff + mypy --strict + eslint + tsc + import-linter
make test           # backend unit + integration (real Postgres via testcontainers)
make test-safety     # safety golden set (production call-flow only, not the demo)
```

See [`CLAUDE.md`](CLAUDE.md) for coding conventions, the full command list, and the non-negotiable
rules this codebase follows.
