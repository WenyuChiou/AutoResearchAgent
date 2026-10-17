"""Publish verified native-produced Harness output as a current V7 result."""
import hashlib
import json
import re
from pathlib import Path

from saved_views import snapshot_saved_views


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class NativeOutputs:
    def __init__(self, root, presentations):
        from stage1_deliverable.common import private_output, reject_links
        self.root = private_output(root)
        reject_links(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.presentations = presentations

    def collect(self, job_ref, case_ref, output_dir):
        from stage1_deliverable.common import reject_links
        from stage1_deliverable.common import canonical
        from research_workspace.canonical_delivery import project_canonical_atlas
        from research_workspace_native.atlas_host import load_views

        if not re.fullmatch(r'native-[a-f0-9]{64}', job_ref):
            raise ValueError('invalid native job reference')
        expected = self.presentations[case_ref]
        output = Path(output_dir)
        reject_links(output)
        proof = json.loads((output / 'case-result.json').read_bytes())
        package = Path(expected['source_package'])
        manifest_raw = (package / 'provenance_manifest.json').read_bytes()
        manifest_sha = digest(manifest_raw)
        manifest = json.loads(manifest_raw)
        if (manifest_sha != expected['source_manifest_sha256']
                or proof['delivery_manifest_sha256'] != manifest_sha
                or manifest['original_input_sha256'] != expected['records_sha256']):
            raise ValueError('native delivery input binding differs')
        index, _ = project_canonical_atlas(package, expected['project_id'], manifest_sha)
        if (output/'atlas/workspace-index.json').read_bytes() != canonical(index):
            raise ValueError('native projection differs from canonical source')
        view = output / 'atlas' / 'view-manifest.json'
        view_sha = digest(view.read_bytes())
        if proof['view_manifest_sha256'] != view_sha:
            raise ValueError('native view receipt differs')
        config = {'views': [dict(ref=case_ref, label=expected['label'],
                   manifest=str(view), sha256=view_sha, fixture=expected['fixture'])]}
        raw = json.dumps(config, ensure_ascii=False, sort_keys=True).encode('utf-8')
        path = output / 'v7-output-registration.json'
        if path.exists():
            if path.read_bytes() != raw:
                raise ValueError('native registration changed')
        else:
            with path.open('xb') as stream:
                stream.write(raw)
        files, views = load_views(path, digest(raw))
        if len(views) != 1 or views[0]['project_id'] != expected['project_id']:
            raise ValueError('native view project differs')
        assets = snapshot_saved_views(files, views)
        envelope = json.loads(assets['/v7-saved-runs/'+case_ref+'.json'])
        entry = json.loads(assets['/v7-saved-runs.json'])['views'][0]
        entry['project_ref'] = expected['project_ref']
        value = dict(kind='V7NativeDeliveredResult', job_ref=job_ref, case_ref=case_ref,
                     project_ref=expected['project_ref'], entry=entry, envelope=envelope,
                     source_scope='historical-saved-case-reexport',
                     new_research=False, research_complete=False)
        result_raw = json.dumps(value, ensure_ascii=True, allow_nan=False).encode('utf-8')
        if len(result_raw) > 1024*1024:
            raise ValueError('native result response bound exceeded')
        target = self.root / (job_ref+'.json')
        if target.exists():
            if target.read_bytes() != result_raw:
                raise ValueError('native result changed')
        else:
            with target.open('xb') as stream:
                stream.write(result_raw)
        return dict(result_json_sha256=digest(result_raw),
                    result_url='/api/v7/stage1/jobs/'+job_ref+'/result',
                    project_ref=expected['project_ref'], manifest_sha256=view_sha,
                    delivery_manifest_sha256=manifest_sha, validation='canonical-saved-package-bytes-verified',
                    semantic_replay=False,
                    research_complete=False, new_research=False)

    def get(self, job_ref, receipt):
        if not re.fullmatch(r'native-[a-f0-9]{64}', job_ref) or not receipt:
            return None
        target = self.root / (job_ref+'.json')
        if not target.is_file() or target.is_symlink():
            return None
        raw = target.read_bytes()
        if len(raw) > 1024*1024 or digest(raw) != receipt.get('result_json_sha256'):
            raise ValueError('native saved result hash differs')
        return json.loads(raw)
