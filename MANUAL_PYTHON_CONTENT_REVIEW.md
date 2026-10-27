# Manually authored Python TOC content

29 distinct modules. Applied only to exact topic matches in Python datasets. Original source subtopics are retained; these exercises do not establish mastery of every subtopic. Lab assets, timings and technical review remain pending.

## Python Basics

**Prerequisites:** Basic computer use and running a Python script

**Scenario:** An expense clerk needs a calculator that rejects invalid input instead of crashing.

**Lab:** Build a command-line calculator for two numbers and +, -, * or /. Separate input conversion from calculation. Add a number-guessing loop with an injected target so checks are repeatable.

**Participant output:** calculator.py, guessing_game.py and an input/result table

**Acceptance checks:**

- Inputs 8, 2 and / return 4
- Division by zero and input 'abc' produce actionable errors without a traceback
- With target 7, guesses 3, 9, 7 report low, high, correct and terminate

## Control Flow & Functions

**Prerequisites:** Variables, arithmetic and boolean expressions

**Scenario:** A reporting script repeats logic and fails on empty input.

**Lab:** Extract pure functions for summing positive values, producing a triangular text pattern and computing factorial with a recursive base case. Reject negative factorial inputs.

**Participant output:** functions.py and table-driven checks

**Acceptance checks:**

- Values [-2, 0, 3, 5] produce a positive-value sum of 8
- Factorial of 0 is 1 and factorial of 5 is 120; -1 raises ValueError
- A three-row pattern has row lengths 1, 2, 3; zero rows returns an empty result

## Data Structures

**Prerequisites:** Loops and functions

**Scenario:** Student records contain repeated IDs and inconsistent marks.

**Lab:** Store grades in a dictionary keyed by student ID, retain subject marks in lists and reject duplicate IDs. Calculate class statistics without mutating submitted records.

**Participant output:** Grade manager, sample records and validation report

**Acceptance checks:**

- Marks 60, 75, 90 yield mean 75
- Duplicate student ID is rejected without replacing the original marks
- An empty class returns an explicit no-data result; marks outside 0 to 100 are rejected

## Object-Oriented Programming

**Prerequisites:** Functions, dictionaries and exceptions

**Scenario:** A small library must prevent duplicate loans and a bank-account model must protect balances.

**Lab:** Implement Account.deposit/withdraw and Library.checkout/return methods with explicit invariants. Keep account and book state private to each instance; raise domain errors for invalid operations.

**Participant output:** Account and Library classes with state-transition tests

**Acceptance checks:**

- Starting balance 100, deposit 20 and withdrawal 30 leave 90
- A withdrawal of 200 fails and leaves the balance unchanged
- Checking out an already-loaned book fails; returning it allows a new checkout

## Modules & Packages

**Prerequisites:** Functions, files and virtual environments

**Scenario:** Two scripts duplicate date parsing and data validation helpers.

**Lab:** Move reusable functions into a local package with explicit public imports. Add a command entry point and demonstrate importing the installed package from a different working directory.

**Participant output:** Installable utility package, build metadata and smoke-test instructions

**Acceptance checks:**

- A clean virtual environment can install and import the package
- Importing a utility does not execute the command-line program
- Invalid dates return the documented error consistently through both CLI and library calls

## NumPy Fundamentals

**Prerequisites:** Lists, loops and basic arithmetic

**Scenario:** A sensor report must compute per-sensor averages while retaining missing-value information.

**Lab:** Use a supplied 3-by-2 measurement array to calculate column means, masks and normalised values. Compare an explicit Python loop with vectorised calculation and distinguish element-wise multiplication from matrix multiplication.

**Participant output:** Notebook with arrays, shape annotations and equality checks

**Acceptance checks:**

- Array [[1,2],[3,4],[5,6]] has column means [3,4]
- A boolean mask identifies the exact location of an injected NaN
- The loop and vectorised result agree within a stated tolerance; incompatible shapes raise a explained error

## Pandas Data Analysis

**Prerequisites:** CSV handling and Python dictionaries

**Scenario:** Sales totals increase after joining customer data with duplicate keys.

**Lab:** Read a sales CSV, validate order IDs, aggregate revenue by region and join customer metadata with a cardinality check. Isolate unmatched rows and explain the effect of duplicate customer keys.

**Participant output:** Analysis notebook, regional totals and join-exception report

**Acceptance checks:**

- North sales 100 and 50 total 150; South sale 80 totals 80
- The valid join preserves the 230 grand total
- A duplicate customer key is detected before publishing totals; an unmatched order remains visible in the exception report

## Data Visualization

**Prerequisites:** Pandas grouping and missing-value handling

**Scenario:** A dashboard hides a missing month and makes revenue and order counts appear comparable on an unlabeled axis.

**Lab:** Create monthly revenue and order-count views from a fixed dataset. Preserve a missing-month gap, label units and create a regional comparison with a documented aggregation rule.

**Participant output:** Chart notebook, exported figures and an explanation of chart choices

**Acceptance checks:**

- Plotted monthly totals reconcile to the input aggregation
- The missing month is shown as missing rather than zero revenue
- Revenue and count units are explicit and a selected region filters both chart and supporting table consistently

## Web Basics & REST APIs

**Prerequisites:** Functions, dictionaries and JSON

**Scenario:** An inventory client cannot distinguish missing items from server failures.

**Lab:** Implement a local JSON inventory service with list, detail and create operations. Define the request schema, response statuses and handling of malformed JSON.

**Participant output:** Local service, request examples and endpoint contract

**Acceptance checks:**

- Creating a valid item returns a new identifier and a successful creation status
- Reading an unknown identifier returns 404 without an internal traceback
- Malformed JSON is rejected and does not create a record

## Flask Framework Fundamentals

**Prerequisites:** HTTP methods, HTML forms and Python functions

**Scenario:** A support form loses validation errors and creates duplicate tickets on refresh.

**Lab:** Build a Flask ticket form with server-side validation, a confirmation page and a redirect after successful submission. Render submitted text safely through the template engine.

**Participant output:** Flask app, templates and form-flow tests

**Acceptance checks:**

- A valid submission creates one ticket and redirects to confirmation
- An empty subject renders a clear error and creates no ticket
- Refreshing the confirmation page creates no second ticket; markup in the subject appears as text

## Flask with Databases

**Prerequisites:** Flask routing and SQL basics

**Scenario:** A ticket system needs persistent owners and must recover from failed writes.

**Lab:** Add users and tickets to a supplied Flask starter with relational models and migrations. Implement one transactional create operation and inject a failure before commit.

**Participant output:** Models, migration scripts and persistence/rollback tests

**Acceptance checks:**

- A ticket remains available after application restart
- A failed transaction leaves no partial ticket record
- Listing one owner's tickets excludes another owner's tickets and avoids an extra owner query for every row

## Django Fundamentals

**Prerequisites:** Python classes, HTTP and relational tables

**Scenario:** Editors need a blog whose drafts are not visible to anonymous readers.

**Lab:** Build models, views, templates and URL routes for a supplied Django blog starter. Use framework authentication; restrict draft editing to its owner and show only published posts publicly.

**Participant output:** Blog application, migrations and visibility tests

**Acceptance checks:**

- Anonymous readers see published posts but not drafts
- An authenticated owner can edit their draft
- Another authenticated user cannot edit that draft by changing the URL identifier

## Django ORM & Queries

**Prerequisites:** Django models and SQL joins

**Scenario:** A blog list sends a separate database query for every author.

**Lab:** Seed posts with authors and tags. Measure baseline query count, optimise related-object access and add a query-budget regression test; inspect aggregates for duplication across tags.

**Participant output:** Before/after query report and ORM regression tests

**Acceptance checks:**

- Rendering 20 posts stays within the declared query budget
- Doubling posts does not double related-author query count
- Tagged-post counts agree with distinct post IDs rather than joined-row count

## Django REST Framework

**Prerequisites:** Django ORM and HTTP response codes

**Scenario:** A blog mobile client needs paginated posts but must not edit another user's content.

**Lab:** Add serializers, viewsets, routing and object permissions to the blog starter. Define pagination and validate required title fields.

**Participant output:** REST endpoints, serializer tests and permission matrix

**Acceptance checks:**

- Two pages contain no repeated post IDs under a stable ordering
- A blank title produces a validation error and no new post
- A different authenticated user cannot update or delete the owner's post

## FastAPI Basics

**Prerequisites:** Python type hints, JSON and HTTP

**Scenario:** An order endpoint accepts negative quantities and returns undocumented responses.

**Lab:** Implement typed request and response models for an order endpoint and an item lookup. Constrain quantity to 1 through 5, expose generated OpenAPI and test with an in-process client.

**Participant output:** FastAPI service, OpenAPI schema and request-validation tests

**Acceptance checks:**

- Quantities 1 and 5 are accepted
- Quantities 0 and 6 receive validation errors with no stored order
- An unknown item returns the declared 404 response and OpenAPI documents the input constraints

## FastAPI Advanced

**Prerequisites:** FastAPI dependencies and basic authentication concepts

**Scenario:** A signed token is accepted even after expiry and users can read other users' records.

**Lab:** Extend a prepared authentication starter with expiry checks and object-level authorisation. Use test signing keys and an injectable clock. Distinguish authentication failure from an authenticated but forbidden action.

**Participant output:** Protected endpoints, token tests and access-control matrix

**Acceptance checks:**

- A valid unexpired token can read its owner's record
- Expired or incorrectly signed tokens are rejected
- Changing the record ID never grants access to another owner's data

## Async Python & Concurrency

**Prerequisites:** Coroutines, HTTP requests and exceptions

**Scenario:** A collector hangs when one endpoint is slow and launches too many concurrent calls.

**Lab:** Fetch five local mock endpoints with bounded concurrency of two, per-call deadlines and cancellation cleanup. Preserve the relationship between each URL and its result.

**Participant output:** Async collector, mock endpoints and concurrency trace

**Acceptance checks:**

- Observed in-flight requests never exceed two
- One timed-out endpoint produces a labelled error while other results remain available
- Cancelling the collection closes clients and leaves no pending task warnings

## Testing & TDD

**Prerequisites:** Application fixtures and business-rule functions

**Scenario:** A price calculation regression is invisible because tests only assert that the endpoint responds.

**Lab:** Write a failing business-rule test for a supplied Flask or Django checkout. Apply the minimal correction and add fixture-isolated boundary cases for discounts and invalid quantities.

**Participant output:** Red/green test history and focused regression suite

**Acceptance checks:**

- The new test fails against the original defect
- A 100 subtotal with a 10-percent discount totals 90
- Invalid quantities fail before persistence and tests pass in both normal and reversed order

## Web Scraping

**Prerequisites:** HTML structure, HTTP concepts and CSV output

**Scenario:** A local product catalog changes its markup and includes repeated links.

**Lab:** Scrape trainer-provided HTML pages using stable selectors. Follow two pagination pages, deduplicate product IDs and handle a page missing its price field without inventing a zero price.

**Participant output:** Scraper, local HTML fixtures and CSV export with exception log

**Acceptance checks:**

- Repeated product links yield one exported row per ID
- A missing price is reported as missing and not converted to zero
- An empty or changed page triggers a useful diagnostic instead of silently reporting a complete scrape

## Machine Learning Basics

**Prerequisites:** Pandas, features/labels and train/test splitting

**Scenario:** A classification experiment reports inflated accuracy because preprocessing saw validation data.

**Lab:** Train a baseline classifier on a supplied labelled dataset using a preprocessing pipeline and stratified cross-validation. Keep a final holdout untouched and compare with a simple majority-class baseline.

**Participant output:** Reproducible notebook, fold results and holdout report

**Acceptance checks:**

- Preprocessing is fitted inside each training fold
- The holdout is excluded from tuning and evaluated only after model selection
- The report includes per-class errors and baseline comparison without claiming a guaranteed target accuracy

## Deep Learning Fundamentals

**Prerequisites:** Classification metrics, tensor shapes and neural-network basics

**Scenario:** An image model appears accurate because augmented versions of one image occur in both training and validation.

**Lab:** Use a small prepared image dataset and CNN starter. Split by original image identity before augmentation, run a short bounded training session and inspect misclassified examples.

**Participant output:** Training notebook, split manifest and error gallery

**Acceptance checks:**

- No source image identity occurs in both train and validation manifests
- Output shape matches the declared class count
- Metrics and selected errors are reproducible under recorded settings; no arbitrary accuracy threshold is asserted

## DevOps & Deployment

**Prerequisites:** Python dependency files and container basics

**Scenario:** A Python API works on a laptop but fails in a fresh container.

**Lab:** Containerise the supplied API with pinned dependencies, explicit runtime configuration and a health endpoint. Run as a non-root user and test startup with a missing required setting.

**Participant output:** Dockerfile, launch instructions and startup/health evidence

**Acceptance checks:**

- A clean build starts and serves the health endpoint
- The application process does not run as root
- A missing required setting fails with a clear message and secrets are absent from the image build context

## CI/CD Pipeline for Python

**Prerequisites:** Git, automated tests and container builds

**Scenario:** A deployment pipeline continues after a failed regression test.

**Lab:** Create a pipeline for the supplied Python service that installs locked dependencies, runs checks and builds an artifact only after tests pass. Use a staging deployment stub rather than production credentials.

**Participant output:** Pipeline configuration and passing/failing run evidence

**Acceptance checks:**

- The seeded regression fails the test stage
- The failed run never reaches the deployment stub
- A passing run produces a traceable artifact tied to the commit and records its test results

## Database Design & SQL

**Prerequisites:** SQL SELECT, joins and transactions

**Scenario:** An order table repeats customer details and permits orphan order lines.

**Lab:** Design customer, order and order-line tables with keys and constraints. Seed two orders with multiple lines; write a revenue query and compare its execution plan before and after a justified index.

**Participant output:** Schema migration, seed data, reconciliation SQL and plan comparison

**Acceptance checks:**

- An orphan order line is rejected by a foreign-key constraint
- Order totals reconcile to the sum of quantity times unit price
- The index choice is justified by the query plan and preserves result rows; no universal speedup is claimed

## API Security & Best Practices

**Prerequisites:** HTTP authentication, model validation and logging

**Scenario:** An API exposes another user's order when a valid user changes the ID.

**Lab:** Add object-level access checks to a prepared API, validate request fields and inspect logs for seeded credentials. Exercise unauthenticated, owner and non-owner cases using disposable test users.

**Participant output:** Access-control tests, validation rules and redacted log sample

**Acceptance checks:**

- Owner access succeeds and non-owner access is denied
- Unknown request fields cannot change owner or privilege attributes
- Seeded passwords and bearer tokens do not appear in captured request logs

## Performance Optimization

**Prerequisites:** Profiling tools, SQL queries and regression tests

**Scenario:** A list endpoint repeats database calls for each result and slows with larger pages.

**Lab:** Profile a fixed workload on the supplied local API. Identify repeated calls, implement one targeted optimisation and compare both result equivalence and query count under the same fixture.

**Participant output:** Profile traces, minimal patch and controlled benchmark report

**Acceptance checks:**

- Response values and ordering remain unchanged
- Doubling page size no longer doubles the eliminated lookup calls
- Timing comparisons use repeated runs with recorded fixture and environment; variability is reported

## Real-Time Features

**Prerequisites:** Async endpoints, authentication and connection lifecycle

**Scenario:** A notification service delivers events to the wrong room after a reconnect.

**Lab:** Implement authenticated room subscriptions in a local WebSocket starter. Connect two users to different rooms, disconnect one and test cleanup and resubscription with identifiable messages.

**Participant output:** WebSocket service, two-client test harness and message trace

**Acceptance checks:**

- Each message reaches only the authorised room
- A disconnected client's subscription is removed
- Reconnect follows the documented replay or no-replay policy without accidental duplicate delivery

## Capstone Project - Part 1

**Prerequisites:** One Python web framework, SQL and automated tests

**Scenario:** A team must scope a small order-tracking service before implementation.

**Lab:** Produce an API contract, relational schema and thin vertical slice that creates and reads an order. Define owner permissions, invalid-input cases and explicit exclusions; choose one Python framework rather than combining several.

**Participant output:** Architecture sketch, backlog, API contract and working vertical slice

**Acceptance checks:**

- One valid order can be created and retrieved end to end
- The contract names validation errors and ownership rules
- Every in-scope requirement maps to an acceptance test; optional features remain outside the committed scope

## Capstone Project - Part 2 + Certification Roadmap

**Prerequisites:** Completed capstone vertical slice and container/testing foundations

**Scenario:** The order-tracking prototype needs a reproducible handoff and an honest statement of its limitations.

**Lab:** Complete owner-access checks and regression tests, package the service and demonstrate startup from a clean environment. Inject a failed configuration and document recovery. Map demonstrated skills to further study without promising certification eligibility.

**Participant output:** Runnable release, test report, setup/recovery guide and skills-gap plan

**Acceptance checks:**

- A clean environment can run the documented happy path
- Unauthorised access and invalid-order regression tests pass
- The handoff records known limitations and recovers from the injected configuration failure without losing seeded orders
