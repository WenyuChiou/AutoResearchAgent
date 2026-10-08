"""Verify supplied PDF review bytes, without reading files or replaying readers.

The external acceptance digest must come from the caller, outside the bundle.
Digest binding and distinct declared actors do not authenticate a human reviewer.
This engineering evidence never overrides formal eligibility or scientific state.
"""

from copy import deepcopy
from difflib import SequenceMatcher
from pathlib import PurePosixPath
import re

from stage1_deliverable.common import DeliverableError, canonical, sha

from .json_bytes import decode_json


VERSION = "1.0.0"
SCOPE = "engineering-only-body-text"
HASH = re.compile(r"[0-9a-f]{64}")
BINDING = {"work_id", "source_id", "version_id", "source_version", "attempt_id",
           "reading_sha256", "raw_sha256", "text_sha256"}
CLASSES = {"text", "math", "table", "figure"}
EXTENT = {"page", "start", "end", "reader_start", "reader_end",
          "saved_text_sha256", "reader_text_sha256"}


def _require(condition, message):
    if not condition:
        raise DeliverableError("body review: " + message)


def _keys(value, keys, label):
    _require(isinstance(value, dict) and set(value) == set(keys), label + " fields differ")
    return value


def _string(value, label):
    _require(isinstance(value, str) and bool(value.strip()), label + " missing")
    return value.strip()


def _hash(value):
    _require(isinstance(value, str) and HASH.fullmatch(value), "invalid SHA-256")
    return value


def _bytes(reference, artifacts):
    _keys(reference, {"path", "sha256"}, "artifact reference")
    name = _string(reference["path"], "artifact path")
    path = PurePosixPath(name)
    _require(reference["path"] == name == str(path) and not path.is_absolute() and ".." not in path.parts
             and "\\" not in name and ":" not in name and name != ".", "unsafe artifact path")
    raw = artifacts.get(name)
    _require(type(raw) is bytes and sha(raw) == _hash(reference["sha256"]),
             "artifact missing or hash differs: " + name)
    return raw


def _json(reference, artifacts):
    try:
        return decode_json(_bytes(reference, artifacts))
    except DeliverableError:
        raise
    except (ValueError, UnicodeError) as error:
        raise DeliverableError("body review: invalid JSON artifact") from error


def _header(value, kind):
    _require(value["kind"] == kind and value["schema_version"] == VERSION,
             "unsupported " + kind + " version")


def _quote(quote, text, start, end):
    _keys(quote, {"start", "end", "text", "sha256"}, "quotation")
    left, right = quote["start"], quote["end"]
    _require(type(left) is int and type(right) is int and start <= left < right <= end,
             "quotation extent invalid")
    _string(quote["text"], "quotation text")
    _require(text[left:right] == quote["text"] and sha(quote["text"].encode("utf-8"))
             == _hash(quote["sha256"]), "quotation differs")


def _runtime(manifest, artifacts):
    runtime = _json(manifest["runtime"], artifacts)
    _keys(runtime, {"kind", "schema_version", "python_version", "reader_name",
                    "reader_version", "program_sha256", "executable", "module",
                    "native_library"}, "reader runtime")
    _header(runtime, "IndependentPDFReaderRuntime")
    for key in ("python_version", "reader_name", "reader_version"):
        _string(runtime[key], key)
    _require(runtime["program_sha256"] == manifest["program"]["sha256"], "runtime program differs")
    for key in ("executable", "module", "native_library"):
        _require(bool(_bytes(runtime[key], artifacts)), "empty runtime artifact")
    return runtime


def _pages(manifest, reading, text, artifacts):
    pages = manifest["pages"]
    diagnostics = reading["diagnostics"]
    total = diagnostics.get("pages_total")
    _require(type(total) is int and total > 0 and isinstance(pages, list)
             and len(pages) == total, "page count differs")
    locators = [item for item in reading["locators"] if item.get("type") == "pdf-page"]
    _require(len(locators) == total, "PDF locator count differs")
    expected = [index + 1 for index in range(len(pages))]
    _require(isinstance(diagnostics.get("readable_pages"), list)
             and all(type(value) is int for value in diagnostics["readable_pages"])
             and diagnostics["readable_pages"] == expected
             and diagnostics.get("omitted_pages") == [] and diagnostics.get("blank_pages") == [],
             "omitted, blank or unreadable pages")
    changes, prior_end, scoped = {}, 0, False
    for number, (page, locator) in enumerate(zip(pages, locators), 1):
        _keys(page, {"page", "start", "end", "saved_text_sha256", "reader_text",
                     "quotations", "comparison"}, "page proof")
        start, end = page["start"], page["end"]
        _require(type(page["page"]) is int and page["page"] == number
                 and type(locator.get("value")) is int and locator["value"] == number,
                 "page order differs")
        _require(type(start) is int and type(end) is int and 0 <= start < end <= len(text)
                 and start == locator.get("start") and end == locator.get("end"), "page extent differs")
        _require(start == prior_end or (number > 1 and text[prior_end:start] == "\n\n"
                 and start == prior_end + 2), "page extents overlap or leave content uncovered")
        saved = text[start:end]
        _require(bool(saved.strip()) and sha(saved.encode("utf-8")) == _hash(page["saved_text_sha256"]),
                 "saved page text differs")
        try:
            observed = _bytes(page["reader_text"], artifacts).decode("utf-8")
        except UnicodeError as error:
            raise DeliverableError("body review: reader text is not UTF-8") from error
        _require(bool(observed.strip()), "blank independent page")
        _require(isinstance(page["quotations"], list) and bool(page["quotations"]), "page quotation missing")
        for quote in page["quotations"]:
            _quote(quote, text, start, end)
        _require(page["comparison"] in {"exact", "scoped", "discrepancy"}, "comparison invalid")
        if page["comparison"] == "exact":
            _require(saved == observed, "exact page comparison differs")
        elif page["comparison"] == "scoped":
            scoped = True
        else:
            changes[number] = {(start + left, start + right, a, b)
                               for operation, left, right, a, b in
                               SequenceMatcher(None, saved, observed, autojunk=False).get_opcodes()
                               if operation != "equal"}
            _require(bool(changes[number]), "discrepancy has no text difference")
        prior_end = end
    _require(prior_end == reading["characters"], "final page extent differs")
    return changes, scoped


def _discrepancies(manifest, acceptance, text, artifacts, changes):
    entries, reviews = manifest["discrepancies"], acceptance["discrepancy_reviews"]
    _require(isinstance(entries, list) and isinstance(reviews, list) and len(entries) == len(reviews),
             "discrepancy reviews differ")
    reviewed, covered, unresolved = {}, {}, []
    for review in reviews:
        _keys(review, EXTENT | {"id", "reviewer", "decision", "rationale",
                               "evidence_sha256", "image_sha256"}, "discrepancy review")
        _string(review["id"], "discrepancy ID")
        _require(review["id"] not in reviewed, "duplicate discrepancy review")
        reviewed[review["id"]] = review
    used = set()
    for entry in entries:
        _keys(entry, EXTENT | {"id", "image", "evidence", "failure_class"}, "discrepancy")
        _require(entry["id"] in reviewed and entry["id"] not in used, "discrepancy review missing or duplicate")
        used.add(entry["id"])
        review = reviewed[entry["id"]]
        _require(all(review[key] == entry[key] for key in EXTENT), "reviewed discrepancy extent differs")
        _require(review["reviewer"] == acceptance["reviewer"] and review["decision"] in {"equivalent", "unresolved"},
                 "discrepancy reviewer or decision differs")
        _string(review["rationale"], "discrepancy rationale")
        page = entry["page"]
        _require(type(page) is int and page in changes and entry["failure_class"] in CLASSES,
                 "discrepancy page or failure class differs")
        extent = tuple(entry[key] for key in ("start", "end", "reader_start", "reader_end"))
        _require(all(type(value) is int for value in extent) and extent in changes[page],
                 "discrepancy does not match an exact changed extent")
        _require(extent not in covered.setdefault(page, set()), "duplicate discrepancy extent")
        covered[page].add(extent)
        observed = _bytes(manifest["pages"][page - 1]["reader_text"], artifacts).decode("utf-8")
        _require(sha(text[extent[0]:extent[1]].encode("utf-8")) == _hash(entry["saved_text_sha256"])
                 and sha(observed[extent[2]:extent[3]].encode("utf-8")) == _hash(entry["reader_text_sha256"]),
                 "discrepancy text differs")
        _require(bool(_bytes(entry["image"], artifacts)), "discrepancy image missing")
        evidence = _json(entry["evidence"], artifacts)
        _keys(evidence, EXTENT | {"kind", "schema_version", "id", "binding", "image_sha256", "failure_class"},
              "discrepancy evidence")
        _header(evidence, "PDFPageDiscrepancyEvidence")
        _require(evidence["binding"] == manifest["binding"] and evidence["id"] == entry["id"]
                 and evidence["failure_class"] == entry["failure_class"]
                 and all(evidence[key] == entry[key] for key in EXTENT), "discrepancy evidence binding differs")
        _require(evidence["image_sha256"] == review["image_sha256"] == entry["image"]["sha256"]
                 and review["evidence_sha256"] == entry["evidence"]["sha256"], "reviewed discrepancy bytes differ")
        if review["decision"] == "unresolved":
            unresolved.append({"id": entry["id"], "page": page, "failure_class": entry["failure_class"],
                               "detail": review["rationale"]})
    _require(covered == changes, "unreviewed comparison discrepancy")
    return unresolved


def _verify_body_review(row, artifacts, expected_acceptance_sha256):
    """Verify one externally bound bundle; return engineering evidence only.

    Malformed, missing or stale bindings raise DeliverableError. Scoped proofs
    and faithfully retained residual failures return pending/unresolved statuses.
    Runtime bytes are checked as supplied artifacts, never imported or executed.
    """
    _hash(expected_acceptance_sha256)
    _require(isinstance(row, dict) and isinstance(artifacts, dict), "row/artifact mapping required")
    reference = _keys(row.get("body_review"), {"manifest_path", "manifest_sha256",
                                              "acceptance_path", "acceptance_sha256"}, "body_review")
    _require(reference["acceptance_sha256"] == expected_acceptance_sha256, "external acceptance hash differs")
    acceptance = _json({"path": reference["acceptance_path"], "sha256": expected_acceptance_sha256}, artifacts)
    _keys(acceptance, {"kind", "schema_version", "scope", "manifest_sha256", "reviewer", "producer",
                       "decision", "cover_geometry_decision", "discrepancy_reviews"}, "acceptance")
    _header(acceptance, "IndependentPDFBodyReviewAcceptance")
    _require(acceptance["manifest_sha256"] == reference["manifest_sha256"], "accepted manifest differs")
    manifest = _json({"path": reference["manifest_path"], "sha256": reference["manifest_sha256"]}, artifacts)
    _keys(manifest, {"kind", "schema_version", "scope", "producer", "binding", "parser_receipt",
                     "parser_program", "reader_receipt", "program", "runtime", "pages", "coverage",
                     "cover_geometry_review", "discrepancies", "residual_failures"}, "manifest")
    _header(manifest, "IndependentPDFBodyReview")
    _require(acceptance["scope"] == manifest["scope"] == SCOPE
             and acceptance["decision"] == "reviewed-engineering-evidence", "engineering-only scope required")
    producer = _string(manifest["producer"], "producer")
    reviewer = _string(acceptance["reviewer"], "reviewer")
    _require(acceptance["producer"] == manifest["producer"] and producer.casefold() != reviewer.casefold(),
             "self-review or producer binding differs")
    binding = _keys(manifest["binding"], BINDING, "source binding")
    reading = row.get("reading")
    _require(isinstance(reading, dict) and reading.get("evidence_level") == "full-text"
             and reading.get("status") == "extracted" and isinstance(reading.get("diagnostics"), dict)
             and isinstance(reading.get("locators"), list), "full extracted PDF reading required")
    for key in ("work_id", "source_id", "version_id", "source_version", "attempt_id", "raw_sha256"):
        _require(binding[key] == row.get(key), "source/attempt binding differs: " + key)
        _string(binding[key], key)
    _require(binding["reading_sha256"] == sha(canonical(reading))
             and binding["text_sha256"] == reading.get("text_sha256")
             and binding["source_version"] == "sha256:" + binding["raw_sha256"], "reading/version binding differs")
    _hash(binding["attempt_id"])
    raw = _bytes({"path": row.get("raw_path"), "sha256": binding["raw_sha256"]}, artifacts)
    _require(raw.startswith(b"%PDF-"), "PDF bytes required")
    try:
        text = _bytes({"path": row.get("extracted_path"), "sha256": binding["text_sha256"]}, artifacts).decode("utf-8")
    except UnicodeError as error:
        raise DeliverableError("body review: saved text is not UTF-8") from error
    _require(type(reading.get("characters")) is int and len(text) == reading["characters"] > 0, "text count differs")
    parser = _json(manifest["parser_receipt"], artifacts)
    prior = row.get("parser_receipt", {})
    _require(all(manifest["parser_receipt"][key] == prior.get(key) for key in ("path", "sha256")), "parser receipt differs")
    _require(isinstance(parser, dict) and all(parser.get(key) == binding[key]
             for key in ("work_id", "source_id", "version_id", "source_version", "raw_sha256")), "original parser source differs")
    original = parser.get("reading", {})
    _require(isinstance(original.get("diagnostics"), dict), "original parser diagnostics required")
    _require(all(original.get(key) == reading.get(key) for key in ("text_sha256", "characters", "locators", "evidence_level", "status")),
             "original parser reading differs")
    _require("automatic_reading" not in row or row["automatic_reading"] == original, "automatic reading differs")
    _require(bool(_bytes(manifest["parser_program"], artifacts)), "original parser program missing")
    _require(parser.get("runtime", {}).get("parser_sha256") == manifest["parser_program"]["sha256"], "parser program differs")
    _require(bool(_bytes(manifest["program"], artifacts)) and manifest["program"]["sha256"] != manifest["parser_program"]["sha256"],
             "independent reader program required")
    runtime = _runtime(manifest, artifacts)
    execution = _json(manifest["reader_receipt"], artifacts)
    _keys(execution, {"kind", "schema_version", "binding", "parser_receipt_sha256", "program_sha256",
                      "runtime_sha256", "pages_sha256", "discrepancies_sha256", "outcome"}, "reader execution")
    _header(execution, "IndependentPDFReaderExecution")
    _require(execution["binding"] == binding and execution["outcome"] == "completed"
             and execution["parser_receipt_sha256"] == manifest["parser_receipt"]["sha256"]
             and execution["program_sha256"] == manifest["program"]["sha256"]
             and execution["runtime_sha256"] == manifest["runtime"]["sha256"]
             and execution["pages_sha256"] == sha(canonical(manifest["pages"]))
             and execution["discrepancies_sha256"] == sha(canonical(manifest["discrepancies"])), "reader execution binding differs")
    coverage = _keys(manifest["coverage"], {"text_availability", "order", "punctuation", "word_boundaries"}, "coverage")
    _require(all(type(value) is bool for value in coverage.values()), "coverage must be explicit booleans")
    changes, scoped = _pages(manifest, reading, text, artifacts)
    unresolved = _discrepancies(manifest, acceptance, text, artifacts, changes)
    residual = manifest["residual_failures"]
    _require(isinstance(residual, list), "residual failures required")
    for failure in residual:
        _keys(failure, {"page", "failure_class", "detail"}, "residual failure")
        _require(type(failure["page"]) is int and 1 <= failure["page"] <= len(manifest["pages"])
                 and failure["failure_class"] in CLASSES, "residual failure invalid")
        _string(failure["detail"], "residual failure detail")
    unresolved.extend(deepcopy(residual))
    cover = manifest["cover_geometry_review"]
    geometry = any(isinstance(key, str) and key.startswith("geometry_") and value
                   for diagnostics in (reading["diagnostics"], original["diagnostics"]) for key, value in diagnostics.items())
    if cover is not None:
        _keys(cover, {"page", "image", "evidence"}, "cover geometry review")
        _require(type(cover["page"]) is int and cover["page"] == 1 and bool(_bytes(cover["image"], artifacts)), "cover page/image invalid")
        evidence = _json(cover["evidence"], artifacts)
        _keys(evidence, {"kind", "schema_version", "binding", "page", "image_sha256", "diagnostics_sha256"}, "cover evidence")
        _header(evidence, "PDFCoverGeometryReviewEvidence")
        _require(evidence["binding"] == binding and type(evidence["page"]) is int and evidence["page"] == 1
                 and evidence["image_sha256"] == cover["image"]["sha256"]
                 and evidence["diagnostics_sha256"] == sha(canonical(reading["diagnostics"])), "cover evidence differs")
        _require(acceptance["cover_geometry_decision"] in {"reviewed", "unresolved"}, "cover decision invalid")
        if acceptance["cover_geometry_decision"] == "unresolved":
            unresolved.append({"page": 1, "failure_class": "text", "detail": "cover geometry unresolved"})
    else:
        _require(not geometry and acceptance["cover_geometry_decision"] == "not-required", "explicit cover geometry review required")
    status = "unresolved" if unresolved else "scoped-pending" if scoped or not all(coverage.values()) else "verified-body-text"
    references = [{"path": reference["manifest_path"], "sha256": reference["manifest_sha256"]},
                  {"path": reference["acceptance_path"], "sha256": expected_acceptance_sha256}]
    references += [manifest[key] for key in ("parser_receipt", "parser_program", "reader_receipt", "program", "runtime")]
    references += [runtime[key] for key in ("executable", "module", "native_library")]
    references += [{"path": row["raw_path"], "sha256": binding["raw_sha256"]},
                   {"path": row["extracted_path"], "sha256": binding["text_sha256"]}]
    references += [page["reader_text"] for page in manifest["pages"]]
    references += [entry[key] for entry in manifest["discrepancies"] for key in ("image", "evidence")]
    if cover is not None:
        references += [cover[key] for key in ("image", "evidence")]
    artifact_bindings = dict(sorted((item["path"], item["sha256"]) for item in references))
    return {"kind": "IndependentPDFBodyReviewEvidence", "schema_version": VERSION, "status": status,
            "scope": SCOPE, "binding": deepcopy(binding), "acceptance_sha256": expected_acceptance_sha256,
            "manifest_sha256": reference["manifest_sha256"], "reviewer": reviewer, "producer": producer,
            "review_reference": deepcopy(reference), "artifact_bindings": artifact_bindings,
            "coverage": deepcopy(coverage), "unresolved": unresolved, "runtime": deepcopy(runtime),
            "original_diagnostics": deepcopy(original["diagnostics"]), "current_diagnostics": deepcopy(reading["diagnostics"]),
            "identity_status": reading.get("identity_status"),
            "reviewer_identity_authenticated": False, "formal_eligibility_override": False,
            "scientific_claim_adequacy": "not-assessed", "research_execution": False,
            "official_stage2_import_eligible": False, "quality_score": None}


def verify_body_review(row, artifacts, expected_acceptance_sha256):
    """Return bound engineering evidence; no file I/O, runtime replay or admission.

    The caller supplies the external acceptance digest. Declared actor names and
    byte hashes do not establish human identity or independent execution.
    """
    try:
        return _verify_body_review(row, artifacts, expected_acceptance_sha256)
    except (KeyError, TypeError, AttributeError) as error:
        raise DeliverableError("body review: malformed supplied evidence") from error
