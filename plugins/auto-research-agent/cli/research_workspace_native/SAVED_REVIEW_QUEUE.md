# Explicit saved-request maintenance queue

`SavedReviewQueueService` extends the same private `MaintenanceInbox` used by
`SavedReviewService`. Existing feedback and its `recorded-not-dispatched` status
remain immutable. Separate append-only binding/events tables record explicit
queue admission, a receiving owner's claim, and the owner's result report.
There is no worker, process launcher, native/model/source call or automatic
dispatch. `submit-review` means follow-up of the original opinion; it does not
change scientific certification. Handoff items do not accept/import Stage 2.

## Trusted configuration and API

The embedding server authenticates and authorizes callers before passing their
principal labels. It fixes the original review service, independently pinned
registration file, a disjoint physical private result root and this policy:

```json
{
  "schema_version": "SavedReviewQueuePolicy.v1",
  "routes": {
    "submit-review": {"owner_ref": "review-followup", "admit_principals": ["reader"], "owner_principals": ["review-handler"]},
    "request-fix": {"owner_ref": "stage1-maintainer", "admit_principals": ["reader"], "owner_principals": ["stage1-handler"]},
    "request-handoff": {"owner_ref": "core-intake", "admit_principals": ["reader"], "owner_principals": ["core-handler"]}
  }
}
```

These illustrative labels are not credentials or proof of Core identity. Only
the actual trusted operator sets real allowed principals and routing. The browser
cannot select owners, principals, filesystem paths, policy or trusted hashes.
No browser-facing registration or HTTP route is added here.

```python
queue = SavedReviewQueueService(
    review, registration_path=trusted_registration_path,
    policy=trusted_policy, result_root=trusted_result_root,
)
saved = review.action(review.ref, original_request_key)
admitted = queue.admit(authenticated_reader, review.ref, {
    "key": admission_key, "source_key": saved["key"],
    "source_record_sha256": saved["record_sha256"],
    "source_review_revision": saved["review_revision"], "confirmed": True,
})
```

The caller must explicitly confirm that this original request should enter the
registered maintenance queue. It is not enqueued merely because it was saved.
Only the original submitter's allowed principal may admit it. Original request
revision, input version/type, run/Unknowns, context and exact work/version/source
SHA are retained. Later opinions do not invalidate that historical request.
Queue revisions are independent: admission is 1, owner claim 2, terminal report 3.

The allowed receiving owner actually calls `claim(owner, queue_ref, body)` with
`{key, revision: 1, confirmed: true}`. A different allowed worker cannot finish
another principal's claim. `finish(owner, queue_ref, body)` takes
`{key, revision: 2, outcome, reason, new_delivery_ref, confirmed: true}`.
Outcome is `completed` or `failed`; reason is original nonblank UTF-8 text up
to 4,000 bytes. A completed report requires a real nonempty file reference
`{path, bytes, sha256}` under the fixed result root, at most 32 MiB. Source and
result pins are checked before and after insertion. Failed reports may use null.
The service reads that artifact; it does not write or independently accept it.
The 32 MiB limit fits a small new-delivery manifest or producer seal which pins
the full delivery ZIP; it does not require this queue to read the complete ZIP.

Receipts say `queued-for-owner`, `owner-claimed`, `owner-reported-completed` or
`owner-reported-failed`, and retain `owner_report_only=true`. They always retain
`execution_authorized=false`, `research_execution_authorized=false`,
`Core_acceptance=false` and `formal_Stage2_import=false`. A candidate file can
still be building or awaiting CI/review; the report does not declare it released,
accepted by UI, scientifically correct or safe to consume. Genuine Core/HTML
acceptance and the exact producer-versus-derived-UI HTML binding remain separate.

Same key/body returns its original event without another admission or owner
action. Another admission key cannot duplicate an already queued source request.
Wrong principal/owner, request hash, original revision, queue CAS, changed
registration/source or policy refuses. Claim/result loss is recovered by
`action(principal, queue_ref, key=None)` and paginated
`history(principal, queue_ref, after_revision=0, limit=100)`. Reads and same-key
replay remain passive after source drift. A new write refuses drift and rolls
back; the prior claim remains visible without implying work completion. A crash
after claim is not automatically adopted, retried or converted to success.

Receipt reads reconstruct the exact action/body fields, fixed authority flags,
deterministic queue reference, source binding, allowed principal and ordered
admission/claim/terminal chain. A changed payload with a recalculated digest
still refuses inconsistent fields or a terminal actor different from the claim.
This validates receipt structure; it does not protect against an operator who
can replace the complete trusted policy and database. Historical result refs
receive structural checks only: moving the result file later does not erase
its old receipt or cause passive recovery to read current result bytes. New
writes continue to verify the actual source and result pins twice.

## Trusted local CLI

With the fixed plugin `cli/` on `PYTHONPATH`, use:

```text
python -B -X utf8 -m research_workspace_native.saved_review_queue
  --database <EXISTING_PRIVATE_INBOX_SQLITE>
  --package-root <FIXED_PRIVATE_PACKAGE_ROOT>
  --registration <ORIGINAL_REGISTRATION_JSON>
  --expected-registration-sha256 <INDEPENDENT_RAW_REGISTRATION_SHA256>
  --policy <TRUSTED_POLICY_JSON> --expected-policy-sha256 <INDEPENDENT_RAW_POLICY_SHA256>
  --result-root <FIXED_PRIVATE_RESULT_ROOT>
  admit --principal <ORIGINAL_SUBMITTER> --request <CONFIRMED_ADMISSION_JSON>
```

The line breaks above are presentation only; pass one argv list or use the
shell's normal continuation. Other subcommands are `claim` and `finish` (each
with `--principal`, `--queue-ref`, `--request`), `action` (principal/queue-ref,
optional `--key`) and `history` (principal/queue-ref, optional after-revision/limit).
Only `admit` can first register queue configuration. The original saved-review
registration and database must already exist. CLI principal labels are explicit
operator declarations, not authenticated human identities. Missing real Core
owner credentials does not authorize the Stage1 operator to claim Core work.

No formal acceptance, actual research run, UI HTTP adaptation or real production
request admission is demonstrated by this module's authored SQLite tests.
