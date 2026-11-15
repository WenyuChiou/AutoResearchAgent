# ProjectHost completion evidence

The optional read-only adapter in
`cli/research_workspace_native/project_completion.py` connects an existing
ProjectHost submission and saved Stage 3 plan to the caller's completion checker.
It does not start a planner, submit a choice, rerun research, or grant execution
authority. It is an engineering check, not a research-quality evaluation.

## Trusted caller inputs

The application supplies its existing selection and planning services, an
authorized credential, and a `CompletionIdentity`. The identity pins the task,
code version, environment, operation, project, exact input-version type/value,
delivery manifest, original submission request and saved plan manifest. Obtain
these pins from the application's accepted operation, not from the event file
being checked. Supply the original planning request with its key and hash.

`inspect_project_completion(...)` calls the existing service validators again
under their shared intake lock. They check the persisted submission, current
source/version and saved plan package. Missing, stale, failed or tampered records
raise an error. Tentative direction advice remains distinct from a formally
selected planning input; both retain `execution_authorized=false`.

## Completion checker integration

Load the approved generic `task_completion` module in the trusted application;
event JSON must never select or import Python code. Bind the adapter explicitly:

```python
adapter = completion_event_adapter(
    selection_service, planning_service, credential, identity, original_request,
    event_factory=task_completion.VerifiedEvent,
    observed_events=trusted_browser_observations,
)
result = task_completion.verify(
    fixed_contract, evidence_root,
    event_verifiers={"projecthost": adapter},
)
```

Each observer record binds its phase, target, mechanism, operation, project,
input version, submission request hash, planning key/request hash and saved plan
manifest hash. Different planning jobs under the same selection cannot share
completion evidence. UI entry/action must originate from the requested
button or keyboard action. A GET or direct API call cannot substitute for that
journey. The adapter reinspects the authoritative services and compares the
event artifact with those facts on every check. The caller still owns and pins
the contract, evidence and observer provenance; hashes alone do not establish
authorship.

Only `automation` and `synthetic` observer origins are supported. ProjectHost
does not authenticate the named human behind a submission, so this adapter
cannot establish actual-human acceptance. A successful automated journey must
remain labelled as such. No credential is included in the returned evidence.

## Acceptance paths

`test_project_completion.py` covers negative trust boundaries. Its service
doubles do not prove a real Host or browser journey.

`test_project_wiki_completion_e2e.py` uses the production V9 Wiki renderer and
real Host services over isolated, authored fixtures. Desktop and mobile cases
start in Wiki Stage 2, select a direction, click **Save and start planning**,
enter the same project's Stage 3, and inspect the persisted plan. The test
planner is deterministic: one callback per case, zero research-model calls.
Refreshing a saved plan must not submit another job. Browser observations,
service inspection, screenshots and traces are retained separately.

Set `PROJECT_WIKI_COMPLETION_EVIDENCE_ROOT` to a private output directory outside
every Git tree, as required by the existing planning storage guard. This setting
does not waive local workspace policy. A blocked launch is a failed acceptance
attempt, not a successful journey. Install the project's pinned test dependencies
and Playwright runtime separately; copying the generic harness does not deploy
this project's Host, inputs, permissions or authenticated accounts.
