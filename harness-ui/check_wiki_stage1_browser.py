"""Read Stage 1 in the production Wiki against a same-checkout, zero-call Core fixture."""
import argparse
from collections import Counter
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from unittest.mock import patch

from PIL import Image

from check_wiki_home_browser import Browser, REPO, UI, process, wait

PLUGIN = REPO / "plugins/auto-research-agent"
sys.path.insert(0, str(PLUGIN / "tests"))
from current_core_stage12_fixtures import current_core_stage1_case  # noqa: E402


class Stage1Browser(Browser):
    def __init__(self, port):
        super().__init__(port)
        self.clicks = []
        self.readbacks = []

    def click(self, selector):
        attempt = {"selector":selector, "dispatched":False}
        self.clicks.append(attempt)
        super().click(selector)
        attempt["dispatched"] = True

    def write_trace(self, evidence, error):
        counts = Counter(click["selector"] for click in self.clicks)
        trace = {"click_count":len(self.clicks), "by_selector":dict(counts), "clicks":self.clicks,
                 "readbacks":self.readbacks, "failure":repr(error) if error else None}
        (evidence / "stage1-click-trace.json").write_text(json.dumps(trace,indent=2,ensure_ascii=False), encoding="utf-8")


def state_counts(root):
    uri = (root / "project-intake.sqlite").as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        return {table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in ("intake_actions", "intake_events")}

def stage2_receipt(root, ref):
    uri = (root / "project-intake.sqlite").as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        rows = db.execute("""SELECT receipt FROM intake_actions WHERE project=?
            AND json_extract(receipt, '$.kind')='stage2-record-connection'""", (ref,)).fetchall()
        assert len(rows) == 1, rows
        receipt = json.loads(rows[0][0])
        return {key:receipt[key] for key in ("kind", "project_ref", "status", "connection_id", "execution_authorized")}


def compare(evidence, design, name):
    with Image.open(design / f"new-s1-{name}.png") as left, Image.open(evidence / f"stage1-{name}.png") as right:
        assert left.width == right.width == 1440
        panel = Image.new("RGB", (2880, max(left.height, right.height)), "white")
        panel.paste(left, (0, 0))
        panel.paste(right, (1440, 0))
        panel.save(evidence / f"compare-{name}-design-left.png")


def stage1_browser(browser, url, fixture, evidence, design):
    browser.origin = url.rstrip("/")
    ref = fixture["project_ref"]
    browser.open(url + f"#{ref}?stage=1&lang=zh-CN")
    browser.cdp("Emulation.setDeviceMetricsOverride", width=1440, height=1560, deviceScaleFactor=1, mobile=False)
    browser.cdp("Emulation.setEmulatedMedia", features=[{"name":"prefers-reduced-motion","value":"reduce"}])
    browser.ws.settimeout(90)
    try:
        wait(lambda: browser.js("!!document.querySelector('[data-s1-paper], [data-shell-state=error]')"), timeout=120)
        assert browser.js("!!document.querySelector('[data-s1-paper]')")
    except AssertionError as error:
        status = browser.js("""({hash:location.hash, summary:document.querySelector('[data-shell-details] pre')?.textContent,
            error:document.querySelector('.live-error')?.textContent, state:document.querySelector('[data-shell-state]')?.dataset.shellState,
            refreshAvailable:!!document.querySelector('.hs-content .live-error [data-live-action="refresh"]:not(:disabled)')})""")
        print(json.dumps({"stage1_not_loaded":status,"browser_errors":browser.errors}, ensure_ascii=False), flush=True)
        requests = browser.js("""performance.getEntriesByType('resource').filter(row=>row.name.includes('/api/'))
            .map(row=>({path:new URL(row.name).pathname, status:row.responseStatus, ms:Math.round(row.duration)}))""")
        print(json.dumps({"api_requests":requests}, ensure_ascii=False), flush=True)
        raise error
    meta = browser.get("/v7-case.json")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    assert meta["harness_head"] == head and meta["execution_authorized"] is False
    assert not any(meta["run_limits"].values())
    assert not any(meta[key] for key in ("source_worker_requested", "query_runtime_registered", "content_model_registered"))
    binding = browser.get("/host-binding.json")
    assert binding["v9"]["modules"]["wiki-stage1.js"] == sha256((UI / "wiki-stage1.js").read_bytes()).hexdigest()
    overview = browser.get(f"/api/projects/{ref}/overview")
    project, delivery = overview["project"], overview["stage1"]["delivery"]["canonical_package"]
    atlas_route = f"/api/projects/{ref}/stage1/atlas/{project['input_version']}/{project['revision']}/{delivery['artifact_ref']}/{delivery['manifest_sha256']}"
    atlas = browser.get(atlas_route)
    index = atlas["payload"]["index"]
    assert (atlas["project_ref"], atlas["input_version"], atlas["revision"], atlas["manifest_sha256"]) == (
        ref, project["input_version"], project["revision"], delivery["manifest_sha256"])
    assert project["execution_authorized"] is False
    assert index["papers"] and index["claims"] and index["coverage"]
    assert browser.js("""document.querySelector('[data-wiki-shell]').nextElementSibling
        .querySelector('span').textContent === '这一段还没有记录'""")
    assert browser.js("document.querySelectorAll('[data-s1-paper]').length") == len(index["papers"])
    assert browser.js("document.documentElement.scrollWidth <= innerWidth")

    paper = index["papers"][0]
    key = paper["work_id"]
    mode_error = None
    diagnostics = "document.querySelector('[data-wiki-s1-atlas]')?.v7Diagnostics?.()"
    status = wait(lambda: browser.js(f"""{diagnostics} || (document.querySelector('[data-s1-fallback]:not([hidden])')?.textContent)"""))
    browser.click("[data-s1-paper]")
    assert browser.js("document.querySelector('[data-s1-paper][aria-pressed=true]').dataset.s1Paper") == key
    browser.readbacks.append({"after_click":len(browser.clicks), "selected_source":key})
    if not isinstance(status, dict) or status["mode"] != 3:
        mode_error = {"fallback":status, "error":browser.js("document.querySelector('[data-wiki-s1-atlas]')?.dataset.wikiS1GraphError")}
    else:
        assert status["papers"] == len(index["papers"]) and status["depthRange"] > 0
        browser.click("[data-s1-group]:not([data-s1-group=''])")
        group = browser.js("document.querySelector('[data-s1-group][aria-pressed=true]').dataset.s1Group")
        assert group
        browser.readbacks.append({"after_click":len(browser.clicks), "group":group})
        browser.click("[data-s1-paper]")
        for mode in (3,2,3):
            browser.click(f"[data-s1-mode='{mode}']")
            current = browser.js(diagnostics)
            assert current["mode"] == mode and current["focus"] == {"kind":"paper", "key":key}
            assert current["navigation"]["mode"] == ("pan" if mode == 2 else "rotate")
            assert browser.js("document.querySelector('[data-s1-paper][aria-pressed=true]').dataset.s1Paper") == key
            assert browser.js("document.querySelector('[data-s1-group][aria-pressed=true]').dataset.s1Group")
            browser.readbacks.append({"after_click":len(browser.clicks), "atlas_mode":mode, "selected_source":key})
            if mode == 2:
                browser.screenshot(evidence / "stage1-graph-2d.png")
        labels = "[data-wiki-s1-atlas] button[data-node-kind='paper']"
        wait(lambda: browser.js(f"[...document.querySelectorAll({json.dumps(labels)})].some(el => getComputedStyle(el).visibility==='visible')"))
        browser.click(labels)
        assert browser.js(diagnostics)["focus"]["key"] == key
        browser.readbacks.append({"after_click":len(browser.clicks), "atlas_focus":key})
    browser.screenshot(evidence / "stage1-sources.png")

    browser.click("[data-s1-selected] [data-s1-tab=evidence]")
    browser.see("[data-s1-claim]")
    claims = [claim for claim in index["claims"] if claim["work_id"] == key and claim["version_id"] == paper["version_id"]]
    assert browser.js("document.querySelectorAll('[data-s1-claim]').length") == len(claims)
    located = [claim for claim in claims if claim["locator"]]
    assert located and browser.js("[...document.querySelectorAll('[data-s1-claim]')].some(node=>node.textContent.includes('保存文本第'))")
    assert browser.js("document.querySelectorAll('[data-s1-review=unchecked]').length") == len(claims)
    evidence_links = browser.js("""[...document.querySelectorAll('[data-s1-claim]')].map(row=>row.querySelector('a')?.href || null)""")
    assert any(not claim["locator"] for claim in claims), "Expected at least one claim without a saved locator"
    assert all(link is None for claim,link in zip(claims,evidence_links) if not claim["locator"] or not claim.get("source_id"))
    browser.readbacks.append({"after_click":len(browser.clicks), "evidence_rows":len(claims), "located":len(located),
                             "evidence_links":sum(link is not None for link in evidence_links)})
    assert browser.js("document.documentElement.scrollWidth <= innerWidth")
    browser.screenshot(evidence / "stage1-evidence.png")
    browser.click("[data-s1-check=supports]")
    browser.see("[data-wiki-s1] [role=status]")
    browser.readbacks.append({"after_click":len(browser.clicks), "supports_filter_empty":True})
    browser.click("#wiki-s1-synthesis")
    browser.see(".wiki-s1-synthesis")
    assert "当前交付没有跨文献综合记录" in browser.js("document.querySelector('.wiki-s1-synthesis').textContent")
    assert browser.js("document.querySelectorAll('.wiki-s1-bar').length") == len(index["coverage"])
    assert browser.js("document.documentElement.scrollWidth <= innerWidth")
    browser.readbacks.append({"after_click":len(browser.clicks), "synthesis_missing":True, "groups":len(index["coverage"])})
    browser.screenshot(evidence / "stage1-synthesis.png")
    for name in ("sources", "evidence", "synthesis"):
        compare(evidence, design, name)

    browser.js("""const field = document.querySelector('[data-language]');
       field.value='en';field.dispatchEvent(new Event('change',{bubbles:true}));""")
    browser.see('[data-live-spatial]')
    assert not browser.js("!!document.querySelector('[data-wiki-s1]')")
    assert not browser.writes and not browser.external and not browser.errors, (browser.writes, browser.external, browser.errors)
    result = {"head":head, "project_ref":ref, "input_version":project["input_version"],
              "brief_sha256":project["brief_sha256"], "atlas_manifest_sha256":delivery["manifest_sha256"],
              "sources":len(index["papers"]), "claims":len(index["claims"]), "located":len(located),
              "groups":len(index["coverage"]), "model_calls":0, "search_calls":0,
              "browser_writes":len(browser.writes), "external_requests":len(browser.external),
              "native_3d_2d_3d":mode_error is None, "graph_failure":mode_error}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chrome", type=Path, required=True)
    parser.add_argument("--design", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--scratch-parent", type=Path, required=True)
    parser.add_argument("--normal-listener", action="store_true",
                        help="Observe the standard Wiki launcher with its automatic Stage 2 receipt.")
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    assert args.scratch_parent.is_dir()
    with tempfile.TemporaryDirectory(prefix="s1-", dir=args.scratch_parent) as scratch:
        root = Path(scratch).resolve()
        # The fixture follows tempfile.gettempdir() and requires a short, private Windows path.
        original_temp = tempfile.tempdir
        tempfile.tempdir = str(root)
        try:
            with patch("test_project_stage1_delivery.authenticate",
                       lambda token: "local-viewer" if token == "alice-token" else None):
                with current_core_stage1_case(screened=True) as fixture:
                    run(fixture, root, args)
        finally:
            tempfile.tempdir = original_temp


def run(fixture, root, args):
    case = fixture["case"]
    before = state_counts(case.intake_root)
    (root / "incoming").mkdir()
    helper = PLUGIN / "cli/research_workspace_native/atlas_local_source.py"
    # Scope the fixture listener to Stage 1 reads. An ordinary full Wiki listener
    # also records a Stage 2 connection when it first reads an eligible handoff.
    launch = """import sys
sys.path.insert(0, sys.argv.pop(1))
import run_v9
original = run_v9.run_v7.configure_host_lifecycle
def configure(host, services):
    original(host, services)
    host.project_stage2.receive_current = False
run_v9.run_v7.configure_host_lifecycle = configure
raise SystemExit(run_v9.main())
"""
    entry = [str(UI / "run_v9.py")] if args.normal_listener else ["-c", launch, str(UI)]
    server = [sys.executable, "-B", *entry, "--repo", str(REPO),
              "--source-helper-sha256", sha256(helper.read_bytes()).hexdigest(),
              "--projects-root", str(case.intake_root), "--ui-state-root", str(root / "state"),
              "--incoming-root", str(root / "incoming"), "--run-limits", str(UI / "zero-limits.json"),
              "--port", "0"]
    host_log = root / "host.log"
    profile = root / "chrome"
    chrome = [str(args.chrome), "--headless", "--disable-background-networking", "--no-first-run",
              "--enable-unsafe-swiftshader", "--use-angle=swiftshader",
              "--remote-debugging-port=0", f"--user-data-dir={profile}", "about:blank"]

    with process(server, host_log) as host:
        def url_ready():
            assert host.poll() is None, host_log.read_text(encoding="utf-8", errors="replace")
            return next((json.loads(line)["url"] for line in host_log.read_text(encoding="utf-8").splitlines()
                         if line.startswith("{") and '"url"' in line), None)

        url = wait(url_ready, timeout=40)
        profile_name = "normal listener" if args.normal_listener else "scoped listener, automatic Stage 2 receipt disabled"
        print(f"Built Wiki Host ready against the persisted engineering fixture ({profile_name}).", flush=True)
        with process(chrome, root / "chrome.log"):
            port_file = profile / "DevToolsActivePort"
            port = wait(lambda: port_file.read_text().splitlines()[0] if port_file.exists() else None)
            browser = Stage1Browser(port)
            failure = None
            try:
                result = stage1_browser(browser, url, fixture, args.evidence, args.design)
            except Exception as error:
                failure = error
                raise
            finally:
                browser.write_trace(args.evidence, failure)
                browser.ws.close()
    after = state_counts(case.intake_root)
    result["server_counts_before"] = before
    result["server_counts_after"] = after
    result["server_mutations"] = {key:after[key]-count for key,count in before.items()}
    result["query_runner_calls"] = case.runner.call_count
    result["source_fixture"] = "current_core_stage1_case(screened=True)"
    result["fixture_automatic_stage2_receipt"] = args.normal_listener
    if args.normal_listener:
        result["observed_stage2_receipt"] = stage2_receipt(case.intake_root, fixture["project_ref"])
    (args.evidence / "stage1-observations.json").write_text(json.dumps(result,indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)
    try:
        assert case.runner.call_count == 0, result
        if args.normal_listener:
            receipt = result["observed_stage2_receipt"]
            assert receipt["status"] == "saved" and receipt["execution_authorized"] is False, result
            assert result["server_mutations"] == {"intake_actions":1, "intake_events":2}, result
        else:
            assert after == before, result
        assert result["native_3d_2d_3d"], result["graph_failure"]
    except AssertionError as error:
        browser.write_trace(args.evidence, error)
        raise
    print("PASS built Wiki V1 Stage 1: source, native atlas, evidence, synthesis, and English compatibility.")


if __name__ == "__main__":
    main()
