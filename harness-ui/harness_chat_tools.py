"""Topic-independent adapters to existing Harness operations; no research rules."""
import hashlib
import json
from pathlib import Path
from harness_chat_stages import attach_stage_availability


TEXT_MATERIAL_LIMIT = 64 * 1024
TEXT_MATERIAL_EXTENSIONS = {'.txt', '.md', '.json', '.jsonl', '.csv', '.tsv', '.bib'}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(',', ':')).encode()


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


class HarnessChatTools:
    def __init__(self, host, materials, stage_registry=None):
        self.host, self.materials = host, materials
        self.stage_registry = stage_registry

    def context(self, project, stage):
        require(type(stage) is int and 1 <= stage <= 6, 'chat-stage-not-supported')
        if project.startswith('view:'):
            view = next((v for v in self.host.views if 'view:' + v['ref'] == project), None)
            require(view is not None, 'chat-project-unknown')
            pin = view['manifest_sha256']
            mode = 'saved-delivery'
        else:
            value = self.host.projects.read(self.host.credential, project)
            pin = hashlib.sha256(encoded(value)).hexdigest()
            mode = 'active-project'
        catalog = self.materials.catalog()
        items = [m for m in catalog['materials'] if m['project_ref'] == project and m['stage'] == stage]
        actions = ['state', 'materials', 'read_material', 'register_delivery', 'save_review']
        if stage == 1:
            actions += ['read_saved_stage', 'read_paper']
        elif stage == 2:
            actions += ['read_saved_stage', 'inspect_workflow', 'prepare_workflow', 'handoff_status', 'prepare_advice']
        context = dict(project_ref=project, stage=stage, mode=mode, project_pin=pin,
                    materials=[{k: m.get(k) for k in ('id', 'name', 'sha256', 'packet_file_sha256', 'status', 'stage')}
                               for m in items],
                    registered_delivery_ids=[x['id'] for x in catalog['available_deliveries'] if x['stage'] == stage],
                    supported_actions=actions,
                    unavailable=['new-formal-human-record', 'live-research-loop', 'stage-research-execution'],
                    capabilities=dict(material_registration=True, local_review_notes=True,
                        material_reading='validated-stage2-packet' if stage == 2 else 'registered-utf8-text-only',
                        material_text_max_bytes=TEXT_MATERIAL_LIMIT if stage != 2 else None,
                        saved_stage_reading=stage in (1, 2), offline_workflow_preparation=stage == 2,
                        formal_selection=False, research_execution=False,
                        stage_execution='planned-unconnected' if stage >= 3 else 'not-authorized'))
        reader = getattr(self.host, 'independent_saved_stage2_reader', None)
        if stage == 2 and reader is not None and project == reader.project_ref:
            context['independent_saved_stage2'] = reader.describe(project, stage, pin)
            context['capabilities']['material_reading'] = 'registered-packet-or-independent-saved-source'
        return attach_stage_availability(context, self.stage_registry)

    @staticmethod
    def specs():
        actions = ['state', 'materials', 'read_material', 'read_saved_stage', 'read_paper', 'inspect_workflow', 'register_delivery',
                   'prepare_workflow', 'save_review', 'handoff_status', 'prepare_advice']
        return [dict(type='function', name='harness', description=(
            'Call the current project and stage Harness. state/materials/read_material/inspect_workflow/handoff_status '
            'are read-only. Other actions require the human to confirm the exact request in the UI. '
            'prepare_workflow invokes real offline Harness initialization; it does not execute research. '
            'save_review saves an annotation, not formal scientific selection. Never invent IDs or evidence. '
            'Stage1 and Stage3-6 can read only registered bounded UTF-8 text materials. '
            'No shell, network research, model recursion, formal human-record, or Stage3-6 execution is offered. '
            'Use state to read the supported actions for this stage.'),
            inputSchema={'type': 'object', 'properties': {
                'action': {'type': 'string', 'enum': actions},
                'id': {'type': 'string', 'description': 'Exact material/workflow/delivery or independent saved-document ID returned by state; empty if not needed.'},
                'note': {'type': 'string', 'description': 'Review text, or empty.'}},
                'required': ['action', 'id', 'note'], 'additionalProperties': False})]

    def validate(self, session, args):
        require(isinstance(args, dict) and set(args) == {'action', 'id', 'note'}, 'chat-tool-arguments-invalid')
        require(all(isinstance(v, str) for v in args.values()), 'chat-tool-strings-required')
        require(len(args['note'].encode()) <= 8192 and len(args['id']) <= 200, 'chat-tool-input-too-large')
        require(args['action'] in self.specs()[0]['inputSchema']['properties']['action']['enum'], 'chat-tool-unknown')
        context = self.context(session['project_ref'], session['stage'])
        require(context['project_pin'] == session['project_pin'], 'chat-project-changed-open-new-session')
        require(args['action'] in context['supported_actions'], 'chat-action-not-supported-for-stage')
        return context

    @staticmethod
    def writes(args):
        return args['action'] in {'register_delivery', 'prepare_workflow', 'save_review', 'prepare_advice'}

    def proposal_pin(self, session, args):
        """Bind confirmation to the material, draft and workflow actually shown."""
        context = self.validate(session, args)
        catalog = self.materials.catalog()
        state = dict(context=context, args=args,
                     drafts=[x for x in catalog['drafts'] if x.get('project_ref') == session['project_ref']],
                     operations=[x for x in catalog['operations'] if x.get('project_ref') == session['project_ref']])
        if args['action'] == 'prepare_advice':
            state['delivery'] = self.host.stage2_handoffs._get(args['id'])
        return hashlib.sha256(encoded(state)).hexdigest()

    def call(self, session, args):
        context = self.validate(session, args)
        action, identity = args['action'], args['id']
        if action == 'state':
            return dict(context, research_execution=False)
        reader = getattr(self.host, 'independent_saved_stage2_reader', None)
        if session['stage'] == 2 and reader is not None and session['project_ref'] == reader.project_ref:
            if action == 'read_saved_stage':
                return reader.read(session['project_ref'], session['stage'], session['project_pin'], identity)
            if action == 'read_material' and reader.owns(identity):
                return reader.read_document(session['project_ref'], session['stage'], session['project_pin'], identity)
        if action in {'read_saved_stage', 'read_paper'}:
            require(session['project_ref'].startswith('view:'), 'chat-active-project-saved-output-not-yet-available')
            ref = session['project_ref'][5:]
            envelope = json.loads(self.host._assets['/v7-saved-runs/' + ref + '.json'])
            binding = envelope['binding']
            require(binding['manifest_sha256'] == session['project_pin'], 'chat-saved-output-binding-differs')
            payload_raw = envelope['payload_json'].encode()
            require(hashlib.sha256(payload_raw).hexdigest() == binding['payload_sha256'], 'chat-saved-output-bytes-differ')
            payload = json.loads(payload_raw)
            if action == 'read_paper':
                require(session['stage'] == 1, 'chat-paper-read-requires-stage1')
                paper = next((p for p in payload['index']['papers'] if p.get('work_id') == identity), None)
                require(paper is not None, 'chat-paper-not-found')
                result = paper
            else:
                result = payload['index'] if session['stage'] == 1 else payload.get('stage2')
                require(result is not None, 'chat-saved-stage-not-available')
            return dict(binding=binding, saved_result=result, research_generated=False)
        catalog = self.materials.catalog()
        if action == 'materials':
            return dict(context, workflows=[{k: o.get(k) for k in ('id', 'material_id', 'status', 'event_head')}
                for o in catalog['operations'] if o.get('project_ref') == session['project_ref'] and o.get('stage') == session['stage']])
        if action == 'register_delivery':
            require(identity in context['registered_delivery_ids'], 'chat-delivery-stage-differs')
            return self.materials.register_delivery(dict(project_ref=session['project_ref'], delivery_id=identity))
        if action == 'inspect_workflow':
            operation = self.materials._get('operations', identity)
            require(operation['project_ref'] == session['project_ref'] and operation['stage'] == session['stage'], 'chat-workflow-binding-differs')
            return self.materials.inspect(identity)
        if action == 'prepare_advice':
            require(session['stage'] == 2 and hasattr(self.host, 'stage2_handoffs'), 'chat-handoff-unavailable')
            # Do not accept free-form paths or manufacture a canonical registration.
            delivery = self.host.stage2_handoffs._get(identity)
            require(delivery['project_ref'] == session['project_ref'], 'chat-delivery-project-differs')
            return self.host.stage2_handoffs.prepare(dict(delivery_id=identity, project_ref=session['project_ref'],
                                                        input_sha256=delivery['input_sha256'], mode='advice'))
        material = next((m for m in context['materials'] if m['id'] == identity), None)
        require(material is not None, 'chat-material-binding-differs')
        if action == 'save_review':
            require(args['note'].strip(), 'chat-review-note-required')
            old = next((d for d in catalog['drafts'] if d['id'] == identity), None)
            return self.materials.draft(dict(id=identity, target_stage=session['stage'], note=args['note'],
                                            revision=old['revision'] if old else 0))
        if action == 'read_material' and session['stage'] != 2:
            if session['stage'] >= 3:
                require(self.stage_registry is not None, 'chat-stage-material-reader-unavailable')
                return self.stage_registry.read_material(session['project_ref'], session['stage'], session['project_pin'], identity)
            from harness_chat_stage_materials import read_registered_text
            return read_registered_text(self.materials, identity, session['project_ref'], session['stage'])
        require(session['stage'] == 2, 'chat-action-not-supported-for-stage')
        if action == 'handoff_status':
            require(hasattr(self.host, 'stage2_handoffs'), 'chat-handoff-unavailable')
            return self.host.stage2_handoffs.status(identity, session['project_ref'], material.get('packet_file_sha256') or material['sha256'])
        view = self.materials.packet_view(identity)
        if action == 'prepare_workflow':
            return self.materials.workflow(dict(id=identity, expected_sha256=material['sha256']))
        packet = json.loads(view['packet_text'])
        # Only bounded metadata and candidates go into the model; source originals stay on disk.
        return dict(material_id=identity, packet_sha256=view['packet_file_sha256'],
                    brief=packet['brief'], candidates=packet['candidates'], evidence=packet['evidence'],
                    sources=packet['sources'], formal_selection=view['formal_selection'],
                    research_generated=False, stage1_lineage=view['stage1_lineage'])
