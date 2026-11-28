"""Opt-in V9 renderer on the repository's existing loopback ProjectHost."""
import argparse
from pathlib import Path
import re
import sys

import run_v7
from build_v7 import canonical, sha
from materials_http import install_materials
from display_translations import load_translations, translation_script
from review_reading import load_review_sources
from current_chat_host import add_arguments as add_chat_arguments, install_wiki_chat, validate_options as validate_chat_options

HERE = Path(__file__).resolve().parent
MODULES = ('stage2_display.js', 'v9-i18n.js', 'v9-route-language.js', 'v9-workbench.js', 'v9-materials.js', 'v9-review-reading.js', 'v9-continuation.js', 'v9-stage-connections.js', 'v9-stage3-bridge.js', 'v9-research-guide-contract.js', 'v9-research-guide-view.js', 'v9-research-guide.js', 'v9-stage3-materials.js', 'v9-stage3-feedback.js', 'v9-quantitative-contract.js', 'v9-quantitative-view.js', 'v9-quantitative-guide.js', 'wiki-v1-text.js', 'wiki-harness-record.js', 'wiki-home.js', 'wiki-stage1.js', 'wiki-stage1-ops.js', 'wiki-stage1-materials.js', 'wiki-stage1-grant.js', 'wiki-stage2.js', 'wiki-stage3.js', 'wiki-stage3-plan-request.js', 'wiki-stage3-decision.js', 'wiki-v1.js', 'wiki-v1-global.js', 'wiki-chat.js')


def private_directory(path):
    path = path.absolute()
    if any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction())
           for p in (path, *path.parents)):
        raise ValueError('private directory must not traverse links')
    if any((p / '.git').exists() for p in (path, *path.parents)):
        raise ValueError('private data must stay outside Git checkouts')
    return path.resolve()


def main(argv=None):
    selection = argparse.ArgumentParser(add_help=False)
    wants_help = run_v7.asks_for_help(sys.argv[1:] if argv is None else argv)
    selection.add_argument('--ui-state-root', type=Path, required=not wants_help)
    selection.add_argument('--incoming-root', type=Path, required=not wants_help)
    selection.add_argument('--display-translations', type=Path)
    selection.add_argument('--review-sources', type=Path)
    selection.add_argument('--review-sources-sha256')
    add_chat_arguments(selection)
    selected, rest = selection.parse_known_args(sys.argv[1:] if argv is None else argv)
    if wants_help:
        return run_v7.main(rest)  # prints the full option help and exits
    validate_chat_options(selected)
    state = private_directory(selected.ui_state_root)
    incoming = private_directory(selected.incoming_root)
    if not incoming.is_dir() or state.is_relative_to(incoming) or incoming.is_relative_to(state):
        raise ValueError('incoming must exist and be separate from UI state')
    translations = load_translations(selected.display_translations)
    review_sources = load_review_sources(selected.review_sources, selected.review_sources_sha256)
    original = run_v7.install_renderer

    def install(host, assets, meta, project_handler, atlas_handler):
        original(host, assets, meta, project_handler, atlas_handler)
        # Grant creation/reading is a Wiki route, so it also exists without a consent file.
        from wiki_stage1_run_grant_http import install_stage1_run_grant

        install_stage1_run_grant(
            host, limits=meta['run_limits'], runtime_sha256=meta['harness_inventory_sha256'])
        install_materials(host, host.projects, state, incoming, review_sources=review_sources)
        # Codex chat routes: off unless the operator passed --chat-config; never starts Codex by itself.
        chat = install_wiki_chat(host, host.materials, selected)
        app = host._assets['/app.js']
        at = app.rfind(b'})();')
        if at < 0:
            raise ValueError('renderer closure missing')
        modules = {name: (HERE / name).read_bytes() for name in MODULES}
        host._assets['/app.js'] = app[:at] + b'\n' + translation_script(translations) + b'\n'.join(modules.values()) + b'\n' + app[at:]
        selection = host._assets['/project-stage2-selection.html']
        main_tags = list(re.finditer(rb'<main(?:\s[^<>]*)?>', selection))
        if (len(main_tags) != 1 or selection.count(b'</main>') != 1
                or main_tags[0].end() > selection.index(b'</main>')):
            raise ValueError('selection template structure differs')
        selection_main = selection[main_tags[0].start():selection.index(b'</main>') + len(b'</main>')]
        if b'<script' in selection_main.lower() or b'<iframe' in selection_main.lower():
            raise ValueError('selection template contains executable content')
        template = b'<template id="v93-selection-template">' + selection_main + b'</template>'
        scripts = (b'<script defer src="/project-stage3-research-diagram.js"></script>'
                   b'<script defer src="/project-stage2-selection.js"></script>')
        for route in ('/', '/index.html'):
            html = host._assets[route]
            if html.count(b'</head>') != 1 or html.count(b'</body>') != 1:
                raise ValueError('Wiki document structure differs')
            host._assets[route] = html.replace(b'</head>', scripts + b'</head>').replace(b'</body>', template + b'</body>')
        for route in ('/', '/index.html', '/app.js'):
            host._assets[route] = host._assets[route].replace(b'V7', b'V9') if route != '/app.js' else host._assets[route]
        host._assets['/runtime.css'] += b'\n' + (HERE/'stage2_display.css').read_bytes() + b'\n' + (HERE/'v9.css').read_bytes() + b'\n' + (HERE/'v9-research-guide.css').read_bytes() + b'\n' + (HERE/'v9-stage3-feedback.css').read_bytes() + b'\n' + (HERE/'v9-quantitative-view.css').read_bytes()
        host._assets['/runtime.css'] += b'\n' + (HERE/'wiki-home.css').read_bytes()
        host._assets['/runtime.css'] += b'\n' + (HERE/'wiki-stage1.css').read_bytes()
        host._assets['/runtime.css'] += b'\n' + (HERE/'wiki-stage1-ops.css').read_bytes()
        host._assets['/runtime.css'] += b'\n' + (HERE/'wiki-stage1-grant.css').read_bytes()
        host._assets['/runtime.css'] += b'\n' + (HERE/'wiki-stage2.css').read_bytes()
        host._assets['/runtime.css'] += b'\n' + (HERE/'wiki-stage3.css').read_bytes()
        host._assets['/runtime.css'] += b'\n' + (HERE/'wiki-v1.css').read_bytes()
        host._assets['/runtime.css'] += b'\n' + (HERE/'wiki-v1-global.css').read_bytes()
        host._assets['/runtime.css'] += b'\n' + (HERE/'wiki-chat.css').read_bytes()
        host.host_binding['display_translations_sha256'] = sha(translation_script(translations))
        host.host_binding['review_sources_sha256'] = selected.review_sources_sha256
        host.host_binding.update(ui_version='V9', v9=dict(modules={k:sha(v) for k,v in modules.items()},
            material_registration=True, packet_projection=True, formal_selection=False,
            formal_selection_scope='manual-packet-only',
            current_delivery_selection_configured=bool(host.project_stage2_selection and host.project_stage2_selection.bindings),
            stage3_planning_configured=bool(host.project_stage3_http and host.project_stage3_http.service.bindings),
            configuration_is_not_selection=True,
            active_stage1='existing-bound-project-operations', model_permission='unchanged'),
            chat=dict(configured=chat.spec is not None, disabled_reason=getattr(chat, 'reason', None),
                      read_only=True, research_execution=False, formal_selection=False))
        host.host_binding['served_files'] = {k:sha(v) for k,v in host._assets.items() if k != '/host-binding.json'}
        host._assets['/host-binding.json'] = canonical(host.host_binding)

    run_v7.install_renderer = install
    try:
        return run_v7.main(rest)
    finally:
        run_v7.install_renderer = original


if __name__ == '__main__':
    raise SystemExit(main())
