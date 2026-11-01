# Submission kit

## Round 2: idea deck (≤ 10 slides)
1. **Problem**: AI agents now commit to real repos. Each vendor's controls are separate; companies can't answer "what did AI change, who allowed it, can we prove it?" Users: engineering leads, agencies handing AI-written code to clients, compliance teams.
2. **Solution**: RepoBrain = one policy file, one audit trail, any AI. (Hero screenshot.)
3. **USP & features**: Shield · Optimizer with proof · Failure Explainer · tamper-evident audit · Agent Preflight API.
4. **Demo moment**: AI PR blocked → learned guard catches a paraphrased injection → optimizer proof (tests + 750 fuzz inputs) → typosquats → tampered log breaks the chain.
5. **Tech stack**: Python stdlib + PyYAML; raw WebGL2; GitHub Actions + SARIF; optional Anthropic/OpenAI/Ollama.
6. **Architecture**: the mermaid diagram from the README.
7. **Novelty**: differential fuzzing as a safety net for AI refactors; approval pinned to a commit; rules-block/model-warns design; vendor-neutral preflight.
8. **Differentiation**: vs CodeRabbit (reviews) / SonarQube (static gate) / Socket (deps) / Copilot (writes). Be honest: "their controls are separate and tool-specific; we are the common layer."
9. **Feasibility & scalability**: already running; added-lines-only scanning; cached analysis; GitHub App + queue is the scale path; BYO key / local Ollama for privacy.
10. **Impact & roadmap**: refactor our own hotspots (we found them with our own tool), JS support, GitHub App, real agent connectors.
*Optional 2-min video:* use **play autopilot demo** (footer link) and narrate the on-screen captions.

## Round 3: deliverables checklist
- [x] Working prototype + GitHub repo + README (stack, setup)
- [x] GitHub tools: Actions PR check, SARIF code scanning, sticky PR comment, composite action, dependabot, PR template
- [x] Screenshots in `docs/screenshots/`
- [ ] **You:** record the demo video (autopilot), push to GitHub, enable Pages/hosting if you want a live link
- [ ] **You:** adapt the AI-disclosure paragraph in the README to what your team actually did

## 90-second live script
1. Open console → "An AI agent opened this PR. 98/100 risk, blocked." (click `ci.yml`, point at the constellation turning red)
2. `AGENTS.md` → "Rules missed this paraphrased injection; the learned guard flagged it. Rules can block, the model can only warn."
3. `orders.py` → "Simpler code, proven: tests pass, 750 fuzz inputs agree." **Approve optimization**: the brain calms.
4. **Simulate an agent → lookalike packages** → three typosquats caught.
5. Audit → **Simulate tampering** → "the chain breaks at record #0". Restore.
6. Agents tab → **Hidden instruction** → blocked before it was written.

## Hard questions
- *"Why not just prompt the model to be safe?"* A prompt is not enforceable or auditable; a policy file + signed log is.
- *"Can an agent bypass it?"* If it bypasses CI, the hook and the preflight API, yes, and we say so. Branch protection closes the loop.
- *"Is the ML good?"* Small, team-labelled corpus; we report precision/recall and false-positive rate and never let it block.
- *"Is the optimizer safe?"* Tests + differential fuzz, comments never deleted, nothing pushed without a human.
