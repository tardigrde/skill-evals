# Roadmap

Planned harness improvements, distilled from running real eval suites against side-effect-heavy skills. Ordered roughly by value-to-effort; items are independent unless noted.

## 1. Record a skill content hash in run artifacts

**What:** Hash the skill's content (SKILL.md plus bundled resources) at run time and record it in `run_meta.json` and `evals_meta.json`. `compare` warns when the hash differs between the iterations being compared.

**Why:** Iteration-vs-iteration deltas are only meaningful when exactly one thing changed. In practice, skill wording and run configuration (model, reasoning effort) often change between iterations, and the comparison silently mixes both effects — e.g. attributing an accuracy gain to a cheaper reasoning setting when it actually came from a skill edit. The model configuration is already recorded; the skill content is the missing half of reproducibility.

## 2. Side-effect tags on eval cases

**What:** An optional per-case field such as `side_effect_level: static | local-only | live-safe | live-external`, plus a way to run by tag (e.g. `--side-effect-level live-safe`).

**Why:** For skills with external side effects, the cheap and safe iteration order is: negative/no-side-effect cases first, one happy-path smoke next, full live suite last. Today that ordering is user discipline plus hand-maintained `--eval-id` lists. Tagging makes it a structural property of the suite: targeted safe runs become the default path, and a full live suite becomes a deliberate choice. Also gives reports a place to show which cases can create remote state.

## 3. "How to iterate cheaply" documentation

**What:** A README section laying out the recommended loop: `validate --eval-id` → targeted `run --eval-id` with budget guards → `status` → full suite only as a final gate. Include the decision tree: accuracy low → inspect evidence and patch the skill, rerun the one failing case; time high → lower reasoning effort or model; tokens high → targeted reruns and pre-run static checks; side-effect risk high → run safe cases first, verify cleanup between runs.

**Why:** The features for cheap iteration exist, but nothing teaches the workflow they were built for. Users who default to full-suite reruns either overspend or stop running evals.

## 4. Provider-neutral side-effect manifest and cleanup

**What:** A manifest format describing expected and recorded external side effects (branches, pull/merge requests) independent of the hosting provider, with cleanup, cleanup dry-run, and read-only cleanup-verify operating from the manifest. Provider adapters (GitHub, GitLab) implement the operations.

**Why:** Cleanup is currently GitHub-oriented; evals against other providers need hand-built teardown and verification scripts. Side-effect setup, grading, cleanup, and reporting should share one source of truth, and users need a read-only proof that remote state is clean before the next run.

## 5. Agent configuration variants as the comparison unit

**What:** Allow one run to evaluate the same agent under multiple configurations (model, reasoning effort), e.g. a repeatable `--agent-config` flag, with benchmark rows and deltas keyed by configuration rather than agent alone. A cross-run matrix view (case × configuration × pass rate × runtime × tokens × cost) aggregating over saved summaries belongs to the same theme.

**Why:** The real optimization space is agent × model × reasoning setting, not agent alone. Comparing two reasoning settings today takes two full invocations plus manual artifact diffing. This is the largest item here — it touches benchmark keys and artifact layout — so it should come after the items above.
