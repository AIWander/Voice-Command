# Deployment

This directory is the published site. It is served two ways:

- **voice.aiwander.ai** via GitHub Pages (`main` / `docs`). GitHub Pages ignores
  `_headers`, so only the CSP-in-markup and its own `max-age=600` apply there.
- **aivoicemcp.pages.dev** via Cloudflare Pages, connected to this repo with build
  output `docs`. This is where `_headers` actually takes effect.

Before 2026-08-21 the Cloudflare project was a direct upload with no Git
connection, so repo edits never reached it. It is now wired to `main`, and a push
here deploys automatically.
