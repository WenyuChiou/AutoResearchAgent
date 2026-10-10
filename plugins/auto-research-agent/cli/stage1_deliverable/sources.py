"""Wrap public source validation; preserve original receipts on relocation."""

import copy
import importlib.metadata
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import urlsplit

from .common import (
    DeliverableError,
    canonical,
    private_output,
    read_json,
    safe_path,
    sha,
    write_json,
)
from .records import _keys, public_uri, timestamp

HUB_SHA = "496a70415859a15031cb5da55d4495cb1d0a8e7d"
STATES = (
    "available",
    "abstract-only",
    "metadata-only",
    "paywalled",
    "not-found",
    "rate-limited",
    "network-error",
    "parse-error",
    "login-page",
    "identity-mismatch",
)
RESULT_FIELDS = (
    "status",
    "evidence_level",
    "source_url",
    "final_url",
    "expected_identity",
    "observed_identity",
    "identity_status",
    "source_version",
    "raw_path",
    "raw_sha256",
    "extracted_text_path",
    "extracted_text_sha256",
    "locators",
)
ATTEMPT_FIELDS = (
    "sequence",
    "purpose",
    "url",
    "final_url",
    "http_status",
    "outcome",
    "raw_sha256",
)


def runtime_binding():
    distribution = importlib.metadata.distribution("research-hub-pipeline")
    direct = json.loads(distribution.read_text("direct_url.json") or "{}")
    if direct.get("vcs_info", {}).get("commit_id") != HUB_SHA:
        raise DeliverableError(
            "research-hub must be installed from the pinned merge commit"
        )
    packages = {}
    for module, dist in (
        ("research_hub", "research-hub-pipeline"),
        ("pdfplumber", "pdfplumber"),
        ("openpyxl", "openpyxl"),
        ("docx", "python-docx"),
    ):
        spec = importlib.util.find_spec(module)
        if spec is None:
            raise DeliverableError(
                "declared exporter runtime dependency is missing: " + module
            )
        root = Path(spec.origin).parent
        packages[module] = {
            "version": importlib.metadata.version(dist),
            "python_sha256": sha(
                canonical(
                    {
                        p.relative_to(root).as_posix(): sha(p.read_bytes())
                        for p in sorted(root.rglob("*.py"))
                    }
                )
            ),
        }
    own = Path(__file__).parent
    distributions = {}
    for item in importlib.metadata.distributions():
        files = {}
        for name in item.files or []:
            if str(name).endswith((".pyc", ".pyo")) or "__pycache__" in str(name):
                continue
            path = Path(item.locate_file(name))
            if path.is_file():
                files[str(name).replace("\\", "/")] = sha(path.read_bytes())
        distributions[item.metadata["Name"]] = {
            "version": item.version,
            "file_count": len(files),
            "files_sha256": sha(canonical(files)),
        }
    return {
        "research_hub_merge_sha": HUB_SHA,
        "python_version": sys.version,
        "python_sha256": sha(Path(sys.executable).read_bytes()),
        "packages": packages,
        "installed_distributions": distributions,
        "exporter_sha256": sha(
            canonical({p.name: sha(p.read_bytes()) for p in sorted(own.glob("*.py"))})
        ),
        "docx": "available",
    }


def reject_secrets(raw):
    # Inspect common JSON escaping as well as literal header/form syntax. Keep
    # original bytes unchanged; ambiguous credential-like material is rejected.
    scanned = re.sub(
        rb"\\u([0-9a-fA-F]{4})",
        lambda match: chr(int(match[1], 16)).encode("utf-8"),
        raw,
    ).replace(b'\\"', b'"')
    if re.search(
        rb"""(?i)(?:bearer\s+[a-z0-9_.-]{8,}|["']?(?:password|access_token|api_key|authorization|client_secret)["']?\s*[=:]\s*["']?[^\s<>"']{4,}|sk-[a-z0-9_-]{20,})""",
        scanned,
    ):
        raise DeliverableError("credential-like content cannot enter a source archive")


def validate_receipt_shape(result):
    _keys(
        result,
        (
            "schema_version",
            "request",
            "receipt_sha256",
            "status",
            "evidence_level",
            "source_url",
            "final_url",
            "retrieved_at",
            "expected_identity",
            "observed_identity",
            "identity_status",
            "source_version",
            "attempts",
            "raw_path",
            "raw_sha256",
            "extracted_text_path",
            "extracted_text_sha256",
            "locators",
            "errors",
            "output_dir",
        )
        + (
            ("diagnostics",)
            if isinstance(result, dict) and "diagnostics" in result
            else ()
        ),
        "public source receipt",
    )
    if "diagnostics" in result and not isinstance(result["diagnostics"], dict):
        raise DeliverableError("source diagnostics must be an object")
    _keys(
        result["request"],
        ("operation", "doi", "url", "title", "output_dir", "public_only"),
        "source request",
    )
    if result["request"]["public_only"] is not True:
        raise DeliverableError(
            "source request must be credential-free public acquisition"
        )
    for key in ("expected_identity", "observed_identity"):
        _keys(result[key], ("doi", "title"), key)
    for value in (result["request"]["url"], result["source_url"], result["final_url"]):
        if value:
            public_uri(value)
    timestamp(result["retrieved_at"])
    if not isinstance(result["attempts"], list) or not result["attempts"]:
        raise DeliverableError("source requires at least one preserved attempt")
    for attempt in result["attempts"]:
        _keys(
            attempt,
            (
                "sequence",
                "purpose",
                "url",
                "final_url",
                "requested_at",
                "received_at",
                "http_status",
                "content_type",
                "outcome",
                "response_bytes",
                "response_truncated",
                "raw_path",
                "raw_sha256",
                "error",
            ),
            "source attempt",
        )
        public_uri(attempt["url"])
        public_uri(attempt["final_url"])
    reject_secrets(canonical(result))


def receipt_digest(result):
    """Match v1 serialization in the immutable merged SDK pin.

    Nonempty diagnostics are receipt claims and are re-extracted during SDK
    replay. Absent or empty diagnostics retain the exact legacy v1 digest.
    """
    claims = {key: result.get(key) for key in RESULT_FIELDS}
    if result.get("diagnostics"):
        claims["diagnostics"] = result["diagnostics"]
    return sha(
        canonical(
            {
                "schema_version": "source-fetch-result/v1",
                "request": result["request"],
                "attempts": [
                    {k: a[k] for k in ATTEMPT_FIELDS} for a in result["attempts"]
                ],
                "extracted_text_sha256": result["extracted_text_sha256"],
                "result": claims,
            }
        )
    )


def artifact_map(result):
    """Map only declared artifacts, never enumerate an unrelated source folder."""
    original_root = result["output_dir"]
    path_type = (
        PureWindowsPath
        if "\\" in original_root or re.match(r"^[A-Za-z]:", original_root)
        else PurePosixPath
    )
    root = path_type(original_root)
    mapping = {}
    values = [result.get("raw_path"), result.get("extracted_text_path")]
    values += [row.get("raw_path") for row in result["attempts"]]
    for value in filter(None, values):
        path = path_type(value)
        relative = (
            path.relative_to(root).as_posix() if path.is_absolute() else path.as_posix()
        )
        # safe_path also rejects .., drive letters, backslashes and links.
        safe_path(Path(tempfile.gettempdir()).resolve(), relative)
        if relative in {"original.json", "source-fetch-result.json", "validation.json"}:
            raise DeliverableError("source artifact collides with package metadata")
        mapping[value] = relative
    return mapping


def _relocate(result, root, mapping):
    value = copy.deepcopy(result)
    value["output_dir"] = str(root)
    value["request"]["output_dir"] = str(root)
    for row in [value, *value["attempts"]]:
        for key in ("raw_path", "extracted_text_path"):
            if row.get(key):
                row[key] = str(safe_path(root, mapping[row[key]]))
    value["receipt_sha256"] = receipt_digest(value)
    return value


def validate_archive(root):
    """Rebase paths only in a disposable copy, then use the public offline CLI."""
    root = Path(root)
    result = read_json(root / "original.json")
    validate_receipt_shape(result)
    if result.get("schema_version") != "source-fetch-result/v1" or receipt_digest(
        result
    ) != result.get("receipt_sha256"):
        raise DeliverableError("original source receipt differs")
    mapping = artifact_map(result)
    for attempt in result["attempts"]:
        public_uri(attempt["url"])
        public_uri(attempt["final_url"])
        timestamp(attempt["requested_at"])
        if attempt.get("received_at"):
            timestamp(attempt["received_at"])
        if attempt.get("raw_path"):
            raw = safe_path(root, mapping[attempt["raw_path"]]).read_bytes()
            reject_secrets(raw)
            if (
                sha(raw) != attempt["raw_sha256"]
                or len(raw) != attempt["response_bytes"]
            ):
                raise DeliverableError("source attempt byte binding differs")
    with tempfile.TemporaryDirectory(prefix="stage1-source-replay-") as temp:
        # Resolve only our own temp root (macOS /var aliases /private/var).
        # Caller-provided roots still pass through the strict link guard.
        relocated_root = private_output(Path(temp).resolve())
        for relative in set(mapping.values()):
            destination = safe_path(relocated_root, relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(safe_path(root, relative), destination)
        relocated = _relocate(result, relocated_root, mapping)
        result_path = relocated_root / "source-fetch-result.json"
        write_json(result_path, relocated)
        command = [
            sys.executable,
            "-I",
            "-B",
            "-m",
            "research_hub",
            "source",
            "validate",
            str(result_path),
            "--json",
        ]
        completed = subprocess.run(
            command, capture_output=True, timeout=120, check=False
        )
        observation = {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout.decode("utf-8", errors="replace"),
            "stderr": completed.stderr.decode("utf-8", errors="replace"),
            "original_sha256": sha((root / "original.json").read_bytes()),
            "relocated_sha256": sha(result_path.read_bytes()),
            "network_acquisition": False,
        }
        try:
            report = json.loads(completed.stdout)
        except ValueError as exc:
            raise DeliverableError(
                "public source validator returned invalid JSON"
            ) from exc
        if (
            completed.returncode
            or report.get("valid") is not True
            or report.get("errors") != []
            or report.get("receipt_sha256") != relocated["receipt_sha256"]
            or report.get("source_version") != result["source_version"]
        ):
            raise DeliverableError(
                "public source semantic replay failed: " + str(report.get("errors"))
            )
    return result, mapping, observation


def stage_source(source, input_root, archive):
    path = safe_path(input_root, source["result_path"])
    raw = path.read_bytes()
    if sha(raw) != source["result_sha256"]:
        raise DeliverableError("source result changed")
    result = read_json(path)
    validate_receipt_shape(result)
    if Path(result["output_dir"]).resolve() != path.parent.resolve():
        raise DeliverableError(
            "source result must reside in its recorded output directory"
        )
    staged = {}
    for relative in set(artifact_map(result).values()):
        staged[relative] = safe_path(path.parent, relative).read_bytes()
        reject_secrets(staged[relative])
    archive.mkdir(parents=True, exist_ok=False)
    (archive / "original.json").write_bytes(raw)
    for relative, content in staged.items():
        target = safe_path(archive, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    _, _, observation = validate_archive(archive)
    write_json(archive / "validation.json", observation)


def validate_observation(archive, result, mapping, replay, *, saved_observation=None):
    """Check saved validator evidence against the original and fresh replay."""
    saved = (
        read_json(archive / "validation.json")
        if saved_observation is None
        else saved_observation
    )
    _keys(saved, replay, "saved source validation observation")
    command = saved["command"]
    if (
        not isinstance(command, list)
        or len(command) != 9
        or command[:7]
        != [sys.executable, "-I", "-B", "-m", "research_hub", "source", "validate"]
        or command[-1] != "--json"
        or saved["returncode"] != 0
        or saved["stderr"] != replay["stderr"]
        or saved["network_acquisition"] is not False
        or saved["original_sha256"] != replay["original_sha256"]
    ):
        raise DeliverableError("saved source validation observation differs")
    path = Path(command[7])
    if not path.is_absolute() or path.name != "source-fetch-result.json":
        raise DeliverableError("saved source validation command path differs")
    relocated = _relocate(result, path.parent, mapping)
    if saved["relocated_sha256"] != sha(canonical(relocated) + b"\n"):
        raise DeliverableError("saved source validation receipt differs")
    report, fresh = json.loads(saved["stdout"]), json.loads(replay["stdout"])
    _keys(report, fresh, "saved source validation report")
    timestamp(report["checked_at"])
    fresh.update(
        checked_at=report["checked_at"],
        result_path=str(path),
        output_dir=str(path.parent),
        receipt_sha256=relocated["receipt_sha256"],
    )
    if report != fresh:
        raise DeliverableError("saved source validation report differs from replay")


def _state(result, attempt, raw):
    text = raw.decode("utf-8", errors="ignore").casefold()
    if attempt.get("http_status") == 429:
        return "rate-limited"
    if attempt.get("http_status") in {404, 410}:
        return "not-found"
    if (
        any(
            word in text
            for word in (
                "purchase this article",
                "subscribe to read",
                "payment required",
            )
        )
        or attempt.get("http_status") == 402
    ):
        return "paywalled"
    if (
        any(
            word in text
            for word in (
                "sign in to continue",
                "log in to continue",
                "institutional login",
                "access through your institution",
                "verify you are human",
                "captcha",
                "cloudflare challenge",
            )
        )
        or attempt.get("http_status") == 401
        or any(
            marker in urlsplit(attempt["final_url"]).path.casefold()
            for marker in ("/login", "/signin", "/challenge", "/captcha")
        )
    ):
        return "login-page"
    if attempt.get("outcome") in {
        "network-error",
        "timeout",
        "redirect-error",
        "unsafe-url",
        "http-error",
    }:
        return "network-error"
    if attempt.get("http_status") == 403:
        # Access denial alone cannot establish a paid subscription requirement.
        return "network-error"
    if attempt.get("outcome") in {"parse-error", "response-too-large"}:
        return "parse-error"
    if attempt.get("raw_path") == result.get("raw_path") and result["status"] in {
        "available",
        "identity-mismatch",
    }:
        if result["status"] == "identity-mismatch":
            return "identity-mismatch"
        return {
            "full-text": "available",
            "abstract": "abstract-only",
            "metadata": "metadata-only",
        }[result["evidence_level"]]
    # Redirect/ancillary metadata is preserved, never promoted to full text.
    return (
        "metadata-only"
        if attempt.get("outcome") in {"success", "redirect", "parsed"}
        else "parse-error"
    )


def validate_paper_identity(paper, result):
    """Bind catalog identity to the request or the replayed source observation.

    A URL-only request does not assert that the fetched work has no DOI. Keep
    observed bibliographic identity separate from claim/evidence eligibility.
    """
    expected = result["expected_identity"]

    def title(value):
        return (
            " ".join(value.casefold().split()).rstrip(".")
            if isinstance(value, str)
            else ""
        )

    catalog_title = title(paper["title"])
    if title(expected.get("title")) != catalog_title:
        if not (
            result["status"] == "available"
            and result["identity_status"] != "mismatch"
            and title(result["observed_identity"].get("title")) == catalog_title
        ):
            raise DeliverableError(
                "source expected identity differs from canonical work"
            )
        # A lookup title can refer to an earlier edition. The independently
        # replayed own-source title binds this catalog entry; retain the original
        # unverified state and the requested/observed DOI checks below.
    requested_doi = expected.get("doi", "")
    catalog_doi = paper["doi"] or ""
    if requested_doi == catalog_doi:
        return
    observed_doi = result["observed_identity"].get("doi", "")
    if (
        not requested_doi
        and catalog_doi == observed_doi
        and re.fullmatch(r"10\.\d{4,9}/\S+", observed_doi)
        and result["status"] == "available"
        and result["identity_status"] != "mismatch"
    ):
        # The saved source validator has already replayed the observed DOI.
        # Unverified title identity stays unverified; this is not sufficiency.
        return
    raise DeliverableError("source expected identity differs from canonical work")


def source_records(source, paper, archive, runtime):
    result, mapping, replay = validate_archive(archive)
    validate_observation(archive, result, mapping, replay)
    validate_paper_identity(paper, result)
    rows = []
    for attempt in result["attempts"]:
        relative = mapping.get(attempt.get("raw_path"))
        raw = safe_path(archive, relative).read_bytes() if relative else b""
        state = _state(result, attempt, raw)
        selected = attempt.get("raw_path") == result.get("raw_path") and bool(relative)
        if (
            selected
            and result["status"] == "available"
            and result["evidence_level"] == "full-text"
            and state != "available"
        ):
            raise DeliverableError(
                "restricted response cannot be promoted to full text"
            )
        kind = (
            "pdf"
            if raw.startswith(b"%PDF-")
            else "html"
            if "html" in attempt["content_type"].casefold()
            else "text"
        )
        if (
            state == "available"
            and "pdf" in attempt["content_type"].casefold()
            and kind != "pdf"
        ):
            raise DeliverableError("HTML or invalid bytes disguised as PDF")
        # HTTP failures were never passed to a document parser. The dependency
        # wrapper records parser dispatch, including unsuccessful parse attempts.
        parsed = attempt["outcome"] in {"parsed", "parse-error"} or (
            attempt["outcome"] == "inaccessible" and attempt["http_status"] == 200
        )
        parser = (
            "pdfplumber"
            if parsed and (kind == "pdf" or "pdf" in attempt["content_type"].casefold())
            else "research_hub"
            if parsed
            else None
        )
        rows.append(
            {
                "source_id": source["source_id"],
                "attempt": attempt["sequence"],
                "work_id": source["work_id"],
                "version_id": source["version_id"],
                "requested_uri": attempt["url"],
                "resolved_uri": attempt["final_url"],
                "observed_at": attempt.get("received_at") or attempt["requested_at"],
                "content_type": attempt["content_type"],
                "access_note": source["access_note"],
                "parser": parser,
                "parser_version": runtime["packages"][parser]["version"]
                if parser
                else None,
                "parser_attempted": parsed,
                "byte_count": attempt.get("response_bytes"),
                "sha256": attempt.get("raw_sha256"),
                "state": state,
                "outcome": attempt["outcome"],
                "error": attempt.get("error"),
                "source_version": result["source_version"] if selected else None,
                "evidence_level": result["evidence_level"] if selected else "metadata",
                "identity_status": result["identity_status"]
                if selected
                else "unverified",
                "archive_path": "sources/" + source["source_id"] + "/" + relative
                if relative
                else None,
                "paper_path": f"papers/{source['work_id']}__{source['version_id']}__{source['source_id']}.{kind if kind != 'text' else 'txt'}"
                if state == "available"
                else None,
            }
        )
    return rows, result, mapping
