# Curriculum content quality pilots

Five authored module previews, not complete course rewrites. Timings are proposals; training assets and technical review remain required. Original reference content is retained in each dataset. These previews show stored curriculum content, not live AI output.

## Python

**Scenario:** A finance team receives a sales export whose invalid records must be isolated without silently losing valid orders.

**Topics:** csv.DictReader and explicit field conversion; Required fields and duplicate order IDs; ISO date validation and rejection reasons; Separate row validation from file I/O; Missing file versus invalid row handling; Regression tests for valid and rejected rows

**Prerequisites:** Python functions, lists, dictionaries and basic exception handling

**Lab:** Implement validate_sales(input_path, accepted_path, rejected_path). Read a supplied ten-row CSV; reject missing IDs, repeated IDs, impossible dates and negative amounts. Retain the first occurrence of a duplicate ID. Write accepted rows and rejected rows with row number and reason. Missing input must fail clearly without reporting success.

**Participant output:** validator.py, accepted.csv, rejected.csv and automated tests covering all four rejection rules and a missing input file

**Acceptance checks:** The ten-row fixture produces six accepted rows and four rejected rows with the expected reasons. Accepted amounts sum to 210.00. All input row numbers occur exactly once across the two outputs. A missing input raises a clear file error; a repeated run yields identical output.

**Delivery:**

- 25 minutes — Demonstration: Trace DictReader values and one rejected row. Evidence: Annotated record and rejection reason.
- 65 minutes — Guided lab: Implement parsing, validation and separate output files. Evidence: Six accepted records and four rejection records.
- 40 minutes — Independent exercise: Add missing-file and repeated-run tests. Evidence: Tests expose silent row loss or nondeterministic results.
- 20 minutes — Assessment: Run the fixture and reconcile counts and accepted total. Evidence: Reconciliation and passing checks.

**Preparation:** Provide ten rows: six valid amounts of 10, 20, 30, 40, 50 and 60; one missing ID, one duplicate of a valid ID, one date of 2026-02-30 and one negative amount; Use UTF-8 CSV columns order_id, order_date, amount; supply expected rejected row numbers separately

**Sources:** https://docs.python.org/3/library/csv.html, https://docs.python.org/3/library/unittest.html

## AWS Cloud Security, DevOps & SRE

**Scenario:** A candidate WAF rule matches both suspicious requests and a legitimate search request. The team must decide whether to promote it without blocking ordinary users.

**Topics:** Count-mode observation before rule promotion; Labelled benign and malicious request fixtures; Rule-match evidence and benign false positives; Rate-based rule aggregation and test limits; Promotion and rollback criteria; Bot Control, Shield and central policy scope as demonstrations

**Prerequisites:** Web ACL associations, HTTP requests and basic CloudWatch log navigation

**Lab:** Use a prepared training Web ACL in Count mode. Replay ten labelled requests containing eight benign cases and two suspicious cases against the isolated lab application. Capture the matched rule for each request, investigate the seeded benign false positive and adjust the candidate rule. Demonstrate rate-rule behaviour separately using a bounded trainer-controlled request run.

**Participant output:** Ten-row request/result matrix, before-and-after rule configuration, false-positive investigation and promotion/rollback decision

**Acceptance checks:** All ten request IDs have traceable results. Both suspicious fixtures still match the intended rule; none of the eight benign fixtures matches it after tuning. Record remaining coverage limits and a rollback condition. Count mode is not reported as having blocked a request.

**Delivery:**

- 35 minutes — Demonstration: Trace Count-mode matches and distinguish matches from blocks. Evidence: Annotated request log.
- 95 minutes — Guided lab: Run ten cases and investigate the false positive. Evidence: Baseline request/result matrix.
- 65 minutes — Independent exercise: Tune and rerun cases; observe bounded rate-rule demo. Evidence: Comparison matrix and tuning rationale.
- 45 minutes — Assessment: Defend promotion criteria and discuss optional central controls. Evidence: Decision with limitations and rollback conditions.

**Preparation:** Trainer-owned isolated application, Web ACL, logs and labelled request fixtures with expected matches; Prepare the false-positive rule and cap the separate rate test; do not use production traffic; Confirm account access and service availability; paid optional features may use recorded demonstrations

**Sources:** https://docs.aws.amazon.com/waf/latest/developerguide/web-acl-testing.html

## Training for Quality Engineers

**Scenario:** A checkout UI accepts invalid quantities and a shared test cart causes order-dependent failures. The team needs a repeatable test framework that exposes both defects.

**Topics:** PyTest fixtures and independent test data; Parameterised valid, invalid and boundary cases; Page objects and separation of assertions; Explicit browser waits and reliable selectors; Failure diagnostics and report interpretation; Cleanup and repeatable execution

**Prerequisites:** Basic Python functions, exceptions and HTTP concepts

**Lab:** Extend a supplied local shop and test skeleton. Create independent cart fixtures, page objects and parameterised quantity tests for -1, 0, 1, 5 and 6 under an allowed range of 1 to 5. Run against a seeded faulty build and a corrected build. Capture failure diagnostics and rerun in reverse case order.

**Participant output:** PyTest suite, cart fixtures, checkout page object, failure diagnostics and reports for faulty and corrected builds

**Acceptance checks:** The faulty build fails the designated invalid-quantity cases. The corrected build passes all five cases. Reversing execution order preserves results. Each failed case reports input, expected behaviour and observed behaviour; no fixed sleep is used as the only readiness check.

**Delivery:**

- 120 minutes — Demonstration: Inspect the starter and trace fixtures, selectors and assertions. Evidence: One isolated checkout test.
- 300 minutes — Guided lab: Build parameterised cases, page objects and failure diagnostics. Evidence: Executable suite and faulty-build report.
- 210 minutes — Independent exercise: Remove state leakage and test corrected build in reverse order. Evidence: Stable comparison reports.
- 90 minutes — Assessment: Explain every seeded failure and demonstrate cleanup. Evidence: Reviewed framework and evidence.

**Preparation:** Provide local faulty and corrected shop builds, browser driver, stable test selectors and a starter repository; Supply the 1-to-5 quantity rule and expected behaviour; reserve Python introduction as prerequisite remediation rather than silently consuming lab time

**Sources:** https://pytest.org/en/stable/how-to/parametrize.html

## Enterprise AI Readiness (GenAI for BI Capstone Track)

**Scenario:** An AI-generated sales model joins product tags directly to order lines, doubling the value of one order. The team must describe a semantic model that prevents the error.

**Topics:** Fact grain versus dimension attributes; Unique keys and one-to-many relationships; Fan-out and double-counted measures; Business glossary and schema metadata; AI-readable schema with explicit unknowns

**Prerequisites:** Power BI or Tableau relationships and basic sales measures

**Lab:** Use three order lines worth 100, 60 and 40 and a product-tag table that duplicates the first line under a naive join. Inspect the resulting 300 total against the correct 200 baseline. Create a grain and relationship map and a JSON metadata description with table keys, relationship cardinalities, measure definitions and unresolved questions. Review an intentionally incorrect AI-produced schema.

**Participant output:** Relationship diagram, JSON schema description and reconciliation of 300 incorrect versus 200 correct sales

**Acceptance checks:** The submitted model reproduces the 200 baseline. Its metadata names order-line grain and the product-tag multiplicity. The review identifies the seeded relationship error and records unknown KPI definitions as questions rather than invented values.

**Delivery:**

- 20 minutes — Demonstration: Show the naive join and inflated aggregate. Evidence: 300 versus 200 reconciliation.
- 40 minutes — Guided lab: Map grain, keys and relationships. Evidence: Reviewed relationship diagram.
- 30 minutes — Independent exercise: Correct generated metadata and list unknowns. Evidence: JSON metadata and questions.
- 15 minutes — Assessment: Recompute total and defend relationship choices. Evidence: 200 baseline with explanation.

**Preparation:** Prepare order-line, product and product-tag tables plus the deliberately incorrect schema; Provide a working BI environment and metadata skeleton; AI-generated metadata must be checked against the supplied tables

**Sources:** https://learn.microsoft.com/en-us/power-bi/guidance/star-schema

## Engineering, Security & Product

**Scenario:** A deliberately insecure local application builds a customer lookup query from user input. A generated patch hides the error message but leaves the unsafe query construction intact.

**Topics:** Untrusted input crossing a query boundary; Parameter binding versus string concatenation; Authentication and authorisation regression cases; Output-context review for reflected content; AI-proposed patch review and reproducible evidence

**Prerequisites:** HTTP handlers, SQL queries and unit/integration tests

**Lab:** Inspect the prepared local repository and test evidence. Reject the cosmetic patch, replace concatenated query construction with parameter binding and add a regression test for the supplied hostile input. Re-run ordinary lookups. Use supplied tests to review separate authentication-bypass and reflected-output findings; distinguish fixed issues from issues still open.

**Participant output:** Minimal query patch, before/after regression results and a findings register separating verified fixes from unresolved findings

**Acceptance checks:** The query regression fails on the seeded vulnerable build and passes with bound parameters. Valid lookup tests still pass. The findings register cites evidence for each status and does not label the separate authentication or output issue fixed without passing its test.

**Delivery:**

- 20 minutes — Demonstration: Trace query construction and inspect the cosmetic patch. Evidence: Annotated unsafe data flow.
- 40 minutes — Guided lab: Write failing regression and implement bound parameters. Evidence: Minimal patch and before/after test.
- 25 minutes — Independent exercise: Run valid lookups and review separate seeded findings. Evidence: Findings register with evidence.
- 20 minutes — Assessment: Defend patch scope and unresolved issues. Evidence: Reviewed tests and explicit limitations.

**Preparation:** Provide a local-only vulnerable application, disposable database, fixed test inputs and baseline test suite; Supply expected findings separately; no production endpoint or customer data is needed

**Sources:** https://community.owasp.org/attacks/SQL_Injection
