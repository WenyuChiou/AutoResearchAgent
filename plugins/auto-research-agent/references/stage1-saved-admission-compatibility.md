# Saved-source producer/receiver compatibility

The optional acceptance envelope kind SavedSourceAdmissionCompatibilityAcceptance
uses schema_version2.0.0 and
separates an independently accepted historical producer from a later receiving
validator. Existing v1 admission keeps its complete-current-producer check;
failure never automatically enables compatibility.

Pass the versioned envelope through the existing acceptance-ref and independent
trusted-acceptance-sha256 inputs. No historical-root override or alternate CLI
entry is added. All explicit HostReplay inputs or the single already verified
context remain required. Initial inspection and import revalidation must use
the same context and exact handoff.

The schema is schemas/stage1-saved-admission-compat.v2.schema.json. The envelope
contains the exact typed snapshot/project/input, that schema's SHA256, original
v1 acceptance reference, every original producer source as a contained byte/hash
reference, complete current receiver delivered/reviewed/tree/parents/source/CI
identity, HostReplay SHA and separately bound compatibility review.

Archived source files are read and hashed only. They are never imported or
executed. The historical source map must exactly match the independently trusted
old producer's entire inventory. Its original schema, four category/rubric/check
records, seven HTML actions, exact view and BibTeX bytes, commit identity and
successful source/post-main CI are rechecked. Missing, extra or changed source
entries refuse.

The receiver separately requires its entire installed CLI/schema/requirements
closure and exact-head source/post-main CI. Its review must bind the original
Core digest, current receiver delivered commit and full closure digest, exact
snapshot and verified HostReplay. Validator, rubric, passed results and evidence
must be present. Changed receiver bytes require a new current disposition;
receiver CI is never relabeled as historical source-acquisition evidence.

The compatibility review is technical, with scientific_acceptance and
execution_authorized both false. The unchanged handoff2.0/ImportReceipt2.1
record the explicit acceptance reference but do not start Stage2 research.
Hashes cannot authenticate reviewers, browser actions or GitHub themselves:
the externally supplied acceptance digest remains a separate trusted decision.
Never compute it from an unreviewed attachment and treat that as acceptance.

Synthetic tests cover the two complete closures, original category/HTML evidence,
external digest, delivered/CI identity, snapshot/type/replay/review changes, path
and byte substitution, malformed JSON shapes and no-authority flags. The outer
forwarding fixture deliberately mocks upstream/Core checks; it proves context
forwarding only. Actual receiving still requires reviewed delivered code, the
corresponding real compatibility disposition and a new immutable import root.
