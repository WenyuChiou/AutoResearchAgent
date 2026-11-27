"""Host-owned local file closure; manifests do not choose runtime locations."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent


def runtime_module_paths():
    """Map every chat runtime module to the file this checkout actually loads.

    The closure is the chat modules next to this file plus the process channel
    in ``native_stage1.py``. Nothing outside ``harness-ui`` is consulted.
    """
    result = {}
    for path in sorted(HERE.glob('*.py')):
        if not path.stem.isidentifier() or path.name.startswith('test_'):
            continue
        if not (path.name.startswith('harness_chat') or path.name in {'current_chat_host.py', 'chat_operator_prepare.py'}):
            continue
        module = sys.modules.get(path.stem)
        actual = getattr(module, '__file__', None) if module is not None else None
        if actual and Path(actual).resolve() != path.resolve():
            raise ValueError('chat-runtime-loaded-module-path-differs')
        result[path.stem] = str(Path(actual).resolve() if actual else path.resolve())
    # The original process channel is intentionally outside the chat modules.
    expected = HERE / 'native_stage1.py'
    module = sys.modules.get('native_stage1')
    actual = getattr(module, '__file__', None) if module is not None else None
    if actual and Path(actual).resolve() != expected.resolve():
        raise ValueError('chat-runtime-native-channel-path-differs')
    result['native_stage1'] = str(expected.resolve())
    # These sources can change client-side gating but never grant authorization.
    asset = HERE / 'v9-harness-chat.js'
    if asset.is_file():
        result['ui_chat_asset'] = str(asset)
    return result
