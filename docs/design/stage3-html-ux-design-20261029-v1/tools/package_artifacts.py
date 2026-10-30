"""Package only the synthetic design directory, never product source or Git state."""
import hashlib
import json
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'downloads'/'design-only.zip'
OUT.parent.mkdir(exist_ok=True)
excluded={'ARTIFACT_MANIFEST.json','PACKAGE.json'}
files=sorted(p for p in ROOT.rglob('*') if p.is_file() and p!=OUT and p.name not in excluded and '__pycache__' not in p.parts)
manifest={'kind':'design-only-artifact-manifest','synthetic_only':True,'product_source_included':False,'files':[{'path':p.relative_to(ROOT).as_posix(),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]}
(ROOT/'ARTIFACT_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
with zipfile.ZipFile(OUT,'w',zipfile.ZIP_DEFLATED) as archive:
    for p in files+[ROOT/'ARTIFACT_MANIFEST.json']:
        archive.write(p,p.relative_to(ROOT).as_posix())
with zipfile.ZipFile(OUT) as archive:
    assert archive.testzip() is None
    assert all(not Path(n).is_absolute() and '..' not in Path(n).parts for n in archive.namelist())
receipt={'artifact':'downloads/design-only.zip','sha256':hashlib.sha256(OUT.read_bytes()).hexdigest(),'bytes':OUT.stat().st_size,'files':len(files)+1,'zip_crc_checked':True,'scope':'design-only; no backend/API/product source/real research data','source_baseline':'57ae0509d7ccf17c92080434d8454b4e2352c33c'}
(ROOT/'PACKAGE.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(receipt))
