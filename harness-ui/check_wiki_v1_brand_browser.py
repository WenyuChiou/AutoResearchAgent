"""Check Wiki V1 branding in the built loopback Wiki and retained V7 renderer."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.request import urlopen

from check_wiki_home_browser import Browser, REPO, UI, process, wait

OBSERVE = """window.brandFrames=[];
new MutationObserver(()=>{
 const badge=document.querySelector('.hs-preview');
 const brand=document.querySelector('.hs-brand strong');
 if(!badge||!brand)return;
 const sample={badge:badge.textContent, sidebar:brand.textContent, title:document.title};
 if(JSON.stringify(window.brandFrames.at(-1))!==JSON.stringify(sample))window.brandFrames.push(sample);
}).observe(document,{subtree:true,childList:true,characterData:true});"""


def app_brand(browser, home=False):
    expected = "Wiki V1 · 工作台" if home else "Wiki V1"
    wait(lambda: browser.js(f"""document.title === {json.dumps(expected)} &&
         document.querySelector('.hs-preview')?.textContent === 'Wiki V1' &&
         document.querySelector('.hs-brand strong')?.textContent === 'Wiki V1'"""))


def check_v1(browser, url):
    browser.cdp("Page.addScriptToEvaluateOnNewDocument", source=OBSERVE)
    browser.open(url)
    browser.home()
    app_brand(browser, home=True)
    with urlopen(url, timeout=5) as response:
        raw_title = re.search(rb"<title>(.*?)</title>", response.read()).group(1).decode()
    browser.click("#wiki-home-topic")
    browser.cdp("Input.insertText", text="Wiki branding engineering fixture")
    browser.click("[data-wiki-home-create] button")
    wait(lambda: browser.js("!!location.hash && !document.querySelector('[data-wiki-home]')"))
    app_brand(browser)
    project = browser.get("/api/projects")[0]
    ref = project["project_ref"]
    assert project["execution_authorized"] is False
    assert browser.js(f"location.hash.startsWith('#{ref}?')")

    for stage, language, tag in ((2,"en","en"), (3,"tw","zh-TW"), (1,"zh","zh-CN")):
        browser.click(f'[data-stage="{stage}"]')
        browser.js(f"""(() => {{
           const field = document.querySelector('[data-language]');
           field.value = '{language}';
           field.dispatchEvent(new Event('change', {{bubbles:true}}));
        }})()""")
        wait(lambda: browser.js(f"""location.hash.startsWith('#{ref}?') &&
            new URLSearchParams(location.hash.split('?')[1]).get('stage') === '{stage}' &&
            new URLSearchParams(location.hash.split('?')[1]).get('lang') === '{tag}'"""))
        app_brand(browser)

    footer = browser.js("document.querySelector('.hs-footer').textContent")
    assert "原材料、保存输出与未接通操作分别标识" in footer
    assert "本地服务已连接" in browser.js("document.querySelector('.hs-sidebar-foot').textContent")
    overview_reads = f"performance.getEntriesByName(location.origin + '/api/projects/{ref}/overview').length"
    reads_before = browser.js(overview_reads)
    browser.click('details[data-local-operations="1"] > summary')
    browser.click('[data-local-operations="1"] [data-live-action="refresh"]')
    wait(lambda: browser.js(overview_reads) > reads_before)
    wait(lambda: browser.js("document.querySelector('[data-wiki-shell]')?.dataset.shellState === 'saved'"))
    app_brand(browser)
    assert browser.js(f"location.hash.startsWith('#{ref}?')")

    browser.click('[data-page="workspace"]')
    browser.home()
    app_brand(browser, home=True)
    browser.js("history.back(); true")
    wait(lambda: browser.js(f"location.hash.startsWith('#{ref}?') && !document.querySelector('[data-wiki-home]')"))
    app_brand(browser)

    frames = browser.js("window.brandFrames")
    assert frames and all(frame["badge"] == frame["sidebar"] == "Wiki V1" and
                          frame["title"] in {"Wiki V1", "Wiki V1 · 工作台"} for frame in frames), frames
    assert browser.writes == [("POST", "/api/projects")], browser.writes
    return {"served_html_title":raw_title, "rendered_title":browser.js("document.title"),
            "observed_brand_states":frames, "navigation":[2,3,1], "locales":["en","tw","zh"],
            "overview_reads_before_refresh":reads_before, "overview_reads_after_refresh":browser.js(overview_reads),
            "fixture_create_posts":len(browser.writes), "external_requests":len(browser.external)}


def check_v7(browser, url):
    browser.open(url)
    browser.see("[data-live-empty-home]")
    shell = (UI / "renderer/src/shell.html").read_text(encoding="utf-8")
    assert browser.js("document.title") == re.search(r"<title>(.*?)</title>", shell).group(1)
    assert browser.js("document.querySelector('.hs-preview').textContent.startsWith('V9 · ')")
    assert not browser.writes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chrome", type=Path, required=True)
    args = parser.parse_args()
    helper = REPO / "plugins/auto-research-agent/cli/research_workspace_native/atlas_local_source.py"
    with tempfile.TemporaryDirectory(prefix="wb-") as scratch:
        root = Path(scratch)
        (root / "in").mkdir()
        profile = root / "chrome"
        chrome = [str(args.chrome), "--headless", "--disable-background-networking", "--no-first-run",
                  "--remote-debugging-port=0", f"--user-data-dir={profile}", "about:blank"]
        with process(chrome, root / "chrome.log"):
            ready = profile / "DevToolsActivePort"
            port = wait(lambda: ready.read_text().splitlines()[0] if ready.exists() else None)
            for mode, check in (("v1",check_v1), ("v7",check_v7)):
                launcher = UI / ("run_v9.py" if mode=="v1" else "run_v7.py")
                server = [sys.executable, "-B", str(launcher), "--repo", str(REPO),
                          "--source-helper-sha256", sha256(helper.read_bytes()).hexdigest(),
                          "--projects-root", str(root / mode), "--run-limits", str(UI / "zero-limits.json"), "--port", "0"]
                if mode == "v1":
                    server += ["--ui-state-root", str(root / "state"), "--incoming-root", str(root / "in")]
                log = root / f"{mode}.log"
                with process(server, log) as host:
                    def url_ready():
                        output = log.read_text(encoding="utf-8", errors="replace")
                        assert host.poll() is None, output
                        return next((json.loads(line)["url"] for line in output.splitlines()
                                     if line.startswith("{") and '"url"' in line), None)
                    browser = Browser(port)
                    try:
                        url = wait(url_ready, timeout=40)
                        browser.origin = url.rstrip("/")
                        result = check(browser,url)
                        assert not browser.external and not browser.errors, (browser.external,browser.errors)
                        if result:
                            result["head"] = subprocess.check_output(["git","rev-parse","HEAD"],cwd=REPO,text=True).strip()
                            print(json.dumps(result, ensure_ascii=False))
                    finally:
                        browser.ws.close()
    print("PASS first render, refresh, stage/locale routing, HOME and standalone V7.")


if __name__ == "__main__":
    main()
