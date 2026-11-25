// A bounded GET-only restart for missing startup assets. Never touch action state.
(() => {
  const address = location.href;
  const marker = 'wiki-startup-retry-v1';
  const required = new Set(['/project-bootstrap.js', '/app.js', '/project-stage2-selection.js']);
  const loaded = new Set();
  let settled = false;
  function scriptPath(node) {
    if (node?.tagName !== 'SCRIPT' || !node.src) return null;
    const url = new URL(node.src, address);
    return url.origin === location.origin ? url.pathname : null;
  }
  document.addEventListener('load', event => {
    const path = scriptPath(event.target);
    if (required.has(path)) loaded.add(path);
  }, true);
  function controls() {
    const panel = document.getElementById('wiki-startup-recovery');
    const retry = document.getElementById('wiki-startup-retry');
    if (retry && !retry.dataset.bound) {
      retry.dataset.bound = 'true';
      retry.hidden = false;
      retry.addEventListener('click', () => location.reload());
    }
    return panel;
  }
  document.addEventListener('DOMContentLoaded', controls, {once: true});
  function finish() {
    if (settled) return;
    settled = true;
    clearTimeout(deadline);
    const panel = controls();
    const scripts = [...document.querySelectorAll('script[src]')].map(scriptPath).filter(path => required.has(path));
    if (scripts.length && scripts.every(path => loaded.has(path))) {
      if (panel) panel.hidden = true;
      try { if (sessionStorage.getItem(marker) === address) sessionStorage.removeItem(marker); } catch (_) {}
      return;
    }
    if (panel) panel.dataset.state = 'failed';
    // Persist before navigating; unavailable storage means manual recovery only.
    try {
      if (sessionStorage.getItem(marker) === address) return;
      sessionStorage.setItem(marker, address);
      if (sessionStorage.getItem(marker) !== address) return;
    } catch (_) { return; }
    location.reload();
  }
  window.addEventListener('load', finish, {once: true});
  const deadline = setTimeout(finish, 10000);
})();
