# Git Workflow — Trunk-Based Development

This repository enforces **trunk-based development** with a single integration branch (`main`). All production-bound code flows through short-lived feature branches that merge back into `main` quickly.

## Branch model

| Branch | Purpose | Lifetime |
|--------|---------|----------|
| `main` | Single source of truth; always deployable to QA | Permanent |
| `feature/*` | One logical change per branch | 1–3 days max |
| `release/*` (optional) | Release preparation only when needed | Hours |

**Do not** use long-lived `develop`, per-developer integration branches, or environment branches (`qa`, `prod`) for source control. Environments are deployment *targets*, not Git branches.

## Anti-overwrite guardrails

Concurrent developers overwrite each other's work when:

1. Two branches diverge from different points on `main`
2. One merges first; the second merges without incorporating the first
3. Git auto-merges overlapping regions incorrectly

### Required practices

1. **Fetch and rebase before every push**
   ```bash
   git fetch origin main
   git rebase origin/main
   ```

2. **Keep PRs small** — under ~400 lines changed when possible.

3. **One concern per PR** — no drive-by refactors in feature PRs.

4. **Linear history on `main`** — squash merge or rebase merge only (no merge commits).

5. **Branch must be up-to-date** — CI fails if `HEAD` is behind `origin/main` (see `dev-to-qa.yml`).

## Standard developer flow

```bash
# Start from latest main
git checkout main
git pull origin main

# Create short-lived branch
git checkout -b feature/add-rate-limit

# Commit incrementally
git add -A && git commit -m "feat(api): add rate limit middleware"

# Stay current with main daily
git fetch origin main
git rebase origin/main

# Push and open PR to main
git push -u origin feature/add-rate-limit
```

## Merge requirements (enforced in CI + branch protection)

- All status checks pass (`Dev → QA Fast-Track`)
- PR is up-to-date with `main` (no behind commits)
- At least one approving review (configure in GitHub)
- Multi-agent PR review comment posted (informational + gate via checks)
- Linear history required

## Release flow (QA → Stage → Prod)

1. Merge PR to `main` after Dev→QA pipeline passes.
2. Create a GitHub **Release** with semantic tag `v*.*.*`.
3. `stage-to-prod.yml` validates tests, deploys to `stage`, then canary-promotes to `production`.
4. Failed canary or health check triggers `scripts/rollback.py`.

## Conflict resolution

If rebase reports conflicts:

```bash
# During rebase
git status                    # list conflicted files
# Edit files, resolve markers
git add <resolved-files>
git rebase --continue
```

Never force-push to `main`. Force-push to your feature branch only if you own it and no one else is stacked on it.
