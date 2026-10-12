"""Conservatively assess affirmative evidence that a saved reading is complete.

This module inspects only the supplied row.  It does not read source artifacts,
reassess claims, or infer completeness from a full-text label.
"""


def _positive_int(value):
    return type(value) is int and value > 0


def _extent(locator, characters):
    start = locator.get("start")
    end = locator.get("end")
    return type(start) is int and type(end) is int and 0 <= start < end <= characters


def _result(incomplete, pending):
    if incomplete:
        return {"status": "incomplete", "reasons": list(dict.fromkeys(incomplete))}
    if pending:
        return {"status": "pending", "reasons": list(dict.fromkeys(pending))}
    return {"status": "confirmed", "reasons": []}


def _fidelity_reasons(diagnostics):
    reasons = []
    fidelity = diagnostics.get("extraction_fidelity")
    if isinstance(fidelity, str) and any(
        marker in fidelity.casefold() for marker in ("pending", "incomplete")
    ):
        reasons.append("extraction-fidelity-unreviewed")
    # The source reader records layout review separately from page coverage.
    # Complete page extents cannot clear a pending or malformed order receipt.
    if "reading_order" in diagnostics:
        order = diagnostics["reading_order"]
        status = order.get("status") if isinstance(order, dict) else None
        if not isinstance(status, str) or status not in {"confirmed", "not-applicable"}:
            reasons.append("reading-order-unreviewed")
    return reasons


def _pdf_assessment(reading, diagnostics, locators, characters):
    incomplete = []
    pending = []
    required = ("pages_total", "readable_pages", "omitted_pages", "blank_pages")
    missing = [name for name in required if name not in diagnostics]
    if missing:
        pending.append("pdf-extent-proof-missing")

    total = diagnostics.get("pages_total")
    readable = diagnostics.get("readable_pages")
    omitted = diagnostics.get("omitted_pages")
    blank = diagnostics.get("blank_pages")
    if "pages_total" in diagnostics and not _positive_int(total):
        incomplete.append("pdf-page-count-invalid")

    for name, value, reason in (
        ("readable_pages", readable, "pdf-readable-pages-invalid"),
        ("omitted_pages", omitted, "pdf-omitted-pages-invalid"),
        ("blank_pages", blank, "pdf-blank-pages-invalid"),
    ):
        if name in diagnostics and not isinstance(value, list):
            incomplete.append(reason)

    if isinstance(omitted, list) and omitted:
        incomplete.append("pdf-pages-omitted")
    if isinstance(blank, list) and blank:
        incomplete.append("pdf-pages-blank")

    readable_valid = isinstance(readable, list) and all(
        _positive_int(page) for page in readable
    )
    if isinstance(readable, list) and not readable_valid:
        incomplete.append("pdf-readable-pages-invalid")
    if readable_valid and len(set(readable)) != len(readable):
        incomplete.append("pdf-readable-pages-duplicate")

    page_locators = [item for item in locators if item.get("type") == "pdf-page"]
    locator_pages = [item.get("value") for item in page_locators]
    locator_pages_valid = all(_positive_int(page) for page in locator_pages)
    if not page_locators or not locator_pages_valid:
        incomplete.append("pdf-page-locators-invalid")
    elif len(set(locator_pages)) != len(locator_pages):
        incomplete.append("pdf-page-locators-duplicate")

    if _positive_int(total):
        expected_sum = total * (total + 1) // 2
        if readable_valid and not (
            len(readable) == total
            and min(readable, default=0) == 1
            and max(readable, default=0) == total
            and sum(readable) == expected_sum
        ):
            incomplete.append("pdf-readable-page-coverage-mismatch")
        if locator_pages_valid and not (
            len(locator_pages) == total
            and min(locator_pages, default=0) == 1
            and max(locator_pages, default=0) == total
            and sum(locator_pages) == expected_sum
        ):
            incomplete.append("pdf-locator-page-coverage-mismatch")
        if readable_valid and locator_pages_valid and readable != locator_pages:
            incomplete.append("pdf-page-order-mismatch")

    extents_valid = all(_extent(item, characters) for item in page_locators)
    if page_locators and not extents_valid:
        incomplete.append("pdf-page-extents-invalid")
    if extents_valid and page_locators and locator_pages_valid:
        ordered = sorted(page_locators, key=lambda item: item["value"])
        if page_locators != ordered or ordered[0]["start"] != 0:
            incomplete.append("pdf-page-extents-inconsistent")
        else:
            prior_end = ordered[0]["end"]
            for item in ordered[1:]:
                if item["start"] - prior_end not in {0, 2}:
                    incomplete.append("pdf-page-extents-inconsistent")
                    break
                prior_end = item["end"]
            if ordered[-1]["end"] != characters:
                incomplete.append("pdf-page-extents-inconsistent")

    pending.extend(_fidelity_reasons(diagnostics))
    if any(
        isinstance(key, str) and key.startswith("geometry_") and value
        for key, value in diagnostics.items()
    ):
        pending.append("pdf-geometry-fallback-unreviewed")
    return _result(incomplete, pending)


def _document_assessment(row, reading, diagnostics, locators, characters):
    receipt = diagnostics.get("document_extent")
    if receipt is None:
        return {"status": "pending", "reasons": ["document-extent-proof-missing"]}
    if not isinstance(receipt, dict):
        return {"status": "incomplete", "reasons": ["document-extent-invalid"]}

    required = (
        "scope",
        "complete",
        "raw_sha256",
        "text_sha256",
        "expected_characters",
        "readable_characters",
    )
    if any(name not in receipt for name in required):
        return {"status": "pending", "reasons": ["document-extent-proof-missing"]}

    incomplete = []
    pending = _fidelity_reasons(diagnostics)
    if receipt["scope"] != "full-body" or receipt["complete"] is not True:
        incomplete.append("document-extent-invalid")
    bound_raw = row.get("raw_sha256")
    bound_text = reading.get("text_sha256")
    if not bound_raw or not bound_text:
        pending.append("document-bound-hash-missing")
    elif receipt["raw_sha256"] != bound_raw or receipt["text_sha256"] != bound_text:
        incomplete.append("document-extent-binding-stale")
    counts = (receipt["expected_characters"], receipt["readable_characters"])
    if not all(_positive_int(value) for value in counts) or any(
        value != characters for value in counts
    ):
        incomplete.append("document-extent-count-mismatch")
    body_locators = [
        item
        for item in locators
        if item.get("type") in {"text", "body"}
        and str(item.get("value", "body")).casefold()
        not in {"abstract", "title", "metadata"}
    ]
    if not any(
        _extent(item, characters) and item["start"] == 0 and item["end"] == characters
        for item in body_locators
    ):
        incomplete.append("document-extent-locator-invalid")
    return _result(incomplete, pending)


def assess_body_completeness(row):
    """Return a pure status/reason assessment for one supplied saved reading row."""
    if not isinstance(row, dict):
        return {"status": "pending", "reasons": ["body-reading-missing"]}
    reading = row.get("reading")
    if not isinstance(reading, dict):
        return {"status": "pending", "reasons": ["body-reading-missing"]}
    if reading.get("evidence_level", "full-text") != "full-text":
        return {"status": "pending", "reasons": ["body-not-full-text"]}
    if reading.get("status", "extracted") != "extracted":
        return {"status": "pending", "reasons": ["body-not-extracted"]}
    characters = reading.get("characters")
    if not _positive_int(characters):
        return {"status": "incomplete", "reasons": ["body-character-count-invalid"]}
    diagnostics = reading.get("diagnostics")
    locators = reading.get("locators")
    if not isinstance(diagnostics, dict) or not isinstance(locators, list):
        return {"status": "pending", "reasons": ["body-extent-proof-missing"]}
    if not all(isinstance(locator, dict) for locator in locators):
        return {"status": "incomplete", "reasons": ["body-locator-invalid"]}

    is_pdf = (
        str(row.get("raw_path", "")).casefold().endswith(".pdf")
        or any(locator.get("type") == "pdf-page" for locator in locators)
        or any(
            key in diagnostics
            for key in ("pages_total", "readable_pages", "omitted_pages", "blank_pages")
        )
    )
    if is_pdf:
        return _pdf_assessment(reading, diagnostics, locators, characters)
    return _document_assessment(row, reading, diagnostics, locators, characters)
