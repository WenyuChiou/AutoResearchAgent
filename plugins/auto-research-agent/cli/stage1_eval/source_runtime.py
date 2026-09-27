"""Check the PDF reader before model calls; bind its versions and Python bytes."""

import importlib
import importlib.metadata
import io
import json

from .common import EvaluationError, sha
from .runtime import installed_package_sha256

PROBE_TEXT = "Stage1 public PDF parser preflight"


def probe_pdf():
    """One deterministic text page, with offsets computed from the actual bytes."""
    stream = f"BT /F1 12 Tf 30 100 Td ({PROBE_TEXT}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 200] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length "
        + str(len(stream)).encode()
        + b" >>\nstream\n"
        + stream
        + b"\nendstream",
    ]
    raw = b"%PDF-1.4\n"
    offsets = [0]
    for number, body in enumerate(objects, 1):
        offsets.append(len(raw))
        raw += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(raw)
    raw += b"xref\n0 6\n0000000000 65535 f \n"
    raw += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    return (
        raw + f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )


def source_runtime_preflight():
    try:
        parser = importlib.import_module("pdfplumber")
        raw = probe_pdf()
        with parser.open(io.BytesIO(raw)) as pdf:
            pages = [page.extract_text() for page in pdf.pages]
        if pages != [PROBE_TEXT]:
            raise ValueError("the PDF text probe did not return its exact sentinel")
        modules = {
            module: {
                "version": importlib.metadata.version(distribution),
                "python_tree_sha256": installed_package_sha256(module),
            }
            for module, distribution in (
                ("pdfplumber", "pdfplumber"),
                ("pdfminer", "pdfminer.six"),
            )
        }
    except Exception as exc:
        raise EvaluationError(
            "PDF source-runtime preflight failed before evaluation: "
            f"{type(exc).__name__}: {exc}. Install the declared evaluator PDF dependencies; "
            "a missing parser is not unavailable scientific evidence."
        ) from exc
    return {
        "kind": "Stage1SourceRuntimePreflight.v1",
        "modules": modules,
        "probe_pdf_sha256": sha(raw),
        "probe_text_sha256": sha(PROBE_TEXT.encode()),
        "probe_pages": 1,
        "scope": "Text PDF parser availability; not OCR, source access, or scientific support.",
    }


if __name__ == "__main__":
    print(json.dumps(source_runtime_preflight(), sort_keys=True))
