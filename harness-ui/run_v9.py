"""Opt-in V9 renderer on the repository's existing loopback ProjectHost."""
import argparse
from pathlib import Path
import sys

import run_v7
from build_v7 import canonical, sha
from materials_http import install_materials
from display_translations import load_translations, translation_script
from review_reading import load_review_sources

HERE = Path(__file__).resolve().parent
MODULES = ('stage2_display.js', 'v9-i18n.js', 'v9-route-language.js', 'v9-workbench.js', 'v9-materials.js', 'v9-review-reading.js', 'v9-continuation.js')


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
    selection.add_argument('--ui-state-root', type=Path, required=True)
    selection.add_argument('--incoming-root', type=Path, required=True)
    selection.add_argument('--display-translations', type=Path)
    selection.add_argument('--review-sources', type=Path)
    selection.add_argument('--review-sources-sha256')
    selected, rest = selection.parse_known_args(sys.argv[1:] if argv is None else argv)
    state = private_directory(selected.ui_state_root)
    incoming = private_directory(selected.incoming_root)
    if not incoming.is_dir() or state.is_relative_to(incoming) or incoming.is_relative_to(state):
        raise ValueError('incoming must exist and be separate from UI state')
    translations = load_translations(selected.display_translations)
    review_sources = load_review_sources(selected.review_sources, selected.review_sources_sha256)
    original = run_v7.install_renderer

    def install(host, assets, meta, project_handler, atlas_handler):
        original(host, assets, meta, project_handler, atlas_handler)
        install_materials(host, host.projects, state, incoming, review_sources=review_sources)
        app = host._assets['/app.js']
        at = app.rfind(b'})();')
        if at < 0:
            raise ValueError('renderer closure missing')
        modules = {name: (HERE / name).read_bytes() for name in MODULES}
        host._assets['/app.js'] = app[:at] + b'\n' + translation_script(translations) + b'\n'.join(modules.values()) + b'\n' + app[at:]
        for route in ('/', '/index.html', '/app.js'):
            host._assets[route] = host._assets[route].replace(b'V7', b'V9') if route != '/app.js' else host._assets[route]
        host._assets['/runtime.css'] += b'\n' + (HERE/'stage2_display.css').read_bytes() + b'\n' + (HERE/'v9.css').read_bytes()
        host.host_binding['display_translations_sha256'] = sha(translation_script(translations))
        host.host_binding['review_sources_sha256'] = selected.review_sources_sha256
        host.host_binding.update(ui_version='V9', v9=dict(modules={k:sha(v) for k,v in modules.items()},
            material_registration=True, packet_projection=True, formal_selection=False,
            active_stage1='existing-bound-project-operations', model_permission='unchanged'))
        host.host_binding['served_files'] = {k:sha(v) for k,v in host._assets.items() if k != '/host-binding.json'}
        host._assets['/host-binding.json'] = canonical(host.host_binding)

    run_v7.install_renderer = install
    try:
        return run_v7.main(rest)
    finally:
        run_v7.install_renderer = original


if __name__ == '__main__':
    raise SystemExit(main())
