"""Bounded offline checks of the design artifacts; never import product modules."""
import hashlib
import json
import re
import struct
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
PREFIX = "docs/design/stage3-html-ux-design-20261029-v1/"
FLAGS = ["execution_authorized", "evaluation_calls_authorized", "formal_execution_enabled", "external_claim_ready", "usable_for_formal_pairing"]
checks = []


def check(condition, identity):
    if not condition:
        raise AssertionError(identity)
    checks.append(identity)


def read(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids=[]; self.links=[]; self.active=[]; self.primary=[]; self.pre=[]; self.current_pre=None; self.sq=[]

    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if "id" in a: self.ids.append(a["id"])
        if tag in {"script","iframe","object","form"}: self.active.append(tag)
        if any(k.startswith("on") for k in a): self.active.append("event-handler")
        if tag=="a" and "href" in a: self.links.append(a["href"])
        if tag in {"link","img"}:
            path=a.get("src",a.get("href",""))
            if urlsplit(path).scheme or path.startswith("//"): self.active.append("external-asset")
        if "primary" in a.get("class","").split(): self.primary.append((tag,"disabled" in a))
        if "data-preserve-sq" in a: self.sq.append((a["data-preserve-sq"],a["href"]))
        if tag=="pre": self.current_pre=[]

    def handle_data(self,data):
        if self.current_pre is not None: self.current_pre.append(data)

    def handle_endtag(self,tag):
        if tag=="pre" and self.current_pre is not None:
            self.pre.append("".join(self.current_pre)); self.current_pre=None


pages={}
for path in ROOT.glob("*.html"):
    p=Page(); p.feed(path.read_text(encoding="utf-8")); pages[path.name]=p
    check(not p.active, path.name+": no script/form/event/network assets")
    check(len(p.ids)==len(set(p.ids)), path.name+": IDs unique")
    if path.name.startswith(("mock-","stage2-")):
        check(p.primary==[("button",True)],path.name+": one disabled primary operation")
        name=path.name.split(".")[0].replace("mock-","").replace("stage2-","")
        check(json.loads(p.pre[-1])==read("fixtures/"+name+".json"),path.name+": raw saved view unchanged")
for name,p in pages.items():
    for link in p.links:
        u=urlsplit(link)
        check(not u.scheme and not u.netloc,name+": local static navigation only")
        target=unquote(u.path) or name
        check((ROOT/target).is_file(),name+": target exists "+target)
        if u.fragment and target in pages: check(unquote(u.fragment) in pages[target].ids,name+": anchor exists "+u.fragment)
    for identity,link in p.sq:
        check(urlsplit(link).fragment==identity,name+": locale preserves SQ anchor")
check(len(pages)==13,"13 generated HTML documents")
copy=read("copy.json")
check(len(copy["labels"])==93,"93 interface labels")
check(all(set(v)=={"zh-CN","zh-TW","en"} and all(v.values()) for v in copy["labels"].values()),"three-language label coverage")
for name in ["observation","theory"]:
    fixture=read("fixtures/"+name+".json"); view=fixture["view"]; meta=fixture["mock_meta"]
    check(meta["synthetic"] and not meta["backend_connected"] and not meta["contract_validated"],name+": explicit synthetic/not admitted")
    check(all(view[k] is False for k in FLAGS),name+": five flags false")
    check(view["selection_status"]=="pending" and view["default_request"] is None,name+": no fake choice/request pins")
    check(meta["literal_values"]=={"known_zero":0,"known_false":False,"unknown":None,"unrun":"not-run"},name+": literal preservation")
    for r in view.get("plan",{}).get("results",[]): check(r["status"]=="not-run" and r["observed_value"] is None,name+": no observed result")
    for locale in copy["locales"]:
        b=read("blocks/"+name+"."+locale+".json")
        check(b["source_fixture_sha256"]==hashlib.sha256((ROOT/"fixtures"/(name+".json")).read_bytes()).hexdigest(),name+locale+": same canonical input")
        refs={r["question_ref"] for r in (view.get("direction_context") or {}).get("questions",[]) or view["plan"].get("questions",[])}
        check(all(any(ref in "\n".join(block["paragraphs"]) for block in b["blocks"]) for ref in refs),name+locale+": every original SQ visible")
        if name=="observation": check(b["explicit_edges"]==[],name+locale+": no graph inferred from prose")
        else:
            expected={("MOCK-FORMAL@1/SQ-01","D-FORMAL-01"),("MOCK-FORMAL@1/SQ-02","D-FORMAL-01"),("D-FORMAL-01","A-FORMAL-01"),("A-FORMAL-01","R-OUTPUT-1"),("A-FORMAL-01","R-OUTPUT-2")}
            check({tuple(x) for x in b["explicit_edges"]}==expected,name+locale+": only five declared edges")
            check(sum(x["id"]=="D-FORMAL-01" for x in b["blocks"])==1,name+locale+": shared design once")
states=read("state-matrix.json")["states"]
check(len(states)==len({s["id"] for s in states})==19,"19 distinct states")
mapping=read("source-map.json")["rows"]
check(len(mapping)==36 and all(r["production_pointer"] is None or (r["production_pointer"].startswith("/") and "*" not in r["production_pointer"]) for r in mapping),"36 concrete-or-missing source pointers")
review=read("self-review.json")
check(review["review_count"]==1 and not review["independent_review"] and review["human_participants"] is None,"one author self-review, no invented users")
check(len(review["findings"])==8 and all(f["remaining"] for f in review["findings"]),"eight findings with limits")
renders=read("WIREFRAME_RENDER.json")
check(len(renders)==24,"24 GDI wireframe outputs")
for r in renders:
    raw=(ROOT/r["file"]).read_bytes()
    width,height=struct.unpack(">II",raw[16:24])
    check(raw[:8]==b"\x89PNG\r\n\x1a\n" and width==r["width"] and height==r["height"] and width in {390,1440},r["file"]+": real PNG dimensions")
    check(r["canvas_bounds_checked"] and r["browser_screenshot"] is False,r["file"]+": drawing only")
css=(ROOT/"mock.css").read_text(encoding="utf-8")
check("@import" not in css and "url(" not in css and "system-ui" in css,"no external font/CDN")
check("min-height:46px" in css and ":focus-visible" in css,"44px+ controls and focus design rule")
changed=subprocess.check_output(["git","diff","57ae0509d7ccf17c92080434d8454b4e2352c33c","--name-only"],cwd=REPO,text=True).splitlines()
check(all(p.startswith(PREFIX) for p in changed),"all tracked changes in design artifact directory")
untracked=subprocess.check_output(["git","ls-files","--others","--exclude-standard"],cwd=REPO,text=True).splitlines()
check(all(p.startswith(PREFIX) for p in untracked),"all untracked changes in design artifact directory")
result={"status":"OFFLINE_ARTIFACT_CHECKS_PASSED","checks":len(checks),"checked":checks,"source_baseline":"57ae0509d7ccf17c92080434d8454b4e2352c33c","product_tests":"NOT_RUN","CI":"NOT_RUN","browser_UI_control":"NOT_RUN","human_usability":"NOT_RUN","actual_accessibility_200percent":"NOT_RUN","E2E_scientific_validity":"NOT_RUN","participants":None,"cost":None}
(ROOT/"VALIDATION.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps({k:result[k] for k in ["status","checks","product_tests","CI","browser_UI_control"]}))
