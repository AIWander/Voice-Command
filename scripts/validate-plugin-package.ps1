<#
  validate-plugin-package.ps1 - the shared AIWander plugin-package contract.

  This file is VENDORED IDENTICALLY into every AIWander plugin repository. Do not
  fork it per repo: change it once, copy it everywhere, and let the per-repo
  differences live in .plugin-package.json instead. The validator carries the
  rules that are true for every package; the config carries the census that is
  true for this one.

  Every rule here exists because the absence of it shipped a real defect:
    - a marketplace advertising a version that drifted from the manifests
    - a plugin README pointing at a file only the installer produces
    - rendered hook JSON carrying one machine's absolute paths
    - skills advertising tools the server had already removed
    - a profile pair whose reference docs silently diverged

  Usage:  pwsh -File scripts/validate-plugin-package.ps1
          pwsh -File scripts/validate-plugin-package.ps1 -RepoRoot <path>
#>
[CmdletBinding()]
param(
    [string] $RepoRoot
)

$ErrorActionPreference = 'Stop'
if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent $PSScriptRoot }
$RepoRoot = [System.IO.Path]::GetFullPath($RepoRoot)

$configPath = Join-Path $RepoRoot '.plugin-package.json'
if (-not (Test-Path -LiteralPath $configPath)) {
    throw "Missing plugin-package contract: $configPath (every AIWander plugin repo declares its census here)."
}
$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json

$problems = [System.Collections.Generic.List[string]]::new()
function Add-Problem([string] $message) { $problems.Add($message) | Out-Null }
function Read-Json([string] $path) { Get-Content -LiteralPath $path -Raw | ConvertFrom-Json }

$advertised = @($config.advertisedProfiles)
if (-not $advertised -or $advertised.Count -lt 1) { throw "$configPath declares no advertisedProfiles." }

# ---------------------------------------------------------------- marketplaces
# Both storefronts must describe the same shipped set. A version restated here
# can only drift from the manifest, so it is banned outright rather than synced.
foreach ($relative in @($config.marketplaces)) {
    $marketplacePath = Join-Path $RepoRoot $relative
    if (-not (Test-Path -LiteralPath $marketplacePath)) { Add-Problem "Missing marketplace file: $relative"; continue }
    $marketplace = Read-Json $marketplacePath
    if ($config.marketplaceName -and $marketplace.name -ne $config.marketplaceName) {
        Add-Problem "$relative declares marketplace name '$($marketplace.name)' but the contract says '$($config.marketplaceName)'."
    }
    $entryNames = @($marketplace.plugins | ForEach-Object { $_.name } | Sort-Object)
    if (Compare-Object $entryNames @($advertised | Sort-Object)) {
        Add-Problem "$relative advertises [$($entryNames -join ', ')] but the contract ships [$($advertised -join ', ')]."
    }
    foreach ($entry in $marketplace.plugins) {
        if ($entry.PSObject.Properties.Name -contains 'version') {
            Add-Problem "$relative entry '$($entry.name)' restates a version; the plugin manifest is the only source of truth."
        }
        $source = if ($entry.source -is [string]) { $entry.source } else { $entry.source.path }
        if (-not $source) { Add-Problem "$relative entry '$($entry.name)' has no source."; continue }
        $resolved = Join-Path $RepoRoot ($source -replace '^\./', '')
        if (-not (Test-Path -LiteralPath $resolved)) {
            Add-Problem "$relative entry '$($entry.name)' points at a missing source: $source"
        }
    }
}

# ------------------------------------------------------------------- manifests
# One kit, one version. Hosts read different manifests; a user comparing them
# must not find two answers.
$versions = @{}
foreach ($profile in $advertised) {
    $profileDir = Join-Path $RepoRoot "plugins/$profile"
    if (-not (Test-Path -LiteralPath $profileDir)) { Add-Problem "Advertised profile has no directory: plugins/$profile"; continue }

    foreach ($manifestDir in @('.claude-plugin', '.codex-plugin')) {
        $manifestPath = Join-Path $profileDir "$manifestDir/plugin.json"
        if (-not (Test-Path -LiteralPath $manifestPath)) {
            if ($manifestDir -eq '.claude-plugin') { Add-Problem "Missing required manifest: plugins/$profile/$manifestDir/plugin.json" }
            continue
        }
        $manifest = Read-Json $manifestPath
        if ($manifest.name -ne $profile) {
            Add-Problem "plugins/$profile/$manifestDir/plugin.json declares name '$($manifest.name)'."
        }
        if (-not $manifest.repository) {
            Add-Problem "plugins/$profile/$manifestDir/plugin.json is missing the repository field."
        }
        if ($manifest.PSObject.Properties.Name -contains 'hooks') {
            Add-Problem "plugins/$profile/$manifestDir/plugin.json declares hooks; opt-in hook packs must stay inert."
        }
        $versions["$profile/$manifestDir"] = $manifest.version
    }

    # An install from the repository must find its own activation guide. The
    # installer-rendered copy does not exist on a marketplace or clone install.
    $applyPath = Join-Path $profileDir 'instructions/APPLY_TO_YOUR_AI.txt'
    if (-not (Test-Path -LiteralPath $applyPath)) {
        Add-Problem "plugins/$profile has no instructions/APPLY_TO_YOUR_AI.txt; a repository install has no activation guide."
    }
}
$distinct = @($versions.Values | Sort-Object -Unique)
if ($distinct.Count -gt 1) {
    $detail = ($versions.GetEnumerator() | Sort-Object Name | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ', '
    Add-Problem "All plugin manifests must advertise one kit version but found: $detail"
}

# ---------------------------------------------------------------------- skills
foreach ($profile in $advertised) {
    $spec = $config.profiles.$profile
    $skillsDir = Join-Path $RepoRoot "plugins/$profile/skills"
    if (-not (Test-Path -LiteralPath $skillsDir)) { Add-Problem "plugins/$profile has no skills directory."; continue }
    $skills = @(Get-ChildItem -LiteralPath $skillsDir -Directory)
    if ($spec -and $spec.skills -and $skills.Count -ne $spec.skills) {
        Add-Problem "plugins/$profile has $($skills.Count) skills but the contract declares $($spec.skills)."
    }
    foreach ($skill in $skills) {
        $skillFile = Join-Path $skill.FullName 'SKILL.md'
        if (-not (Test-Path -LiteralPath $skillFile)) { Add-Problem "plugins/$profile/skills/$($skill.Name) has no SKILL.md."; continue }
        $text = Get-Content -LiteralPath $skillFile -Raw
        if (-not $text.StartsWith('---')) { Add-Problem "$profile/$($skill.Name)/SKILL.md does not open with frontmatter." }
        if ($text -notmatch '(?m)^name:\s*\S') { Add-Problem "$profile/$($skill.Name)/SKILL.md frontmatter has no name." }
        if ($text -notmatch '(?m)^description:\s*\S') { Add-Problem "$profile/$($skill.Name)/SKILL.md frontmatter has no description." }
        if ($text -match '\[TODO:') { Add-Problem "$profile/$($skill.Name)/SKILL.md still contains a TODO marker." }
        # Codex resolves a skill through agents/openai.yaml; without it the skill
        # is silently invisible on that host while looking fine on Claude.
        $agentManifest = Join-Path $skill.FullName 'agents/openai.yaml'
        if (-not (Test-Path -LiteralPath $agentManifest)) {
            Add-Problem "$profile/$($skill.Name) has no agents/openai.yaml; Codex will not see this skill."
        }
    }
}

# ---------------------------------------------------------------- profile parity
# Profiles that ship the same skill pack must ship it byte-for-byte, including
# reference documents - a divergence there is invisible until a user compares.
foreach ($group in @($config.parityGroups)) {
    $members = @($group)
    if ($members.Count -lt 2) { continue }
    $reference = $members[0]
    $referenceRoot = Join-Path $RepoRoot "plugins/$reference/skills"
    if (-not (Test-Path -LiteralPath $referenceRoot)) { continue }
    $referenceFiles = @(Get-ChildItem -LiteralPath $referenceRoot -Recurse -File -Include '*.md')
    foreach ($other in $members[1..($members.Count - 1)]) {
        foreach ($file in $referenceFiles) {
            $relative = $file.FullName.Substring($referenceRoot.Length).TrimStart('\', '/')
            $counterpart = Join-Path (Join-Path $RepoRoot "plugins/$other/skills") $relative
            if (-not (Test-Path -LiteralPath $counterpart)) {
                Add-Problem "Parity break: $reference/skills/$relative has no counterpart in $other."
                continue
            }
            if ((Get-FileHash -LiteralPath $file.FullName).Hash -ne (Get-FileHash -LiteralPath $counterpart).Hash) {
                Add-Problem "Parity break: $relative differs between $reference and $other."
            }
        }
    }
}

# ----------------------------------------------------------------- MCP wiring
foreach ($profile in $advertised) {
    $spec = $config.profiles.$profile
    $mcpPath = Join-Path $RepoRoot "plugins/$profile/.mcp.json"
    $expected = $spec -and $spec.mcp
    if ($expected -and -not (Test-Path -LiteralPath $mcpPath)) {
        Add-Problem "plugins/$profile declares mcp=true but has no .mcp.json."
    }
    if (-not $expected -and (Test-Path -LiteralPath $mcpPath)) {
        Add-Problem "plugins/$profile has a .mcp.json but the contract says it registers no server (double-spawn risk)."
    }
    if (Test-Path -LiteralPath $mcpPath) { $null = Read-Json $mcpPath }
}

# --------------------------------------------------------------- opt-in hooks
foreach ($profile in $advertised) {
    $spec = $config.profiles.$profile
    $hosts = @()
    if ($spec -and $spec.hookHosts) { $hosts = @($spec.hookHosts) }
    $optInDir = Join-Path $RepoRoot "plugins/$profile/hooks/opt-in"

    if ($hosts.Count -eq 0) {
        if (Test-Path -LiteralPath $optInDir) {
            Add-Problem "plugins/$profile declares no hook hosts but ships hooks/opt-in; a skills-only profile must contain no hook code."
        }
        continue
    }
    if (-not (Test-Path -LiteralPath $optInDir)) { Add-Problem "plugins/$profile declares hook hosts but has no hooks/opt-in."; continue }

    $fragments = @(Get-ChildItem -LiteralPath $optInDir -File -Filter '*hooks.fragment.json')
    $found = @($fragments.Name | ForEach-Object { $_ -replace '-hooks\.fragment\.json$', '' } | Sort-Object)
    if (Compare-Object $found @($hosts | Sort-Object)) {
        Add-Problem "plugins/$profile ships fragments for [$($found -join ', ')] but the contract declares [$($hosts -join ', ')]."
    }
    foreach ($fragment in $fragments) {
        $raw = Get-Content -LiteralPath $fragment.FullName -Raw
        $null = $raw | ConvertFrom-Json
        # One portable token across every repo, so the inertness rule is one rule.
        if ($raw -notmatch '__PLUGIN_ROOT__') {
            Add-Problem "plugins/$profile/hooks/opt-in/$($fragment.Name) does not use the __PLUGIN_ROOT__ placeholder; a rendered path must never be committed."
        }
        # The Windows py launcher is not present on every host that can run hooks.
        if ($raw -match 'py\s+-3') {
            Add-Problem "plugins/$profile/hooks/opt-in/$($fragment.Name) invokes the py launcher; use python for portability."
        }
        $hostName = $fragment.Name -replace '-hooks\.fragment\.json$', ''
        $adapter = Join-Path $optInDir "adapters/$hostName/hook_adapter.py"
        if (-not (Test-Path -LiteralPath $adapter)) {
            Add-Problem "Fragment $($fragment.Name) has no adapter at adapters/$hostName/hook_adapter.py."
        }
    }

    # Rendered output bakes this machine's absolute paths. It must be impossible
    # to commit, not merely absent today.
    $probe = "plugins/$profile/rendered-hooks/probe.json"
    $null = & git -C $RepoRoot check-ignore $probe 2>$null
    if ($LASTEXITCODE -ne 0) {
        Add-Problem "$probe is not gitignored; rendered hook JSON carries machine-local absolute paths."
    }
}

# ------------------------------------------------------ hook scripts compile
$hookScripts = @(Get-ChildItem -LiteralPath (Join-Path $RepoRoot 'plugins') -Recurse -File -Filter '*.py' -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch '__pycache__' })
if ($hookScripts.Count -gt 0) {
    $python = (Get-Command python -ErrorAction SilentlyContinue)
    if ($python) {
        foreach ($script in $hookScripts) {
            & $python.Source -m py_compile $script.FullName 2>$null
            if ($LASTEXITCODE -ne 0) { Add-Problem "Hook script does not compile: $($script.FullName.Substring($RepoRoot.Length))" }
        }
    }
}

# ------------------------------------------------- retired capability vocabulary
# Trigger text is routing, not prose: a description that still advertises a moved
# capability sends the model to a server that cannot do the job. Checked ONLY in
# advertising and trigger fields - body paragraphs must stay free to explain where
# a capability went, which is the opposite of a defect.
# A repo that declares none must get an EMPTY list, not @($null) - an empty
# regex matches every string, which would fail every advertising field.
$retired = @($config.retiredCapabilityTerms | Where-Object { $_ -is [string] -and $_.Trim() })
if ($retired.Count -gt 0) {
    function Test-Advertised([string] $text, [string] $where) {
        if (-not $text) { return }
        foreach ($term in $retired) {
            if ($text -match [regex]::Escape($term)) {
                Add-Problem "$where advertises retired capability '$term'; trigger text routes the model, so a stale term sends it to a server that cannot do the job."
            }
        }
    }
    foreach ($profile in $advertised) {
        foreach ($manifestDir in @(".claude-plugin", ".codex-plugin")) {
            $manifestPath = Join-Path $RepoRoot "plugins/$profile/$manifestDir/plugin.json"
            if (-not (Test-Path -LiteralPath $manifestPath)) { continue }
            $manifest = Read-Json $manifestPath
            Test-Advertised $manifest.description "plugins/$profile/$manifestDir/plugin.json description"
            if ($manifest.interface) {
                Test-Advertised $manifest.interface.longDescription "plugins/$profile/$manifestDir/plugin.json longDescription"
                Test-Advertised $manifest.interface.shortDescription "plugins/$profile/$manifestDir/plugin.json shortDescription"
                foreach ($capability in @($manifest.interface.capabilities)) {
                    Test-Advertised $capability "plugins/$profile/$manifestDir/plugin.json capabilities"
                }
            }
        }
        $skillsDir = Join-Path $RepoRoot "plugins/$profile/skills"
        if (-not (Test-Path -LiteralPath $skillsDir)) { continue }
        foreach ($skill in Get-ChildItem -LiteralPath $skillsDir -Directory) {
            $skillFile = Join-Path $skill.FullName "SKILL.md"
            if (Test-Path -LiteralPath $skillFile) {
                # frontmatter only: everything between the opening and closing ---
                $raw = Get-Content -LiteralPath $skillFile -Raw
                $parts = $raw -split "(?m)^---\s*$", 3
                if ($parts.Count -ge 2) { Test-Advertised $parts[1] "$profile/$($skill.Name)/SKILL.md frontmatter" }
            }
            $agentFile = Join-Path $skill.FullName "agents/openai.yaml"
            if (Test-Path -LiteralPath $agentFile) {
                Test-Advertised (Get-Content -LiteralPath $agentFile -Raw) "$profile/$($skill.Name)/agents/openai.yaml"
            }
        }
    }
}
# --------------------------------------------------------------- emoji policy
# Downstream tools that read and rewrite these files can emoji-bake; keep the
# packaged surface plain.
foreach ($file in Get-ChildItem -LiteralPath (Join-Path $RepoRoot 'plugins') -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension -in '.md', '.py', '.ps1', '.json', '.yml', '.yaml', '.txt' }) {
    if ((Get-Content -LiteralPath $file.FullName -Raw) -match '[\uD83C-\uDBFF][\uDC00-\uDFFF]') {
        Add-Problem "Emoji or supplementary glyph in packaged file: $($file.FullName.Substring($RepoRoot.Length))"
    }
}

# ----------------------------------------------------------------------- report
if ($problems.Count -gt 0) {
    Write-Host "Plugin package contract FAILED with $($problems.Count) problem(s):" -ForegroundColor Red
    foreach ($problem in $problems) { Write-Host "  - $problem" }
    exit 1
}
Write-Host "Plugin package contract passed: marketplaces, manifests, skills, Codex manifests, profile parity, MCP wiring, opt-in hook census, rendered-output containment, and emoji policy."
