"""Pinned ordinary Stage 2 packages for reading, without project adoption."""

from copy import deepcopy
from html import escape
from pathlib import Path
import re

from stage1_deliverable.common import canonical, sha
from stage2_check.contracts import decode_json
from stage2_workflow.decision_cards import derive_decision_cards
from stage2_workflow.decision_card_views import render_decision_cards_html
from stage2_workflow.delivery import MANIFEST, inspect_delivery

_NAV_CSS = b".stage2-reading-nav{flex-wrap:wrap}"


class Stage2ReadingRegistry:
    """Seal independently saved reports; this object grants no selection authority."""

    def __init__(self, config_path, expected_sha256):
        self._path = Path(config_path)
        if (
            self._path.is_symlink()
            or not isinstance(expected_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256 or "")
        ):
            raise ValueError("Stage2 reading configuration receipt invalid")
        self._raw = self._path.read_bytes()
        if len(self._raw) > 65536 or sha(self._raw) != expected_sha256:
            raise ValueError("Stage2 reading configuration receipt differs")
        config = decode_json(self._raw, "Stage2 reading configuration")
        if (
            not isinstance(config, dict)
            or set(config) != {"kind", "schema_version", "readings"}
            or config["kind"] != "Stage2ReadingConfiguration"
            or config["schema_version"] != "1.0.0"
            or not isinstance(config["readings"], list)
            or not 1 <= len(config["readings"]) <= 8
        ):
            raise ValueError("Stage2 reading configuration shape differs")
        self._config_sha256 = expected_sha256
        self._entries = deepcopy(config["readings"])
        refs = set()
        for row in self._entries:
            if (
                not isinstance(row, dict)
                or set(row)
                != {"ref", "label", "delivery_root", "delivery_manifest_sha256"}
                or not isinstance(row["ref"], str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", row["ref"])
                or row["ref"] in refs
                or not isinstance(row["label"], str)
                or not 1 <= len(row["label"]) <= 160
                or row["label"] != row["label"].strip()
                or any(ord(c) < 32 or ord(c) == 127 for c in row["label"])
                or not isinstance(row["delivery_root"], str)
                or not Path(row["delivery_root"]).is_absolute()
                or Path(row["delivery_root"]).is_symlink()
                or not isinstance(row["delivery_manifest_sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", row["delivery_manifest_sha256"])
            ):
                raise ValueError("Stage2 reading entry invalid or duplicated")
            refs.add(row["ref"])
        self._assets, self._references = self._build()

    def _build(self):
        assets, references = {}, []
        for row in self._entries:
            checked = inspect_delivery(
                row["delivery_root"], row["delivery_manifest_sha256"]
            )
            root, manifest = checked["root"], checked["manifest"]
            files = {item["path"]: item for item in manifest["files"]}
            saved = {}
            for name in ("selection.json", "selection.md"):
                path = root / name
                raw = path.read_bytes()
                if (
                    path.is_symlink()
                    or sha(raw) != files[name]["sha256"]
                    or len(raw) != files[name]["size"]
                ):
                    raise ValueError("Stage2 reading source changed during inspection")
                saved[name] = raw
            manifest_raw = (root / MANIFEST).read_bytes()
            if decode_json(manifest_raw, "Stage2 reading manifest") != manifest:
                raise ValueError("Stage2 reading manifest changed during inspection")
            if (
                decode_json(saved["selection.json"], "Stage2 reading selection")
                != checked["selection"]
            ):
                raise ValueError("Stage2 reading selection changed during inspection")
            cards = derive_decision_cards(checked["selection"])
            cards_raw = canonical(cards)
            binding = dict(
                kind="Stage2ReadOnlyReading",
                schema_version="1.0.0",
                ref=row["ref"],
                label=row["label"],
                source_kind="independent-saved-stage2",
                configuration_sha256=self._config_sha256,
                delivery_manifest_sha256=manifest["manifest_sha256"],
                delivery_manifest_file_sha256=sha(manifest_raw),
                workflow_manifest_sha256=manifest["workflow_manifest_sha256"],
                workflow_head_sha256=manifest["workflow_head_sha256"],
                snapshot_sha256=manifest["snapshot_sha256"],
                selection_sha256=manifest["selection_sha256"],
                selection_file_sha256=sha(saved["selection.json"]),
                report_file_sha256=sha(saved["selection.md"]),
                decision_cards_sha256=sha(cards_raw),
                delivery_status=manifest["delivery_status"],
                direction_count=len(cards["cards"]),
                recommendation_count=len(checked["selection"]["recommendations"]),
                reading_only=True,
                stage1_lineage_attested=False,
                selection_authority=False,
                execution_authorized=False,
            )
            prefix = "/project-stage2-readings/" + row["ref"] + "/"
            binding_raw = canonical(binding)
            # Only trusted escaped rendering and plain saved text are published.
            # The package's potentially active HTML and arbitrary paths are not served.
            page = (
                '<!doctype html><html lang="en"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                "<title>" + escape(row["label"], quote=True) + "</title>"
                '<link rel="stylesheet" href="/project-stage2-selection.css">'
                '<link rel="stylesheet" href="reading.css"></head><body><main>'
                '<nav class="stage2-reading-nav"><a href="/projects.html">Return to workspace</a> · '
                '<a href="selection.md">Full saved report</a> · '
                '<a href="selection.json">Saved selection JSON</a> · '
                '<a href="binding.json">Package identity</a></nav>'
                "<h1>" + escape(row["label"], quote=True) + "</h1>"
                "<p>Independent Stage 2 report. This reading entry does not link the report "
                "to this project's Stage 1 run or record a research choice.</p>"
                "<p>Directions: "
                + str(binding["direction_count"])
                + "; recommended candidates: "
                + str(binding["recommendation_count"])
                + ". Reading only; no research or experiment is started here.</p>"
                + render_decision_cards_html(cards)
                + "<details><summary>Full saved report, review comments and limitations</summary>"
                '<pre translate="no">'
                + escape(saved["selection.md"].decode("utf-8"), quote=True)
                + "</pre></details><details><summary>Source and version binding</summary><pre>"
                + escape(binding_raw.decode("utf-8"), quote=True)
                + "</pre></details></main></body></html>"
            ).encode("utf-8")
            assets.update(
                {
                    prefix + "index.html": page,
                    prefix + "reading.css": _NAV_CSS,
                    prefix + "binding.json": binding_raw,
                    prefix + "decision-cards.json": cards_raw,
                    prefix + "selection.json": saved["selection.json"],
                    prefix + "selection.md": saved["selection.md"],
                }
            )
            references.append(
                dict(
                    kind="Stage2ReadingReference",
                    schema_version="1.0.0",
                    ref=row["ref"],
                    label=row["label"],
                    url=prefix + "index.html",
                    binding_sha256=sha(binding_raw),
                    delivery_manifest_sha256=manifest["manifest_sha256"],
                    direction_count=binding["direction_count"],
                    recommendation_count=binding["recommendation_count"],
                    source_kind="independent-saved-stage2",
                    reading_only=True,
                    stage1_lineage_attested=False,
                    selection_authority=False,
                    execution_authorized=False,
                )
            )
        if sum(map(len, assets.values())) > 32 * 1024 * 1024:
            raise ValueError("Stage2 reading snapshot exceeds bounded size")
        return assets, references

    def snapshot(self):
        """Recheck before listener allocation, then return independent sealed copies."""
        if self._path.is_symlink() or self._path.read_bytes() != self._raw:
            raise ValueError("Stage2 reading configuration changed before serving")
        assets, references = self._build()
        if assets != self._assets or references != self._references:
            raise ValueError("Stage2 reading snapshot changed before serving")
        return dict(assets), deepcopy(references)
