# Branch Protection Configuration

Apply these settings to the `main` branch in GitHub: **Settings → Branches → Branch protection rules → Add rule**.

## Rule: `main`

### Basic protections

| Setting | Value | Rationale |
|---------|-------|-----------|
| **Require a pull request before merging** | ✅ Enabled | No direct pushes; all changes reviewed |
| **Required approvals** | `1` (increase to `2` for production orgs) | Human gate on top of agent review |
| **Dismiss stale pull request approvals** | ✅ Enabled | New commits invalidate prior approval |
| **Require review from Code Owners** | Optional | Enable if `CODEOWNERS` is added |

### Status checks

| Setting | Value |
|---------|-------|
| **Require status checks to pass** | ✅ Enabled |
| **Require branches to be up to date** | ✅ Enabled — **critical anti-overwrite control** |
| **Required checks** | `Enforce up-to-date with main`, `Jest + Multi-Agent PR Review` |

The **Require branches to be up to date before merging** option ensures GitHub will not merge until the PR branch contains all commits currently on `main`, combined with our CI job that verifies `git rev-list HEAD..origin/main` is empty.

### History and merge strategy

| Setting | Value | Rationale |
|---------|-------|-----------|
| **Require linear history** | ✅ Enabled | Prevents merge-commit diamonds that hide concurrent edits |
| **Allow squash merging** | ✅ Enabled (recommended default) | One commit per PR on trunk |
| **Allow merge commits** | ❌ Disabled | Breaks linear history |
| **Allow rebase merging** | ✅ Optional | Alternative to squash for clean commits |

### Additional safeguards

| Setting | Value |
|---------|-------|
| **Include administrators** | ✅ Recommended for sandbox; orgs may exempt break-glass admins |
| **Restrict who can push** | Optional — limit to CI bot + release managers |
| **Require signed commits** | Optional — recommended for compliance |
| **Lock branch** | Only during incident freeze |

## Environment protection (Stage / Production)

Configure under **Settings → Environments**:

### `stage`

- **Required reviewers:** 0–1 (team lead)
- **Wait timer:** 0 minutes
- **Deployment branches:** Selected — `main` or tags matching `v*`

### `production`

- **Required reviewers:** 1–2 (release managers)
- **Wait timer:** 5 minutes (optional soak)
- **Deployment branches:** Tags only (`v*.*.*`)
- **Prevent self-review:** ✅ Enabled

These gates pair with `.github/workflows/stage-to-prod.yml`, which uses `environment: stage` and `environment: production` jobs.

## Rulesets (GitHub Enterprise / public beta)

If using **Repository rulesets** instead of classic protection:

```yaml
# Conceptual ruleset — configure in GitHub UI
target: branch
branch: main
rules:
  - pull_request_required
  - required_status_checks:
      - "Enforce up-to-date with main"
      - "Jest + Multi-Agent PR Review"
  - linear_history_required
  - non_fast_forward_required  # blocks force-push
```

## Verification checklist

After enabling protection:

- [ ] Direct push to `main` is rejected
- [ ] PR behind `main` cannot merge (GitHub UI shows "Update branch")
- [ ] PR with failing Jest cannot merge
- [ ] Merge commit strategy is unavailable
- [ ] Release tag triggers production environment approval
