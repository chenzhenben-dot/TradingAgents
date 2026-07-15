# Upstream Sync Guide — `chenzhenben-dot/TradingAgents`

How to keep your fork in sync with [tauricresearch/tradingagents](https://github.com/tauricresearch/tradingagents)
without losing your `tradingagents_custom/` extensions.

## Repo layout

| Remote | URL | Purpose |
|---|---|---|
| `origin` | `https://github.com/tauricresearch/tradingagents.git` | The "default" remote from the original clone — points to upstream |
| `upstream` | `https://github.com/tauricresearch/tradingagents.git` | Alias for upstream (clearer naming) |
| `fork` | `https://github.com/chenzhenben-dot/TradingAgents.git` | **Your fork on GitHub** (your backup) |

## Branches

| Branch | Tracks | Purpose |
|---|---|---|
| `main` | upstream `main` | Mirrors upstream; do not commit here |
| `custom/v0.3.1-with-extensions` | upstream tag `v0.3.1` | Your fork's main branch with extensions; this is what gets pushed to `fork` |

## When upstream releases a new version (e.g. v0.3.2)

```bash
cd /private/tmp/TradingAgents

# 1. Fetch the new tag from upstream
git fetch upstream v0.3.2

# 2. Create a new branch for the new version
git checkout -b custom/v0.3.2-with-extensions v0.3.2

# 3. Re-apply the .gitignore changes (they get overwritten by tag checkout)
#    (only needed if upstream's .gitignore conflicts with yours)
git checkout custom/v0.3.1-with-extensions -- .gitignore tradingagents_custom/

# 4. Commit the merge
git add .gitignore tradingagents_custom/
git commit -m "Merge v0.3.1 extensions into v0.3.2"

# 5. Push to your fork
git push fork custom/v0.3.2-with-extensions
```

After this, you have:
- `custom/v0.3.1-with-extensions` (old, still works on v0.3.1)
- `custom/v0.3.2-with-extensions` (new, on v0.3.2)
- All `tradingagents_custom/` modules preserved

## If you want to discard upstream and roll back to pure upstream

```bash
# Delete the custom branch and start over
git checkout v0.3.1  # back to pure upstream tag
git branch -D custom/v0.3.1-with-extensions
```

## Disaster recovery — if `/private/tmp/TradingAgents/` gets wiped again

```bash
# 1. Clone your fork (which has the custom code)
git clone https://github.com/chenzhenben-dot/TradingAgents.git /private/tmp/TradingAgents
cd /private/tmp/TradingAgents
git checkout custom/v0.3.1-with-extensions

# 2. Re-add upstream remote
git remote add upstream https://github.com/tauricresearch/tradingagents.git

# 3. Reinstall
python3 -m pip install -e . --break-system-packages
```

That recovers **100% of the custom code** from GitHub. The only thing not recovered is `~/.tradingagents/` (portfolio, memory, reports) — back that up separately:

```bash
# Periodic backup of your data
tar czf /tmp/tradingagents-data-backup.tar.gz ~/.tradingagents/
```

## Daily workflow after this setup

When I run a framework analysis for you:
1. I run on `/private/tmp/TradingAgents/`
2. I commit any new custom code to `custom/v0.3.1-with-extensions`
3. I push to `fork` automatically (or you can)
4. The local clone stays in sync with the fork

If `/private/tmp/TradingAgents/` ever gets wiped:
1. Re-clone from `fork` (one command, full recovery)
2. Re-install (`pip install -e .`)
3. Restore data from `~/.tradingagents/` (if separately backed up)

## Quick reference

```bash
# Status
git status                          # what changed
git remote -v                        # what remotes are configured
git branch -vv                       # what branch tracks what

# Daily operations
git add tradingagents_custom/        # stage new custom files
git commit -m "Add new feature"      # commit
git push fork custom/v0.3.1-with-extensions   # push to your fork

# Sync from upstream
git fetch upstream v0.3.2
git checkout -b custom/v0.3.2-with-extensions v0.3.2
git checkout custom/v0.3.1-with-extensions -- tradingagents_custom/ .gitignore
git commit -m "Merge extensions into v0.3.2"
git push fork custom/v0.3.2-with-extensions
```
