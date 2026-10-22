"""Local material registration and adapters to existing offline Harness contracts.

No model invocation, scientific decisions, stage completion or research permits.
Original packages remain unchanged; new workflow snapshots have their own identity.
"""
from contextlib import contextmanager
import base64
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import threading
from datetime import datetime, timezone


def raw(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(value).hexdigest()


def stamp():
    return datetime.now(timezone.utc).isoformat()


class MaterialError(ValueError):
    pass


def require(ok, reason):
    if not ok:
        raise MaterialError(reason)


class Materials:
    def __init__(self, root, incoming, builtins, review_sources=()):
        self.root, self.incoming = Path(root).resolve(), Path(incoming).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / 'files').mkdir(exist_ok=True)
        (self.root / 'workflows').mkdir(exist_ok=True)
        self.db = self.root / 'materials.sqlite3'
        self.lock = threading.RLock()
        self.builtins = builtins
        self.review_sources = list(review_sources)
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS materials(id TEXT PRIMARY KEY, body TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS chunks(id TEXT, offset INTEGER, data BLOB NOT NULL, PRIMARY KEY(id,offset));
              CREATE TABLE IF NOT EXISTS operations(id TEXT PRIMARY KEY, body TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS drafts(id TEXT PRIMARY KEY, revision INTEGER NOT NULL, body TEXT NOT NULL);''')

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.db, timeout=1)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _get(self, table, identity):
        require(table in {'materials', 'operations', 'drafts'}, 'unknown-record-table')
        with self.connect() as db:
            row = db.execute(f'SELECT body FROM {table} WHERE id=?', (identity,)).fetchone()
        require(row is not None, 'record-not-found')
        return json.loads(row[0])

    def _put(self, table, identity, value):
        require(table in {'materials', 'operations'}, 'unknown-record-table')
        with self.connect() as db:
            db.execute(f'INSERT INTO {table} VALUES (?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body', (identity, raw(value).decode()))

    def catalog(self):
        with self.connect() as db:
            materials = [json.loads(r[0]) for r in db.execute('SELECT body FROM materials ORDER BY rowid DESC')]
            ops = [json.loads(r[0]) for r in db.execute('SELECT body FROM operations ORDER BY rowid DESC')]
            drafts = [json.loads(r[0]) for r in db.execute('SELECT body FROM drafts ORDER BY rowid DESC')]
        return dict(kind='V9ManualMaterialRegistry', materials=materials, operations=ops, drafts=drafts,
                    available_deliveries=[{k:v for k,v in item.items() if k not in {'packet_path','source_root'}} for item in self.builtins],
                    model_execution=False, supported_entry_stages=[1,2,3,4,5,6],
                    stage_operations={'1':'material-registration-and-existing-project-intake',
                      '2':'existing-Harness-validate-packet-and-initialize-inspect-workflow',
                      '3-6':'material-registration-only-no-execution-adapter'})

    def register_delivery(self, body):
        entry = next((x for x in self.builtins if x['id'] == body.get('delivery_id')), None)
        require(entry is not None, 'unknown-delivery')
        identity = 'delivery-' + digest(raw([entry['id'], entry['sha256'], body['project_ref']]))[:32]
        with self.lock:
            try:
                return self._get('materials', identity)
            except MaterialError:
                pass
            value = {**entry, 'id':identity, 'delivery_id':entry['id'], 'project_ref':body['project_ref'],
                     'status':'registered', 'kind':'saved-delivery', 'registered_at':stamp(),
                     'execution_authorized':False, 'association':'operator-material-reference-not-upstream-lineage'}
            self._put('materials', identity, value)
            return value

    def begin_upload(self, body):
        name, stage, size, pin = body.get('name'), body.get('stage'), body.get('bytes'), body.get('sha256')
        require(isinstance(name,str) and 0 < len(name) <= 240 and not any(c in name for c in '/\\\r\n\x00'), 'invalid-file-name')
        require(type(stage) is int and 1 <= stage <= 6, 'invalid-stage')
        require(type(size) is int and 0 <= size <= 128*1024*1024, 'file-exceeds-128MiB')
        require(isinstance(pin,str) and re.fullmatch('[0-9a-f]{64}',pin), 'file-hash-required')
        require(Path(name).suffix.lower() in {'.pdf','.json','.jsonl','.md','.txt','.csv','.tsv','.bib','.zip','.docx','.png','.jpg','.xlsx'}, 'unsupported-material-extension')
        identity = 'file-' + digest(raw([body['project_ref'], stage, name, size, pin]))[:32]
        with self.lock:
            try:
                return self._get('materials', identity)
            except MaterialError:
                pass
            value = dict(id=identity, kind='manual-file', project_ref=body['project_ref'], stage=stage,
                         name=name, bytes=size, sha256=pin, status='uploading', received=0,
                         registered_at=stamp(), execution_authorized=False,
                         content_status='unreviewed-material-not-screened-or-read')
            self._put('materials', identity, value)
            return value

    def upload_chunk(self, body):
        with self.lock:
            item = self._get('materials', body.get('id'))
            require(item['kind']=='manual-file', 'not-uploadable')
            data = base64.b64decode(body.get('base64',''), validate=True)
            offset = body.get('offset')
            require(type(offset) is int and offset >= 0 and 0 < len(data) <= 128*1024 and offset+len(data)<=item['bytes'], 'invalid-chunk')
            with self.connect() as db:
                old = db.execute('SELECT data FROM chunks WHERE id=? AND offset=?',(item['id'],offset)).fetchone()
                if old:
                    require(old[0]==data, 'chunk-conflict')
                    return item
                require(item['status']=='uploading' and offset==item['received'], 'chunk-out-of-order')
                db.execute('INSERT INTO chunks VALUES (?,?,?)',(item['id'],offset,data))
                item['received'] += len(data)
                db.execute('UPDATE materials SET body=? WHERE id=?',(raw(item).decode(),item['id']))
            return item

    def finish_upload(self, body):
        with self.lock:
            item = self._get('materials', body.get('id'))
            require(item['kind']=='manual-file', 'not-uploadable')
            if item['status']=='registered':
                require(digest(self.file_bytes(item['id']))==item['sha256'], 'saved-material-differs')
                return item
            require(item['received']==item['bytes'], 'upload-incomplete')
            with self.connect() as db:
                data = b''.join(r[0] for r in db.execute('SELECT data FROM chunks WHERE id=? ORDER BY offset',(item['id'],)))
            require(len(data)==item['bytes'] and digest(data)==item['sha256'], 'uploaded-bytes-hash-mismatch')
            path = self.root/'files'/(item['id']+'.bin')
            if path.exists():
                require(path.read_bytes()==data, 'material-file-conflict')
            else:
                with path.open('xb') as stream:
                    stream.write(data)
            item.update(status='registered', completed_at=stamp())
            self._put('materials',item['id'],item)
            return item

    def file_bytes(self, identity):
        item = self._get('materials',identity)
        require(item['kind']=='manual-file' and item['status']=='registered','material-not-complete')
        path = self.root/'files'/(identity+'.bin')
        require(not path.is_symlink(),'material-link-rejected')
        data = path.read_bytes()
        require(len(data)==item['bytes'] and digest(data)==item['sha256'],'material-file-differs')
        return data

    def safe_incoming(self, value, directory=False):
        require(isinstance(value,str) and 0<len(value)<1000, 'incoming-path-required')
        path = Path(value)
        require(path.is_absolute(), 'absolute-local-path-required')
        require(not any(p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction()) for p in (path,*path.parents)), 'material-links-rejected')
        resolved = path.resolve(strict=True)
        require(resolved.is_relative_to(self.incoming), 'path-must-be-under-harness-ui-incoming')
        require(resolved.is_dir() if directory else resolved.is_file(), 'material-path-kind')
        return resolved

    def import_packet(self, body):
        """Register any existing Stage2Packet supported by the pinned Harness."""
        from stage2_common import validate_packet, canonical_hash
        packet_path = self.safe_incoming(body.get('packet_path'))
        source_root = self.safe_incoming(body.get('source_root'), True)
        data = packet_path.read_bytes()
        require(len(data)<=8*1024*1024,'packet-too-large')
        require(digest(data)==body.get('sha256'),'operator-packet-byte-hash-differs')
        packet = json.loads(data)
        self._check_source_paths(packet,source_root)
        validate_packet(packet,source_root)
        entry = dict(id='packet-'+digest(raw([digest(data),body['project_ref']]))[:32],
            kind='manual-stage2-packet', stage=2, name=packet_path.name,
            project_ref=body['project_ref'], sha256=digest(data), packet_sha256=canonical_hash(packet),
            packet_path=str(packet_path), source_root=str(source_root), status='registered',
            registered_at=stamp(), execution_authorized=False, schema_version=packet['schema_version'])
        with self.lock:
            try:
                return self._get('materials',entry['id'])
            except MaterialError:
                self._put('materials',entry['id'],entry)
        return entry

    def _check_source_paths(self, packet, root):
        for source in packet.get('sources',[]):
            value=source.get('path','')
            require(isinstance(value,str) and value and not any(c in value for c in '\\:') and not PurePosixPath(value).is_absolute() and all(p not in {'','..','.'} for p in value.split('/')), 'source-path-unsafe')
            self.safe_incoming(str(root.joinpath(*value.split('/'))))

    def packet_view(self, identity):
        """Re-read an imported packet and every bound source without executing it."""
        from stage2_common import validate_packet, canonical_hash
        item = self._get('materials', identity)
        require(item['stage'] == 2 and item.get('packet_path') and item['status'] == 'registered',
                'stage2-packet-required')
        path = self.safe_incoming(item['packet_path'])
        root = self.safe_incoming(item['source_root'], True)
        data = path.read_bytes()
        pin = item.get('packet_file_sha256', item['sha256'])
        require(len(data) <= 8*1024*1024 and digest(data) == pin, 'packet-changed-after-registration')
        packet = json.loads(data)
        self._check_source_paths(packet, root)
        validate_packet(packet, root)
        cards, total = [], len(data)
        for source in packet['sources']:
            content = self.safe_incoming(str(root / source['path'])).read_bytes()
            total += len(content)
            require(total <= 32*1024*1024, 'packet-display-exceeds-32MiB-use-original-files')
            require(digest(content) == source['sha256'], 'source-changed-during-display-read')
            cards.append(dict(source_id=source['source_id'], work_id=source['work_id'],
                version_id=source['version_id'], evidence_level=source['evidence_level'],
                artifact={'sha256': source['sha256']}, saved_text=content.decode('utf-8')))
        view = dict(kind='V9ValidatedPacketView', material_id=item['id'], project_ref=item['project_ref'],
            packet_text=data.decode('utf-8'), packet_file_sha256=pin,
            packet_sha256=canonical_hash(packet), cards=cards, execution_authorized=False,
            projection='validated-input-not-new-research-output',
            formal_selection=dict(available=False, missing=[
                'trusted-workflow-delivery-registration', 'current-delivery-manifest-and-event-head',
                'independent-review-receipts', 'native-user-message-provenance']),
            stage1_lineage=packet.get('upstream'), research_generated=False)
        from review_reading import project_reviews
        reading = project_reviews(self, item, packet, pin)
        if reading is not None:
            view['independent_reviews'] = reading
        return view

    def workflow(self, body):
        from stage2_common import validate_packet, canonical_hash
        from stage2_workflow.store import initialize_workflow, inspect_workflow
        with self.lock:
            item=self._get('materials',body.get('id'))
            require(item['stage']==2 and item.get('packet_path') and item['status']=='registered','stage2-packet-required')
            require(body.get('expected_sha256')==item['sha256'],'material-identity-changed')
            operation='workflow-'+digest(raw([item['id'],item['sha256']]))[:32]
            try:
                old=self._get('operations',operation)
            except MaterialError:
                old=None
            if old:
                require(old['status']=='prepared','previous-attempt-held-read-receipt')
                return self.inspect(operation)
            packet_path=self.safe_incoming(item['packet_path'])
            source_root=self.safe_incoming(item['source_root'],True)
            data=packet_path.read_bytes()
            require(digest(data)==item.get('packet_file_sha256',item['sha256']),'packet-changed-after-registration')
            packet=json.loads(data)
            self._check_source_paths(packet,source_root)
            validate_packet(packet,source_root)
            run=self.root/'workflows'/operation
            value=dict(id=operation, material_id=item['id'], stage=2, project_ref=item['project_ref'],
                status='preparing', run_dir=str(run), created_at=stamp(),
                source_sha256=item['sha256'], packet_sha256=canonical_hash(packet), execution_authorized=False)
            self._put('operations',operation,value)
            try:
                initialize_workflow(packet_path,source_root,run,
                    {'mode':'local-offline-preparation','model_calls':0,'source_requests':0},
                    {'kind':'V9ManualMaterialPreparation','input_material_id':item['id'],'execution_authorized':False},
                    expected_packet_sha256=canonical_hash(packet))
                state=inspect_workflow(run)
                value.update(status='prepared',event_head=state['head_sha256'],
                    workflow_id=state['manifest']['workflow_id'], manifest_sha256=state['manifest']['manifest_sha256'],
                    finished_at=stamp(), next_step='independent-review-inputs-and-role-registration-required',
                    pending_candidates=[c['candidate_id'] for c in packet['candidates']],
                    original_assessments='retained-in-original-delivery-not-reapplied-to-new-workflow')
            except Exception as error:
                value.update(status='failed',error=str(error),finished_at=stamp())
                self._put('operations',operation,value)
                raise
            self._put('operations',operation,value)
            return value

    def inspect(self, identity):
        from stage2_workflow.store import inspect_workflow
        item=self._get('operations',identity)
        require(item['status']=='prepared','workflow-not-prepared')
        state=inspect_workflow(item['run_dir'],expected_head=item['event_head'])
        require(state['manifest']['manifest_sha256']==item['manifest_sha256'],'workflow-manifest-differs')
        return dict(item, revalidated=True, last_read_at=stamp(), actions=len(state['actions']))

    def draft(self, body):
        material=self._get('materials',body.get('id'))
        text=body.get('note','')
        require(isinstance(text,str) and len(text.encode())<=8192,'note-too-long')
        require(type(body.get('target_stage')) is int and 1<=body['target_stage']<=6,'invalid-target-stage')
        revision=body.get('revision')
        require(type(revision) is int and revision>=0,'draft-revision-required')
        selection=body.get('selection')
        if selection is not None:
            require(material['stage']==2 and material.get('packet_path'), 'selection-needs-stage2-packet')
            require(isinstance(selection,dict), 'selection-object-required')
            data=self.safe_incoming(material['packet_path']).read_bytes()
            pin=material.get('packet_file_sha256',material['sha256'])
            require(digest(data)==pin and selection.get('packet_sha256')==pin,'selection-packet-changed')
            packet=json.loads(data)
            papers=selection.get('source_ids');routes=selection.get('candidates')
            require(isinstance(papers,list) and len(papers)<=3 and all(isinstance(x,str) for x in papers) and len(set(papers))==len(papers),'invalid-source-selection')
            require(set(papers)<={s['source_id'] for s in packet['sources']},'unknown-source-selection')
            require(isinstance(routes,list) and len(routes)<=3,'invalid-route-selection')
            valid={(c['candidate_id'],c['version']) for c in packet['candidates']}
            identities=[]
            for candidate in routes:
                require(isinstance(candidate,dict) and set(candidate)=={'candidate_id','version'},'invalid-route-selection')
                require(isinstance(candidate['candidate_id'],str) and type(candidate['version']) is int,'invalid-route-selection')
                identity=(candidate['candidate_id'],candidate['version'])
                require(identity in valid and identity not in identities,'candidate-version-changed')
                identities.append(identity)
            selection=dict(packet_sha256=pin,source_ids=papers,candidates=routes,
                           kind='comparison-shortlist-not-human-selection')
        value=dict(id=material['id'],revision=revision+1, target_stage=body['target_stage'],note=text,
                   source_sha256=material['sha256'],updated_at=stamp(),submitted_to_harness=False,
                   project_ref=material['project_ref'])
        with self.lock, self.connect() as db:
            old=db.execute('SELECT revision,body FROM drafts WHERE id=?',(material['id'],)).fetchone()
            previous=json.loads(old[1]) if old else {}
            value['selection']=selection if selection is not None else previous.get('selection')
            if old and old[0]==revision+1:
                require(previous['note']==text and previous['target_stage']==value['target_stage'] and previous.get('selection')==value['selection'],'draft-revision-conflict')
                return previous
            require((old[0] if old else 0)==revision,'draft-revision-conflict')
            db.execute('INSERT INTO drafts VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,body=excluded.body',(material['id'],revision+1,raw(value).decode()))
        return value
