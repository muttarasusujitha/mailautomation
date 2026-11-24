# Ollama TOC and lab planning validation

The Ollama TOC contract now requires model-authored deliverables, assessment
procedures, preparation, tools, prior skills and three distinct acceptance checks.
Generated checks retain their concrete inputs, expected results and evidence.
Known generic assessment text and repeated result/evidence pairs cannot pass the
quality gate. Technical accuracy still requires trainer review.

AI lab planning uses the configured `AI_PROVIDER` and `OLLAMA_MODEL`. Ollama lab
requests use native JSON schema output. Resource plans are checked against named
compute, managed Kubernetes, database and storage services; explicit individual
VM setups must cover the participant count. Control planes and workers must be
consistent, storage requests need a storage allocation, and active days must match
the TOC entry. The proposed self-hosted minikube/kind architecture uses Heavy VMs.
Template planning respects shared VMs and per-day setup overrides.
Fully local AI requests return zero cloud allocations without calling the model.
Cloud planning receives compact lab scope and a deterministic proposed resource
baseline, keeping assessment prose and review metadata out of its prompt.

These are consistency checks, not measurements of CPU, RAM or application load.
Invalid AI mappings use the existing template fallback. Explicit manual mappings
remain available for trainer-specified architectures. Provider pricing and quote
calculations continue through the existing pricing engine.

## Repeatable live benchmark

From the repository root, using the trainer-service Python dependencies:

```powershell
python microservices/tools/benchmark_ollama_planning.py --output benchmark.json
```

Optional arguments: `--model`, `--url`, `--timeout` and `--scenario` (invoice_csv,
containers, managed_kubernetes). The default URL targets local Ollama.
Use `--reuse-tocs previous-report.json` to rerun resource planning against the same
saved TOCs; reused outputs are identified in the report.

The benchmark generates one-day Python invoice validation, Docker healthcheck,
and shared AWS EKS rollout/rollback outlines for 12 participants. It records the
full TOC, quality results, resource mapping, elapsed time and failures. It does
not write to the application database, send mail, provision resources or fetch
prices. Its scenarios are authored regression fixtures; they are **not** a
trainer-approved reference dataset.

## Trainer review rubric

For each saved result, verify:

1. All requested topics and exclusions match the client brief.
2. Lab commands, fixtures and expected outputs work in the specified environment.
3. Normal, failure and transfer/repeatability checks test distinct behavior.
4. Prior skills and preparation are sufficient for the requested audience.
5. VM/cluster sharing, participant concurrency, machine capacity and resource
   lifetimes match an executed lab, including teardown and storage retention.
6. Every required paid service has a provider price and measured or agreed usage.

Record the reviewer, date, actual lab observations and corrections alongside the
benchmark report before treating any case as an approved reference. A structural
score of 100 does not establish technical correctness or billing accuracy.

## Local validation on 2026-09-29

- Automated checks: 168 tests passed across TOC, planning, pricing coverage and
  document/lab suites, plus 33 subtests. Two calculator integration tests were
  skipped because LibreOffice was unavailable in the host test environment.
- Live `qwen3:8b`: two of three one-day TOCs passed coverage checks. The Python
  outline used duplicate order IDs without explicitly covering the requested
  duplicate invoices topic; it remained blocked for regeneration/review. The
  prompt was subsequently tightened to preserve requested names and identifiers;
  that TOC prompt adjustment has not been live-benchmarked again.
- Resource replay using the same saved TOCs: local scope passed without a model
  call. Docker and EKS responses still supplied storage request counts with zero
  object storage; both were rejected and template fallback mappings recorded.
  Cloud resource replay took about 22 and 20 seconds respectively.
- These initial results verify rejection and fallback behavior, not technical
  accuracy or invoice accuracy. See the subsequent deployment results below.

## Follow-up fixes and local deployment

- Storage request counts now come from participant count multiplied by supplied
  per-participant daily usage assumptions. The model selects architecture; it
  does not estimate these arithmetic inputs. Non-storage days get zero counts.
  Counts remain per day so the cost engine applies duration exactly once.
- All three saved-TOC resource scenarios passed live with `qwen3:8b`, including
  Docker and EKS without template fallback. This resource replay used earlier
  saved TOCs and does not count as a fresh TOC benchmark.
- TOC generation has at most one correction attempt within the original total
  timeout. Empty/invalid output and coverage failures can trigger correction;
  remaining errors still block delivery. Attempts are recorded in the TOC.
- Correction attempts omit optional reference examples and restate exact client
  topic names. This addresses copying order IDs from a reference into an invoice
  validation brief without weakening coverage checks.
- Native-schema requests use temperature zero. Schema guidance remains in the
  prompt, following [Ollama structured-output guidance](https://docs.ollama.com/capabilities/structured-outputs).
- The local model temporarily returned empty schema results and repeated zeros
  even for a tiny plain-text request. Unloading and reloading the model restored
  a normal response. Empty-output errors now include completion/token metadata.
- Trainer and document services were patched locally, with source hashes and
  import checks verified, then restarted and confirmed healthy. The original
  files are saved in `tmp/ollama-planning-backup-20260929-215637` in the workspace.
  These are local container patches; rebuilding/recreating containers requires
  building the repository changes into the images.
- The subsequent reference-isolation correction passed 116 focused tests and
  33 subtests, and was deployed with both services healthy. Its deployment backup
  is `tmp/ollama-planning-backup-20260929-220341` in the workspace.
- The fresh invoice run after reference isolation exhausted the 300-second
  generation budget (about 303 seconds including setup). Its live TOC outcome
  remains unverified; do not treat the correction's regression-test pass as a
  successful live curriculum benchmark. The saved failure report is
  `outputs/ollama_invoice_benchmark_client_scope.json` in the workspace. The
  successful resource replay is `outputs/ollama_resource_benchmark_final.json`.
