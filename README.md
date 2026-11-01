# RepoBrain

**The safety layer that sees what your AI agents do, and asks before it merges.**
One policy file. One audit trail. Any AI. *(CodeQuest 2026 · Team Craduo: Tanmay Jain, Saanchi Jain)*

![RepoBrain hero: a particle brain in lavender and lime, with giant pixel type behind it](docs/screenshots/01-hero.png)

RepoBrain does **not** write code. It sits on top of a repository and does four things for *every* contributor, human or AI (Copilot, Codex, Claude, or your own bot):

| Module | What it does | What makes it different |
|---|---|---|
| **Shield** | Checks every change against `repobrain.yml` | Protected paths, 8 secret formats + entropy, prompt-injection (rules **and** a learned guard), hidden-Unicode / *Trojan Source*, risky commands, dependency typosquats. Findings carry line numbers and **redacted** evidence |
| **Optimizer** | Simplifies code and proves it is safe | Rewrites are spliced **per function** (untouched code stays byte-identical, comments are never deleted), then must pass the project's tests **and** a **differential fuzzer** that compares old vs new on generated inputs |
| **Failure Explainer** | Turns a build log into cause + fix | Proposes a concrete patch (e.g. the right PyPI name) and warns when a "missing package" looks like an AI-hallucinated typosquat |
| **Audit** | Tamper-evident record of every decision | SHA-256 hash chain, optional HMAC signing, approval **pinned to a commit** (a new commit, even by an AI, invalidates it), exports to SARIF / Markdown / CSV / HTML |

Plus an **Agent Preflight API**: any agent asks `POST /api/preflight` *before* writing a file and gets allow / warn / block, logged to the same chain ([`examples/agent_guard.py`](examples/agent_guard.py), three lines).

## Run it (no API key, no pytest, no internet)

```bash
pip install -r requirements.txt     # only PyYAML
python -m repobrain serve           # opens the 3D console on a real demo repo
```

Prefer the terminal? `python -m repobrain demo --approve` runs the whole story. Press **Ctrl/⌘ K** in the console for every action, or **play autopilot demo** (footer) to run a scripted 40-second walkthrough, handy for recording your submission video.

## The console

A raw **WebGL2** particle scene (no libraries, works offline) is not decoration: it is the data. The brain's turbulence follows the repo's real cognitive complexity (approve the optimization and it visibly calms), a threat tint follows the verdict, and scrolling dives into the brain, dissolves it, and re-forms it as a **constellation where each changed file is a cluster coloured by its verdict**. Click a cluster to inspect the file, drag to rotate.

| | |
|---|---|
| ![constellation](docs/screenshots/03-constellation.png) | ![review](docs/screenshots/04-console-review.png) |
| ![optimizer proof](docs/screenshots/05-optimizer-proof.png) | ![audit tamper](docs/screenshots/07-audit-tamper.png) |
| ![preflight](docs/screenshots/06-agent-preflight.png) | ![model card](docs/screenshots/08-model-card.png) |

The demo repo is a real git history with an AI-authored PR. **Simulate an agent…** pushes new commits (lookalike packages, hidden Unicode, leaked credentials) and **Simulate tampering** edits a past audit record so you can watch the chain break at that exact record.

## Measured results (nothing here is aspirational)

| Claim | Evidence |
|---|---|
| Optimizer on the demo `orders.py` | nesting 4 → 3, cognitive complexity Σ 23 → 13, 34 → 19 lines; 4 project tests pass; **750 fuzz inputs, 0 divergences** |
| The fuzzer is not a rubber stamp | A "simplification" that changes `>=` to `>` is caught (tests in `tests/test_engine.py`); an AI-suggested off-by-one is rejected end-to-end (`tests/test_llm.py`, mock provider) |
| Learned injection guard | 5-fold CV on 72 attacks + 170 hard negatives: rules-only precision 1.00 / recall 0.25; **model precision 0.94 / recall 0.62**; hybrid recall 0.64. **0.03 % false positives** on 4,000 held-out real prose lines (Python stdlib). `python -m repobrain ml-eval` reproduces it |
| Test suite | 39 tests (engine, server security, ML claims, LLM verification) pass on the built-in runner, Python 3.12. The CI workflow is also configured to run them under pytest on 3.10 – 3.12; I could not run pytest in my build sandbox, so watch the first CI run |
| Dogfooding | `python -m repobrain shield` over this repo's own tree: clean |

## Honest limits

* **The ML is small by design.** The corpus is team-written (plus template-generated variants used for *training only*), so CV numbers show the approach works on this distribution, not that it generalises to production. **Design rule: rules can block, the model can only warn.** While building this we found it flagged ~40 lines of our own docs (it had learned that words like "AI" and "security" mean "attack"); the fixes (in-domain negatives, a directive-wording gate, evaluating exactly what ships) are in the history of `mlguard.py`.
* **Python only** for the Optimizer today. The fuzzer skips functions that are not pure-looking (I/O, imports, unknown names) and says so; those rely on tests alone.
* **Only what passes through RepoBrain is guarded** (CI, the pre-commit hook `python -m repobrain install-hook`, the preflight API). An agent that bypasses all three is out of scope.
* **We found our own hotspots.** RepoBrain's gate flags 33 of its 160 functions at the default policy (worst: `shield.scan_text`, `server.state`). This repo's policy therefore runs the complexity gate advisory (`optimize: off`) while Shield is enforced. Refactoring them is the first roadmap item.
* **The LLM path is verified with a mock server only.** No real provider was called during development; the safety property (AI output is verified like any other change) *is* tested. Without a key everything else is fully local.
* Scenarios *simulate* agent behaviour on a synthetic repo; they are not recordings of real Copilot/Codex runs.

## GitHub integration

* `.github/workflows/repobrain.yml`: on every PR runs `repobrain ci` → **SARIF to code scanning**, a **sticky PR comment**, a job summary, and fails the check on blocking findings.
* `action.yml`: reusable composite action (`uses: ./`) for other repositories.
* `.github/workflows/tests.yml`: pytest matrix + the dependency-free runner + dogfood scan.
* `python -m repobrain install-hook`: same scan on staged changes before every commit.

## Architecture

```mermaid
flowchart LR
  A[Developer or any AI agent] -->|push / PR / preflight| P[(repobrain.yml policy)]
  P --> S[Shield<br/>rules + learned guard + deps + unicode]
  P --> O[Optimizer<br/>AST rewrite → tests → differential fuzz]
  P --> E[Failure Explainer]
  S & O & E --> L[(Hash-chained audit log)]
  L --> H{Human approval<br/>pinned to commit}
  H --> M[Merge]
  L -.-> X[SARIF · PR comment · CSV · HTML]
```

Standard library + PyYAML only. Details in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Security model

The console is itself an attack surface, so: it binds to `127.0.0.1`, rejects non-local `Host` headers (DNS rebinding), requires a custom `X-RepoBrain` header on every POST (cross-site pages cannot send it), never takes the repo path from the client, serves only whitelisted static files, limits bodies, and redacts secrets before they reach the UI or the log. Each of these has a test in `tests/test_server.py`.

## How it differs from existing tools

Copilot/Codex write code; **CodeRabbit** reviews PRs; **SonarQube** gates on static rules; **Socket/Snyk** guard dependencies. RepoBrain is a vendor-neutral layer *above* them: one policy across every agent, one audit trail, and optimizations that carry machine-checked proof. It does not claim those tools lack controls, only that theirs are separate and tool-specific.

## AI-assistance disclosure *(required by the CodeQuest rules; edit to match what your team actually did)*

Parts of this codebase, including the engine, the WebGL scene and the UI, were developed with the help of an AI assistant (Claude) under the team's direction, then reviewed, run and tested by the team. The earlier prototype ideas (policy file, four-module structure) are the team's own. No third-party code or assets are bundled; the only runtime dependency is PyYAML; `repobrain/data/negative_prose.txt` is a sample of comment lines from the Python standard library (PSF licence).

## Repo map

```
repobrain/            engine: shield · deps · mlguard · optimizer · fuzz · explainer · audit · risk · export · server · cli
repobrain/web/        index.html · app.css · scene.js (WebGL2) · app.js
repobrain/data/       injection corpus + frozen negative prose
tests/                39 tests          demo/   messy.py + failing log
examples/             agent_guard.py    docs/   ARCHITECTURE · PITCH · screenshots
.github/              PR check (SARIF + comment) · tests · dependabot        action.yml
```

MIT licensed.
