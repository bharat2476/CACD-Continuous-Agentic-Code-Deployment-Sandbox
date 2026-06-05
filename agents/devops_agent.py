#!/usr/bin/env python3
"""
Multi-Agent Pull Request Reviewer for CA/CD sandbox.

Runs two specialized agents against a Git diff:
  1. Architect Agent — structural integrity, state conflicts, overwrite risk
  2. Security/Test Agent — security flaws and test coverage gaps

Synthesizes findings and posts a structured markdown report to the active PR.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv
from github import Github
from github.GithubException import GithubException

load_dotenv()

ARCHITECT_SYSTEM = """You are a Principal Software Architect reviewing a pull request diff.
Focus exclusively on:
- Structural integrity and module boundaries
- Database migrations, shared state, or config that could conflict with concurrent features
- Patterns that risk overwriting another developer's in-flight work (wide refactors, global renames, shared file churn)
- Trunk-based development violations (large unrelated changes bundled together)

Be concise. Use bullet points. Rate overall structural risk: LOW, MEDIUM, or HIGH."""

SECURITY_SYSTEM = """You are a Senior Application Security Engineer and QA lead reviewing a pull request diff.
Focus exclusively on:
- OWASP-style vulnerabilities (injection, XSS, secrets in code, unsafe eval, missing auth)
- Dependency or configuration security issues visible in the diff
- Missing or inadequate unit/integration tests for changed behavior
- Test anti-patterns (skipped assertions, commented-out tests)

Be concise. Use bullet points. Rate security/test posture: PASS, WARN, or FAIL."""

SYNTHESIS_SYSTEM = """You are a DevOps release manager synthesizing two PR review reports.
Produce a short executive summary (3-5 sentences), a merged risk table, and clear merge recommendation:
APPROVE, REQUEST_CHANGES, or BLOCK — with one-line justification each for architect and security findings."""


@dataclass
class ReviewContext:
    repo_full_name: str
    pr_number: int
    base_ref: str
    head_ref: str
    diff_text: str
    token: str


def run_git(args: list[str], cwd: Optional[Path] = None) -> str:
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=cwd or Path.cwd(),
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def fetch_diff(base: str, head: str) -> str:
    if os.environ.get("PR_DIFF_FILE"):
        path = Path(os.environ["PR_DIFF_FILE"])
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")

    try:
        return run_git(["diff", f"{base}...{head}", "--no-color", "-U3"])
    except RuntimeError:
        return run_git(["diff", "HEAD~1", "HEAD", "--no-color", "-U3"])


def truncate_diff(diff: str, max_chars: int = 48000) -> str:
    if len(diff) <= max_chars:
        return diff
    half = max_chars // 2
    return (
        diff[:half]
        + f"\n\n... [diff truncated — {len(diff) - max_chars} chars omitted] ...\n\n"
        + diff[-half:]
    )


def call_openrouter(
    system_prompt: str,
    user_prompt: str,
    model: str,
    api_key: str,
    temperature: float = 0.2,
) -> str:
    url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1/chat/completions")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.environ.get("OPENROUTER_HTTP_REFERER", "https://github.com/cacd-sandbox"),
        "X-Title": "CA/CD Multi-Agent PR Reviewer",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": int(os.environ.get("OPENROUTER_MAX_TOKENS", "2048")),
    }
    response = requests.post(url, headers=headers, json=payload, timeout=120)
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"].strip()


def run_crewai_agents(diff: str, model: str, api_key: str) -> tuple[str, str]:
    """Run Architect and Security agents via CrewAI when available."""
    from crewai import Agent, Crew, LLM, Process, Task

    llm = LLM(
        model=f"openrouter/{model}",
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        temperature=0.2,
        max_tokens=2048,
    )

    architect = Agent(
        role="Principal Architect",
        goal="Detect structural and concurrent-work overwrite risks in the diff",
        backstory="Expert in trunk-based development and safe incremental delivery.",
        llm=llm,
        verbose=False,
        allow_delegation=False,
    )
    security = Agent(
        role="Security & Test Lead",
        goal="Find security issues and test gaps in the diff",
        backstory="OWASP practitioner who insists on test coverage for changed code.",
        llm=llm,
        verbose=False,
        allow_delegation=False,
    )

    architect_task = Task(
        description=f"Review this Git diff:\n\n```diff\n{diff}\n```",
        expected_output="Bullet findings and structural risk rating LOW/MEDIUM/HIGH",
        agent=architect,
    )
    security_task = Task(
        description=f"Review this Git diff:\n\n```diff\n{diff}\n```",
        expected_output="Bullet findings and security/test rating PASS/WARN/FAIL",
        agent=security,
    )

    crew = Crew(
        agents=[architect, security],
        tasks=[architect_task, security_task],
        process=Process.sequential,
        verbose=False,
    )
    results = crew.kickoff()
    if hasattr(results, "tasks_output") and len(results.tasks_output) >= 2:
        return str(results.tasks_output[0]), str(results.tasks_output[1])
    raw = str(results)
    parts = raw.split("Security", 1)
    if len(parts) == 2:
        return parts[0].strip(), ("Security" + parts[1]).strip()
    midpoint = len(raw) // 2
    return raw[:midpoint].strip(), raw[midpoint:].strip()


def run_direct_agents(diff: str, model: str, api_key: str) -> tuple[str, str]:
    user = f"Analyze the following pull request diff:\n\n```diff\n{diff}\n```"
    architect = call_openrouter(ARCHITECT_SYSTEM, user, model, api_key)
    security = call_openrouter(SECURITY_SYSTEM, user, model, api_key)
    return architect, security


def heuristic_architect_review(diff: str) -> str:
    findings: list[str] = []
    risk = "LOW"
    files = re.findall(r"^\+\+\+ b/(.*)$", diff, re.MULTILINE)
    if len(set(files)) > 25:
        findings.append(f"Large blast radius: {len(set(files))} files touched — elevated overwrite/conflict risk.")
        risk = "HIGH"
    if re.search(r"package-lock\.json|yarn\.lock|pnpm-lock", diff):
        findings.append("Lockfile changes detected — coordinate with other active branches to avoid dependency drift.")
        risk = "MEDIUM" if risk == "LOW" else risk
    if re.search(r"migration|schema\.sql|ALTER TABLE", diff, re.I):
        findings.append("Database/schema changes present — verify no concurrent migration on main.")
        risk = "HIGH"
    if re.search(r"^rename from", diff, re.MULTILINE):
        findings.append("File renames detected — may conflict with parallel edits to old paths.")
        risk = "MEDIUM" if risk == "LOW" else risk
    if not findings:
        findings.append("No high-risk structural patterns detected in diff heuristics.")
    bullets = "\n".join(f"- {f}" for f in findings)
    return f"{bullets}\n\n**Structural risk:** {risk}"


def heuristic_security_review(diff: str) -> str:
    findings: list[str] = []
    rating = "PASS"
    patterns = [
        (r"eval\s*\(", "Use of eval() — code injection risk.", "FAIL"),
        (r"child_process\.exec\s*\(", "Shell execution via exec — command injection risk.", "FAIL"),
        (r"(api[_-]?key|secret|password)\s*=\s*['\"][^'\"]+['\"]", "Possible hardcoded secret.", "FAIL"),
        (r"\.only\s*\(|describe\.only|it\.only", "Focused/disabled test scope (.only) — remove before merge.", "WARN"),
        (r"console\.log\s*\(", "Debug logging left in production paths.", "WARN"),
    ]
    for pattern, message, severity in patterns:
        if re.search(pattern, diff, re.I):
            findings.append(message)
            if severity == "FAIL":
                rating = "FAIL"
            elif severity == "WARN" and rating == "PASS":
                rating = "WARN"
    test_files = [f for f in re.findall(r"^\+\+\+ b/(.*)$", diff, re.MULTILINE) if "test" in f.lower()]
    code_files = [
        f
        for f in re.findall(r"^\+\+\+ b/(.*)$", diff, re.MULTILINE)
        if f.endswith((".js", ".ts", ".py")) and "test" not in f.lower()
    ]
    if code_files and not test_files:
        findings.append("Application code changed without accompanying test file changes.")
        if rating == "PASS":
            rating = "WARN"
    if not findings:
        findings.append("No critical security patterns flagged by static heuristics.")
    bullets = "\n".join(f"- {f}" for f in findings)
    return f"{bullets}\n\n**Security/test rating:** {rating}"


def synthesize_reports(
    architect: str,
    security: str,
    model: Optional[str],
    api_key: Optional[str],
) -> str:
    combined = f"## Architect Agent\n{architect}\n\n## Security/Test Agent\n{security}"
    if model and api_key:
        try:
            return call_openrouter(
                SYNTHESIS_SYSTEM,
                f"Synthesize these two reports:\n\n{combined}",
                model,
                api_key,
            )
        except requests.RequestException:
            pass
    arch_high = "HIGH" in architect.upper()
    sec_fail = "FAIL" in security.upper()
    if arch_high or sec_fail:
        rec = "BLOCK"
    elif "WARN" in security.upper() or "MEDIUM" in architect.upper():
        rec = "REQUEST_CHANGES"
    else:
        rec = "APPROVE"
    return (
        f"**Executive summary:** Architect and security reviews completed. "
        f"Structural concerns: {'elevated' if arch_high else 'acceptable'}. "
        f"Security posture: {'failing' if sec_fail else 'acceptable'}.\n\n"
        f"**Merge recommendation:** `{rec}`"
    )


def build_markdown_report(
    ctx: ReviewContext,
    architect: str,
    security: str,
    synthesis: str,
    engine: str,
) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"""## 🤖 CA/CD Multi-Agent PR Review

| Field | Value |
|-------|-------|
| **Repository** | `{ctx.repo_full_name}` |
| **Pull Request** | #{ctx.pr_number} |
| **Base → Head** | `{ctx.base_ref}` → `{ctx.head_ref}` |
| **Review engine** | {engine} |
| **Generated** | {ts} |

---

### 🏛️ Architect Agent — Structural & Overwrite Risk

{architect}

---

### 🛡️ Security & Test Agent

{security}

---

### 📋 Synthesis & Merge Guidance

{synthesis}

---

<sub>Powered by [CA/CD Sandbox](https://github.com) — Continuous Agentic Deployment</sub>
"""


def find_existing_bot_comment(github: Github, repo_name: str, pr_number: int, marker: str):
    repo = github.get_repo(repo_name)
    pr = repo.get_pull(pr_number)
    for comment in pr.get_issue_comments():
        if marker in (comment.body or ""):
            return comment
    return None


def post_pr_comment(ctx: ReviewContext, body: str) -> None:
    marker = "CA/CD Multi-Agent PR Review"
    gh = Github(ctx.token)
    existing = find_existing_bot_comment(gh, ctx.repo_full_name, ctx.pr_number, marker)
    if existing:
        existing.edit(body)
        print(f"Updated existing PR comment on #{ctx.pr_number}")
    else:
        repo = gh.get_repo(ctx.repo_full_name)
        pr = repo.get_pull(ctx.pr_number)
        pr.create_issue_comment(body)
        print(f"Posted new PR comment on #{ctx.pr_number}")


def resolve_context(args: argparse.Namespace, dry_run: bool = False) -> ReviewContext:
    token = args.token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    if not token and not dry_run:
        raise SystemExit("GITHUB_TOKEN (or --token) is required to post PR comments.")

    repo = args.repo or os.environ.get("GITHUB_REPOSITORY")
    pr_number = args.pr_number or int(os.environ.get("PR_NUMBER", "0") or "0")

    if dry_run:
        repo = repo or "local/cacd-sandbox"
        pr_number = pr_number or 1
    else:
        if not repo or not pr_number:
            raise SystemExit(
                "GITHUB_REPOSITORY and PR_NUMBER (or --repo / --pr-number) are required."
            )

    base = args.base or os.environ.get("GITHUB_BASE_REF", "main")
    head = args.head or os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_SHA", "HEAD")

    if args.diff_file:
        diff = Path(args.diff_file).read_text(encoding="utf-8", errors="replace")
    else:
        subprocess.run(["git", "fetch", "origin", base, "--depth=1"], check=False)
        diff = fetch_diff(f"origin/{base}", head)

    if not diff.strip():
        diff = "# Empty diff\nNo file changes detected between base and head."

    return ReviewContext(
        repo_full_name=repo,
        pr_number=pr_number,
        base_ref=base,
        head_ref=head,
        diff_text=truncate_diff(diff),
        token=token,
    )


def run_review(ctx: ReviewContext, dry_run: bool = False) -> str:
    model = os.environ.get(
        "OPENROUTER_MODEL",
        "qwen/qwen-2.5-coder-32b-instruct",
    )
    api_key = os.environ.get("OPENROUTER_API_KEY")
    engine = "heuristic"

    if api_key:
        try:
            architect, security = run_crewai_agents(ctx.diff_text, model, api_key)
            engine = f"CrewAI + OpenRouter (`{model}`)"
        except Exception as crew_err:
            print(f"CrewAI path unavailable ({crew_err}); falling back to direct OpenRouter.", file=sys.stderr)
            try:
                architect, security = run_direct_agents(ctx.diff_text, model, api_key)
                engine = f"OpenRouter direct (`{model}`)"
            except requests.RequestException as req_err:
                print(f"OpenRouter failed ({req_err}); using heuristics.", file=sys.stderr)
                architect = heuristic_architect_review(ctx.diff_text)
                security = heuristic_security_review(ctx.diff_text)
    else:
        print("OPENROUTER_API_KEY not set — running deterministic heuristic review.", file=sys.stderr)
        architect = heuristic_architect_review(ctx.diff_text)
        security = heuristic_security_review(ctx.diff_text)

    synthesis = synthesize_reports(architect, security, model if api_key else None, api_key)
    report = build_markdown_report(ctx, architect, security, synthesis, engine)

    if dry_run:
        print(report)
        return report

    try:
        post_pr_comment(ctx, report)
    except GithubException as exc:
        raise SystemExit(f"Failed to post GitHub comment: {exc}") from exc

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="CA/CD Multi-Agent PR Reviewer")
    parser.add_argument("--repo", help="owner/repo (default: GITHUB_REPOSITORY)")
    parser.add_argument("--pr-number", type=int, help="Pull request number (default: PR_NUMBER)")
    parser.add_argument("--base", default="main", help="Base branch name")
    parser.add_argument("--head", help="Head ref or SHA")
    parser.add_argument("--diff-file", help="Path to precomputed diff file")
    parser.add_argument("--token", help="GitHub token (default: GITHUB_TOKEN)")
    parser.add_argument("--dry-run", action="store_true", help="Print report without posting")
    args = parser.parse_args()

    ctx = resolve_context(args, dry_run=args.dry_run)
    run_review(ctx, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
