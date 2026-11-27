"""Bounded registered-text bridge for future trusted Stage3-6 adapters.

This module supplies no Core verifier and installs no provider. A trusted
bootstrap may compose it only after the real native Core verifier, independent
pins and legal material mapping are available. Test callbacks are not a
production verifier. Registered bytes are not scientific or human approval.
"""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import re
import stat

from harness_chat_stages import EVIDENCE_KIND, EVIDENCE_VERSION, require_stage


TEXT_LIMIT = 64 * 1024
EXTENSIONS = {'.txt', '.md', '.json', '.jsonl', '.csv', '.tsv', '.bib'}


def require(ok, code):
    if not ok:
        raise ValueError(code)


def _chain(path):
    values = []
    for item in [*reversed(path.parents), path]:
        info = item.lstat()
        require(not stat.S_ISLNK(info.st_mode)
                and not (getattr(info, 'st_file_attributes', 0) & 0x400),
                'chat-text-material-link-rejected')
        require(stat.S_ISDIR(info.st_mode) if item != path else stat.S_ISREG(info.st_mode),
                'chat-text-material-path-kind')
        values.append((info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)))
    return values


def _read_registered_text(materials, identity, project_ref, stage, *, expected_sha256=None):
    require(type(stage) is int and 1 <= stage <= 6, 'chat-stage-not-supported')
    require(isinstance(identity, str) and re.fullmatch(r'file-[0-9a-f]{32}', identity),
            'chat-registered-text-id-required')
    item = materials._get('materials', identity)
    require(item.get('id') == identity and item.get('project_ref') == project_ref
            and item.get('stage') == stage, 'chat-material-binding-differs')
    require(item.get('kind') == 'manual-file' and item.get('status') == 'registered',
            'chat-registered-text-material-required')
    require(isinstance(item.get('name'), str) and Path(item['name']).suffix.lower() in EXTENSIONS,
            'chat-text-material-extension-required')
    require(type(item.get('bytes')) is int and 0 <= item['bytes'] <= TEXT_LIMIT,
            'chat-text-material-too-large')
    require(isinstance(item.get('sha256'), str) and re.fullmatch(r'[0-9a-f]{64}', item['sha256']),
            'chat-text-material-pin-required')
    require(expected_sha256 is None or item['sha256'] == expected_sha256,
            'chat-text-material-external-pin-differs')
    root = Path(materials.root)
    require(root.is_absolute(), 'chat-text-material-absolute-root-required')
    path = root / 'files' / (identity + '.bin')
    before = _chain(path)
    require(path.resolve(strict=True).is_relative_to(root.resolve(strict=True)),
            'chat-text-material-path-escaped')
    with path.open('rb') as stream:
        raw = stream.read(TEXT_LIMIT + 1)
        opened = os.fstat(stream.fileno())
    opened_identity = (opened.st_dev, opened.st_ino, stat.S_IFMT(opened.st_mode))
    require(stat.S_ISREG(opened.st_mode) and opened_identity == before[-1]
            and _chain(path) == before, 'chat-text-material-path-changed')
    require(len(raw) == item['bytes'] and hashlib.sha256(raw).hexdigest() == item['sha256'],
            'chat-text-material-bytes-differ')
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError as error:
        raise ValueError('chat-text-material-utf8-required') from error
    require(not any((ord(c) < 32 and c not in '\t\r\n') or ord(c) == 127 for c in text),
            'chat-binary-material-rejected')
    return dict(material_id=identity, project_ref=project_ref, stage=stage,
                name=item['name'], sha256=item['sha256'], bytes=len(raw), text=text,
                content_status='registered-text-not-screened-or-verified',
                research_generated=False, execution_authorized=False)


def read_registered_text(materials, identity, project_ref, stage, *, expected_sha256=None):
    try:
        return _read_registered_text(materials, identity, project_ref, stage,
                                     expected_sha256=expected_sha256)
    except OSError:
        raise ValueError('chat-text-material-file-unavailable') from None


class VerifiedRegisteredStageProvider:
    """Compose a real native preflight with independently pinned registered IDs.

    native_preflight(project, stage, pin, material_pins, evidence_binding) must
    be trusted owning-backend code which checks the original native contracts,
    dependency closure and legal project/run/material mapping. It must be
    bounded, read-only, raise on refusal and return None on success. This class
    cannot implement or replace missing producer/verifier/human authentication.
    """

    def __init__(self, materials, *, project_ref, stage, project_pin, material_pins,
                 evidence_binding, native_preflight, implementation_sha256):
        require_stage(stage)
        require(stage >= 3, 'chat-stage-established-adapter-cannot-be-replaced')
        require(callable(native_preflight), 'chat-stage-native-preflight-required')
        require(isinstance(material_pins, dict) and 1 <= len(material_pins) <= 32,
                'chat-stage-real-material-mapping-required')
        require(all(isinstance(k, str) and re.fullmatch(r'file-[0-9a-f]{32}', k)
                    and isinstance(v, str) and re.fullmatch(r'[0-9a-f]{64}', v)
                    for k, v in material_pins.items()), 'chat-stage-material-mapping-invalid')
        require(isinstance(evidence_binding, dict) and 'manifest_sha256' in evidence_binding
                and all(isinstance(k, str) and re.fullmatch(r'[a-zA-Z0-9_.:-]{1,120}', k)
                        and isinstance(v, str) and re.fullmatch(r'[0-9a-f]{64}', v)
                        for k, v in evidence_binding.items()), 'chat-stage-evidence-binding-required')
        self.materials, self.project_ref, self.stage, self.project_pin = materials, project_ref, stage, project_pin
        self.material_pins, self.evidence_binding = deepcopy(material_pins), deepcopy(evidence_binding)
        self.native_preflight, self.implementation_sha256 = native_preflight, implementation_sha256
        self._preflight()

    def _preflight(self):
        try:
            actual_implementation = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        except OSError:
            raise ValueError('chat-stage-provider-implementation-unavailable') from None
        require(actual_implementation == self.implementation_sha256,
                'chat-stage-provider-implementation-bytes-differ')
        try:
            result = self.native_preflight(self.project_ref, self.stage, self.project_pin,
                                          deepcopy(self.material_pins), deepcopy(self.evidence_binding))
        except Exception:
            raise ValueError('chat-stage-native-preflight-refused') from None
        require(result is None, 'chat-stage-native-preflight-not-confirmed')

    def __call__(self, project, stage, project_pin):
        require((project, stage, project_pin) == (self.project_ref, self.stage, self.project_pin),
                'chat-stage-provider-binding-differs')
        self._preflight()
        documents = []
        for identity, pin in self.material_pins.items():
            value = read_registered_text(self.materials, identity, project, stage, expected_sha256=pin)
            documents.append({k: value[k] for k in ('material_id', 'name', 'sha256', 'bytes', 'content_status')})
        return dict(kind=EVIDENCE_KIND, version=EVIDENCE_VERSION, project_ref=project,
                    stage=stage, project_pin=project_pin, binding=deepcopy(self.evidence_binding), missing=[],
                    context=dict(registered_text_materials=documents, verified_bytes_only=True,
                                 scientific_validation=False, formal_selection=False,
                                 research_execution=False, native_contract_checks_owned_by_backend=True))

    def read_material(self, project, stage, project_pin, identity):
        self(project, stage, project_pin)
        require(identity in self.material_pins, 'chat-stage-material-not-in-native-mapping')
        return read_registered_text(self.materials, identity, project, stage,
                                    expected_sha256=self.material_pins[identity])
