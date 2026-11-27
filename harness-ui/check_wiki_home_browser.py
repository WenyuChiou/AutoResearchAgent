"""Exercise Wiki V1 HOME against an isolated, zero-limit ProjectHost in Chrome."""
import argparse
import base64
from collections import Counter
from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from time import monotonic, sleep
from urllib.request import urlopen

from PIL import Image
from websocket import create_connection

UI = Path(__file__).resolve().parent
REPO = UI.parent


def wait(read, timeout=20):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        value = read()
        if value:
            return value
        sleep(.08)
    raise AssertionError("Timed out waiting for " + repr(read))


@contextmanager
def process(args, log):
    with log.open("wb") as output:
        with subprocess.Popen(args, cwd=REPO, stdout=output, stderr=subprocess.STDOUT) as child:
            try:
                yield child
            finally:
                if child.poll() is None:
                    child.terminate()
                    child.wait(timeout=10)


class Browser:
    def __init__(self, debugger):
        tabs = json.load(urlopen(f"http://127.0.0.1:{debugger}/json/list", timeout=5))
        self.ws = create_connection(next(tab["webSocketDebuggerUrl"] for tab in tabs if tab["type"] == "page"),
                                    suppress_origin=True, timeout=15)
        self.seq = 0
        self.writes = []
        self.external = []
        self.errors = []
        self.origin = None
        for domain in ("Page", "Runtime", "Network"):
            self.cdp(domain + ".enable")
        self.cdp("Emulation.setDeviceMetricsOverride", width=1440, height=1320, deviceScaleFactor=1, mobile=False)

    def cdp(self, method, **params):
        self.seq += 1
        self.ws.send(json.dumps({"method": method, "id": self.seq, "params": params}))
        while True:
            packet = json.loads(self.ws.recv())
            if packet.get("id") == self.seq:
                assert "error" not in packet, packet
                return packet["result"]
            if packet.get("method") == "Runtime.exceptionThrown":
                self.errors.append(packet["params"]["exceptionDetails"])
            if packet.get("method") == "Network.requestWillBeSent":
                request = packet["params"]["request"]
                if self.origin and request["url"].startswith(("http:", "https:")):
                    if not request["url"].startswith(self.origin):
                        self.external.append(request["url"])
                    if request["method"] != "GET":
                        self.writes.append((request["method"], request["url"].removeprefix(self.origin)))

    def js(self, expression):
        result = self.cdp("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
        assert "exceptionDetails" not in result, result["exceptionDetails"].get("text")
        return result["result"].get("value")

    def see(self, selector):
        return wait(lambda: self.js(f"!!document.querySelector({json.dumps(selector)})"))

    def click(self, selector):
        self.see(selector)
        point = self.js(f"""(() => {{
          const item = document.querySelector({json.dumps(selector)});
          if(item.disabled) return null;
          item.scrollIntoView({{block:'center'}});
          const {{x,y,width,height}} = item.getBoundingClientRect();
          return [x+width/2,y+height/2];
        }})()""")
        assert point, selector
        x, y = point
        for event in ("mousePressed", "mouseReleased"):
            self.cdp("Input.dispatchMouseEvent", type=event, x=x, y=y, button="left", clickCount=1)

    def open(self, url):
        self.cdp("Page.navigate", url=url)
        wait(lambda: self.js(f"location.href === {json.dumps(url)} && document.readyState === 'complete'"))

    def go_home(self):
        # DESIGN 8.1: "工作台" stays on the open topic; the home table is "全部项目…" in the topic menu.
        self.click(".v1-switch > summary")
        self.click("[data-v1-home]")

    def home(self):
        self.see('[data-wiki-home] input:not(:disabled)')
        assert self.js("innerWidth === 1440 && document.documentElement.scrollWidth <= innerWidth")

    def screenshot(self, target):
        self.js("window.scrollTo(0,0)")
        self.js("document.fonts.ready.then(() => true)")
        result = self.cdp("Page.captureScreenshot", format="png", captureBeyondViewport=False)
        target.write_bytes(base64.b64decode(result["data"]))

    def get(self, path):
        return self.js(f"""fetch({json.dumps(path)}, {{headers:{{Authorization:'Bearer '+window.RESEARCH_PROJECTS.credential}}}})
            .then(response => {{if(!response.ok) throw Error(response.status);return response.json()}})""")


def check(browser, url, evidence):
    browser.origin = url.removesuffix("/")
    browser.open(url)
    browser.home()
    meta = browser.get("/v7-case.json")
    assert meta["harness_head"] == subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    assert meta["execution_authorized"] is False and not any(meta["run_limits"].values())
    assert not any(meta[key] for key in ("source_worker_requested", "query_runtime_registered", "content_model_registered"))
    binding = browser.get("/host-binding.json")
    for file_name in ("wiki-home.js", "wiki-harness-record.js"):
        assert binding["v9"]["modules"][file_name] == sha256((UI / file_name).read_bytes()).hexdigest()
    for route in ("/app.js", "/runtime.css"):
        with urlopen(browser.origin + route, timeout=5) as response:
            assert sha256(response.read()).hexdigest() == binding["served_files"][route]
    assert "还没有保存的课题" in browser.js("document.querySelector('.wiki-home-empty').textContent")
    assert not browser.get("/api/projects")
    browser.screenshot(evidence / "home-empty-1440.png")

    titles = ["人口老龄化与家庭消费结构", "家庭用水与节水措施", "城市公交可达性与通勤时间"]
    for index, title in enumerate(titles):
        browser.click("#wiki-home-topic")
        browser.cdp("Input.insertText", text=title)
        if index == 0:
            browser.click("[data-wiki-home-more] summary")
            browser.click("#wiki-home-question")
            browser.cdp("Input.insertText", text="不同年龄家庭的消费结构有哪些差异？")
        browser.click("[data-wiki-home-create] button")
        try:
            wait(lambda: browser.js("!document.querySelector('[data-wiki-home]') && location.hash.includes('stage=1')"))
        except AssertionError as error:
            state = browser.js("""({hash:location.hash, topic:document.querySelector('#wiki-home-topic')?.value,
                alert:document.querySelector('[role=alert]')?.textContent})""")
            raise AssertionError((state, browser.writes, [item["text"] for item in browser.errors])) from error
        browser.go_home()
        try:
            browser.home()
        except AssertionError as error:
            raise AssertionError(browser.js("""({hash:location.hash, home:!!document.querySelector('[data-wiki-home]'),
                alert:document.querySelector('[data-v1-alert],[role=alert],.wiki-home-message')?.innerText,
                input:document.querySelector('#wiki-home-topic')?.disabled})""")) from error
    rows = browser.get("/api/projects")
    assert [row["topic"] for row in rows] == titles, rows
    assert all(row["execution_authorized"] is False for row in rows)
    assert all(row["revision"] == 2 and row["input_version"] == 1 for row in rows), rows
    assert browser.js("[...document.querySelectorAll('.hs-stage-nav button')].slice(3).every(node => !node.getClientRects().length)")
    assert browser.js("document.querySelectorAll('[data-wiki-home-origin]').length") == len(titles)
    assert browser.js("[...document.querySelectorAll('[data-wiki-home-origin]')].every(row => row.textContent.includes('还没有运行'))")
    browser.click('[data-wiki-home-filter="local"]')
    assert browser.js("document.querySelector('[data-wiki-home-filter=local]').getAttribute('aria-pressed')") == "true"
    browser.click('[data-wiki-home-filter="all"]')

    first = rows[0]["project_ref"]
    browser.click(f'tr [data-wiki-home-open="{first}"]')
    wait(lambda: browser.js(f"location.hash.startsWith('#{first}?') && !document.querySelector('[data-wiki-home]')"))
    project = browser.get(f"/api/projects/{first}/overview")["project"]
    assert project["brief"]["needs"][0]["question"] == "不同年龄家庭的消费结构有哪些差异？"
    browser.cdp("Page.reload")
    browser.see("[data-live-project-identity]")
    wait(lambda: browser.js(f"document.querySelector('[data-live-project-identity]')?.textContent.includes('{first}')"))
    browser.go_home()
    browser.home()
    browser.screenshot(evidence / "home-projects-1440.png")
    assert browser.js("document.querySelector('.wiki-home-resume h3').textContent") == titles[0]
    browser.click(".wiki-home-resume button")
    wait(lambda: browser.js(f"location.hash.startsWith('#{first}?')"))
    browser.js("history.back(); true")
    browser.home()
    assert len(browser.get("/api/projects")) == len(titles)
    assert Counter(browser.writes) == {("POST", "/api/projects"):len(titles)}, browser.writes
    assert not browser.external, browser.external
    assert not browser.errors, browser.errors


def check_legacy(browser, url, cases):
    browser.origin = url.rstrip("/")
    browser.open(url)
    initial_writes = len(browser.writes)
    for language, title, button_label in cases:
        browser.see("[data-language]")
        browser.js(f"""(() => {{
          const field = document.querySelector('[data-language]');
          field.value = {json.dumps(language)};
          field.dispatchEvent(new Event('change', {{bubbles:true}}));
        }})()""")
        browser.see('[data-live-action="create"]:not(:disabled)')
        assert not browser.js("document.querySelector('[data-wiki-home]') !== null")
        actual = browser.js("document.querySelector('[data-live-action=create]').textContent")
        assert actual == button_label, (language, actual)
        browser.click("[data-live-topic]")
        browser.cdp("Input.insertText", text=title)
        browser.click('[data-live-action="create"]')
        topic = json.dumps(title)
        wait(lambda: browser.js(f"document.querySelector('.hs-heading p:last-child')?.textContent === {topic}"))
        ref = next(row["project_ref"] for row in browser.get("/api/projects") if row["topic"] == title)
        browser.cdp("Page.reload")
        wait(lambda: browser.js(f"document.querySelector('[data-live-project-identity]')?.textContent.includes('{ref}')"))
        if language != "zh":
            assert browser.js("document.querySelector('[data-language]').value") == language, (language, browser.js("[document.querySelector('[data-language]').value, location.hash]"))
    assert browser.writes[initial_writes:] == [("POST", "/api/projects")] * len(cases)
    assert not browser.external and not browser.errors


def check_review_paths(browser):
    # Reproduce the independent HOME review's injected read responses while keeping its evidence intact.
    initial_writes, initial_errors = len(browser.writes), len(browser.errors)
    script = browser.cdp("Page.addScriptToEvaluateOnNewDocument", source="""
        const originalFetch = window.fetch;
        window.wikiHomeListFailures = 0;
        window.wikiHomeListAvailable = false;
        window.fetch = function(path, ...args) {
            if (path !== '/api/projects' || window.wikiHomeListAvailable) return originalFetch.call(this, path, ...args);
            window.wikiHomeListFailures++;
            return Promise.resolve(new Response(JSON.stringify({error:'review-list-unavailable'}), {status:503}));
        };
    """)["identifier"]
    browser.cdp("Page.reload")
    for attempt in range(1, 4):
        wait(lambda: browser.js(f"window.wikiHomeListFailures === {attempt} && !!document.querySelector('[data-wiki-home-retry]:not(:disabled)')"))
        assert browser.js("document.querySelector('.wiki-home-empty').textContent") == "暂时读不到项目列表。"
        assert browser.js("document.querySelector('#wiki-home-topic').disabled")
        if attempt < 3:
            browser.click("[data-wiki-home-retry]")
    browser.js("window.wikiHomeListAvailable = true")
    browser.click("[data-wiki-home-retry]")
    browser.home()
    assert browser.js("document.querySelectorAll('tr[data-wiki-home-origin]').length") == 3
    browser.cdp("Page.removeScriptToEvaluateOnNewDocument", identifier=script)

    index = {"project_id":"independent-saved", "papers":[], "claims":[]}
    index_pin, manifest_pin = "1" * 64, "2" * 64
    entry = {"ref":"independent", "project_ref":"view:independent", "label":"独审归档", "fixture":False,
             "project_id":index["project_id"], "index_sha256":index_pin, "manifest_sha256":manifest_pin,
             "stage2_available":True, "payload_url":"/v7-saved-runs/independent.json", "execution_authority":False}
    payload = json.dumps({"index":index, "index_sha256":index_pin, "stage2":{"project_id":index["project_id"]}})
    binding = {name:entry[name] for name in ("project_id", "fixture", "index_sha256", "manifest_sha256")}
    binding.update(kind="V7CanonicalSavedViewBinding", schema_version="1.0.0", view_ref=entry["ref"],
                   payload_sha256=sha256(payload.encode()).hexdigest())
    read_responses = {"/v7-saved-runs.json":{"kind":"V7CanonicalSavedViewList", "execution_authority":False, "views":[entry]},
                      entry["payload_url"]:{"kind":"V7CanonicalSavedView", "execution_authority":False,
                                            "binding":binding, "payload_json":payload}}
    script = browser.cdp("Page.addScriptToEvaluateOnNewDocument", source=f"""
        const originalFetch = window.fetch, saved = {json.dumps(read_responses)};
        window.fetch = function(path, ...args) {{
            if (Object.hasOwn(saved, path)) return Promise.resolve(new Response(JSON.stringify(saved[path])));
            return originalFetch.call(this, path, ...args);
        }};
    """)["identifier"]
    browser.cdp("Page.reload")
    row = 'tr[data-wiki-home-origin="archive"]'
    browser.see(row)
    assert "Stage 2" in browser.js(f"document.querySelector({json.dumps(row)}).innerText")
    browser.click(row + " button")

    def verify_archive(stage, lang, tag):
        wait(lambda: browser.js(f"""!document.querySelector('[data-wiki-home]') &&
            decodeURIComponent(location.hash).includes('#view:independent?stage={stage}&lang={tag}') &&
            document.querySelector('[data-language]')?.value === '{lang}' &&
            document.documentElement.lang === '{tag}' &&
            (document.querySelector('[data-v1]')
              ? document.querySelector('.v1-crumb')?.textContent.includes('独审归档') &&
                document.querySelector('.v1-flow [data-stage="{stage}"]')?.getAttribute('aria-current') === 'page'
              : document.querySelector('.hs-eyebrow')?.textContent === 'STAGE 0{stage} / 06' &&
                document.querySelector('.hs-project-name')?.textContent.includes('独审归档'))"""))

    def reload_archive(stage, lang, tag):
        browser.js("window.wikiHomeBeforeReload = true")
        browser.cdp("Page.reload")
        wait(lambda: browser.js("!window.wikiHomeBeforeReload && document.readyState === 'complete'"))
        verify_archive(stage, lang, tag)

    verify_archive(2, "zh", "zh-CN")
    reload_archive(2, "zh", "zh-CN")
    browser.click('[data-stage="1"]')
    browser.js("""const language = document.querySelector('[data-language]');
        language.value = 'en'; language.dispatchEvent(new Event('change', {bubbles:true}));""")
    verify_archive(1, "en", "en")
    reload_archive(1, "en", "en")
    browser.cdp("Page.removeScriptToEvaluateOnNewDocument", identifier=script)
    assert len(browser.writes) == initial_writes and not browser.external
    assert len(browser.errors) == initial_errors, browser.errors[initial_errors:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chrome", type=Path, required=True)
    parser.add_argument("--design", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wh-") as scratch:
        root = Path(scratch)
        (root / "incoming").mkdir()
        source = REPO / "plugins/auto-research-agent/cli/research_workspace_native/atlas_local_source.py"
        server = [sys.executable, "-B", str(UI / "run_v9.py"), "--repo", str(REPO),
                  "--source-helper-sha256", sha256(source.read_bytes()).hexdigest(),
                  "--projects-root", str(root / "p"), "--ui-state-root", str(root / "state"),
                  "--incoming-root", str(root / "incoming"), "--run-limits", str(UI / "zero-limits.json"),
                  "--port", "0"]
        host_log = root / "host.log"
        profile = root / "chrome"
        chrome = [str(args.chrome), "--headless", "--disable-background-networking", "--no-first-run",
                  "--remote-debugging-port=0", f"--user-data-dir={profile}", "about:blank"]

        def server_url(host):
            assert host.poll() is None, host_log.read_text(encoding="utf-8", errors="replace")
            return next((json.loads(line)["url"] for line in host_log.read_text(encoding="utf-8").splitlines()
                         if line.startswith("{") and '"url"' in line), None)

        with process(server, host_log) as host:
            url = wait(lambda: server_url(host), timeout=40)
            with process(chrome, root / "chrome.log"):
                port_file = profile / "DevToolsActivePort"
                port = wait(lambda: port_file.read_text().splitlines()[0] if port_file.exists() else None)
                browser = Browser(port)
                try:
                    check(browser, url, args.evidence)
                    check_review_paths(browser)
                    check_legacy(browser, url, [
                        ("en", "English compatibility project", "Create project"),
                        ("tw", "繁體中文相容性課題", "创建项目"),
                    ])
                    v7 = [part if part != str(UI / "run_v9.py") else str(UI / "run_v7.py")
                          for part in server[:server.index("--ui-state-root")] + server[server.index("--run-limits"):]]
                    v7[v7.index("--projects-root") + 1] = str(root / "v7")
                    with process(v7, host_log) as v7_host:
                        check_legacy(browser, wait(lambda: server_url(v7_host), timeout=40),
                                     [("zh", "V7 兼容性课题", "创建项目")])
                finally:
                    browser.ws.close()

    with Image.open(args.design) as reference, Image.open(args.evidence / "home-projects-1440.png") as actual:
        assert reference.width == actual.width == 1440
        comparison = Image.new("RGB", (2880, max(reference.height, actual.height)), "white")
        comparison.paste(reference, (0, 0))
        comparison.paste(actual, (1440, 0))
        comparison.save(args.evidence / "home-design-left-product-right.png")
    print("PASS HOME: empty, three persisted creates, list, filters, open, reload, resume, back, and zero external browser requests.")
    print("PASS HOME review probe: repeated 503 retry and recovery; archive Stage 2, stage and locale reload; no writes or JavaScript exceptions.")
    print("PASS old create and reload paths: standalone V7, Wiki English, and Wiki Traditional Chinese.")

if __name__ == "__main__":
    main()
