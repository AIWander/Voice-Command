# AIWander plugin package template

This file and `validate-plugin-package.ps1` are **vendored identically** into every
AIWander plugin repository. Change them once, copy them everywhere. Per-repo
differences belong in `.plugin-package.json`, never in a forked validator.

The rule behind the rule: **a template that is not a blocking gate is not a
template, it is a description.** Every item below is enforced in CI, because each
one is here as the result of a defect that actually shipped.

## The package

### Repository root

| Path | Purpose |
|---|---|
| `.claude-plugin/marketplace.json` | Storefront for Claude Code and Grok CLI. Advertises exactly the shipped profiles. **Never restates a version.** |
| `.agents/plugins/marketplace.json` | Storefront for Codex. Same profile set as above. |
| `.plugin-package.json` | This repo's census: marketplace name, advertised profiles, per-profile skill count, MCP expectation, hook hosts, parity groups. The validator reads it. |
| `scripts/validate-plugin-package.ps1` | The shared contract. Identical bytes in every repo. |
| `scripts/PLUGIN_PACKAGE_TEMPLATE.md` | This file. |
| `.gitignore` | Must ignore `plugins/<profile>/rendered-hooks/`. |
| `plugins/README.md` | Profile table with status, and "install exactly one profile". |

### Per profile, under `plugins/<profile>/`

| Path | Purpose |
|---|---|
| `.claude-plugin/plugin.json` | name, version, description, author, homepage, repository, license, keywords. No `skills`/`mcpServers` keys - Claude discovers them. **No `hooks` key**: opt-in packs stay inert. |
| `.codex-plugin/plugin.json` | Same core, plus explicit `skills`, `mcpServers`, and an `interface` block. Every `capabilities` string must be provable against a live `tools/list`. |
| `.mcp.json` | STDIO server registration. **Omit entirely** when the server is registered separately, or the plugin and the manual registration double-spawn it. |
| `skills/<skill>/SKILL.md` | Frontmatter opening `---`, a bare `name`, and one dense `description` carrying the trigger vocabulary. No TODO markers. |
| `skills/<skill>/agents/openai.yaml` | Required for every skill. Without it Codex cannot see the skill, while Claude looks fine - the failure is silent and host-specific. |
| `skills/<skill>/references/*.md` | Optional depth, so a dense skill stays short. |
| `hooks/opt-in/` | One shared policy file, `adapters/<host>/hook_adapter.py` per host, and `<host>-hooks.fragment.json` per host. Never auto-loaded. |
| `scripts/render-hooks.ps1` | Renders fragments with this machine's real path into `rendered-hooks/`. Validates JSON, writes UTF-8 without BOM, reports a SHA-256, and refuses to write outside the plugin root. |
| `instructions/APPLY_TO_YOUR_AI.txt` | Per-client activation for a **repository or marketplace** install. Required: `claude plugin marketplace add` never copies `installer/`, so an installer-only guide is a pointer to a file the user does not have. |

## Two hard rules

**1. One placeholder token: `__PLUGIN_ROOT__`.** Not `__AI_HANDS_PLUGIN_ROOT__`,
not `__VOICE_COMMAND_PLUGIN_ROOT__`. One token means one portable inertness
check across every repo, and one render script shape instead of three.

**2. Ground truth comes from a live `initialize` + `tools/list` handshake,
never from documentation.** Counts, tool names, and capability strings drift the
moment a server is rebuilt. Frontmatter `description` and `short_description` are
*trigger text*: a stale trigger routes the model to a server that cannot do the
job, which is worse than a stale sentence in a body paragraph.

## Parity groups are a choice, not a default

Set `parityGroups` when two profiles ship the *same* skill pack and differ only
by hook code - then byte-identity is correct and drift is a bug.

Leave it empty when profiles differ **on purpose**. AI-Hands is the worked
example: its hook-capable profile says covered risky calls remain denied, while
its hookless profile says the skill cannot block and confirmation must come from
the host's native path. Both are true of their own profile. Forcing byte-parity
there would make one of them a lie. Use a phrase contract instead.

## Adding a new package

1. Copy `validate-plugin-package.ps1` and this file into the new repo verbatim.
2. Write `.plugin-package.json` describing the census.
3. Build the package to the table above.
4. Wire the validator into `ci.yml` **and** the release workflow. A validator
   that runs only on CI still lets a hand-cut release ship unvalidated.
5. Run it. It should fail first, then pass - a contract that passes on the first
   run has usually not been wired up correctly.
