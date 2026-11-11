(() => {
  const points = Array.from(document.querySelectorAll('[data-step]'));
  const topics = Array.from(document.querySelectorAll('[data-topic]'));
  const previous = document.querySelector('#previous');
  const next = document.querySelector('#next');
  const position = document.querySelector('#position');
  const stepMode = document.querySelector('#step-mode');
  const codeMode = document.querySelector('#code-mode');
  const varsMode = document.querySelector('#vars-mode');
  const sourcePreview = document.querySelector('#source-preview');
  const calculationCode = document.querySelector('#python-code');
  const progress = document.querySelector('#playback-progress');
  const jump = document.querySelector('#jump');
  const toolbar = document.querySelector('#toolbar');
  const dialog = document.querySelector('#figure-dialog');
  const largeImage = dialog.querySelector('img');
  let index = 0;
  let figureTrigger;
  let variableFrame;
  let renderedFrame;
  const calculation = document.querySelector('#share-calculation');
  const variables = document.querySelector('#variables');
  const variableList = document.querySelector('#variable-list');
  const frames = JSON.parse(document.querySelector('#calculation-frames').textContent);

  function syncVariables() {
    variableFrame = undefined;
    const point = points[index];
    const frame = stepMode.checked && varsMode.checked ? point.dataset.frame : undefined;
    const bounds = calculation.getBoundingClientRect();
    const visible = bounds.bottom > toolbar.getBoundingClientRect().bottom
      && bounds.top < window.innerHeight;
    const activeFrame = visible ? frame : undefined;
    if (activeFrame === renderedFrame) return;
    renderedFrame = activeFrame;
    variableList.replaceChildren();
    variables.hidden = !activeFrame;
    if (!activeFrame) return;
    for (const [name, value, detail] of frames[activeFrame]) {
      const term = document.createElement('dt');
      term.textContent = name;
      const description = document.createElement('dd');
      description.textContent = value + ' · ' + detail;
      variableList.append(term, description);
    }
  }

  function scheduleVariables() {
    if (variableFrame === undefined) variableFrame = requestAnimationFrame(syncVariables);
  }

  points.forEach((point, i) => { point.dataset.stepNumber = i + 1; });
  progress.max = points.length;

  function render() {
    points.forEach((point, i) => {
      point.classList.toggle('future', stepMode.checked && i > index);
      if (stepMode.checked && i === index) point.setAttribute('aria-current', 'step');
      else point.removeAttribute('aria-current');
    });
    previous.disabled = !stepMode.checked || index === 0;
    next.disabled = !stepMode.checked || index === points.length - 1;
    progress.value = stepMode.checked ? index + 1 : 0;
    position.value = progress.value + ' / ' + points.length;
    if (stepMode.checked) jump.value = points[index].closest('[data-topic]').id;
    scheduleVariables();
  }

  function firstPoint(topic) {
    return points.findIndex(point => point.closest('[data-topic]') === topic);
  }

  function reveal(targetIndex, targetTopic) {
    if (targetIndex < 0 || targetIndex >= points.length) return;
    const point = points[targetIndex];
    const oldTopic = points[index].closest('[data-topic]');
    const newTopic = targetTopic || point.closest('[data-topic]');
    index = targetIndex;
    render();

    if (targetTopic || oldTopic !== newTopic) {
      jump.value = newTopic.id;
      const destination = targetTopic || targetIndex === firstPoint(newTopic) ? newTopic : point;
      destination.scrollIntoView({block: 'start'});
      if (targetTopic) document.getElementById(newTopic.getAttribute('aria-labelledby')).focus({preventScroll: true});
    } else {
      const rect = point.getBoundingClientRect();
      if (rect.top < toolbar.getBoundingClientRect().bottom || rect.bottom > window.innerHeight - 18) {
        point.scrollIntoView({block: 'start'});
      }
    }
  }

  previous.addEventListener('click', () => reveal(index - 1));
  next.addEventListener('click', () => reveal(index + 1));
  stepMode.addEventListener('change', render);
  varsMode.addEventListener('change', scheduleVariables);
  codeMode.addEventListener('change', () => {
    sourcePreview.hidden = !codeMode.checked;
    calculationCode.hidden = !codeMode.checked;
    scheduleVariables();
  });
  jump.addEventListener('change', () => {
    const topic = topics.find(item => item.id === jump.value);
    if (topic) reveal(firstPoint(topic), topic);
  });

  document.addEventListener('keydown', event => {
    if (event.defaultPrevented || dialog.open ||
        event.altKey || event.ctrlKey || event.metaKey || event.shiftKey ||
        event.target.closest?.('select, input:not([type=checkbox]), textarea, [contenteditable]')) return;
    const key = event.key.toLowerCase();
    const toggle = key === 'a' ? stepMode : key === 'r' ? codeMode : key === 'e' ? varsMode : null;
    if (toggle) {
      event.preventDefault();
      toggle.click();
      return;
    }
    if (stepMode.checked && (event.key === 'ArrowRight' || event.key === 'ArrowLeft')) {
      event.preventDefault();
      reveal(index + (event.key === 'ArrowRight' ? 1 : -1));
    }
  });

  document.querySelector('main').addEventListener('contextmenu', event => {
    if (!stepMode.checked || dialog.open || event.shiftKey || event.target.closest(
      'a, button, img, input, select, textarea, summary, pre, code, [contenteditable]'
    )) return;
    if (window.getSelection()?.toString() || index === points.length - 1) return;
    event.preventDefault();
    reveal(index + 1);
  });
  window.addEventListener('scroll', scheduleVariables, {passive: true});
  window.addEventListener('resize', scheduleVariables);
  calculation.addEventListener('toggle', scheduleVariables, true);

  for (const button of document.querySelectorAll('.figure-button')) {
    button.addEventListener('click', () => {
      figureTrigger = button;
      const source = button.querySelector('img');
      largeImage.src = source.src;
      largeImage.alt = source.alt;
      largeImage.style.setProperty('--enlarged-width', source.naturalWidth + 'px');
      dialog.showModal();
      dialog.scrollTop = 0;
      dialog.scrollLeft = 0;
    });
  }

  dialog.addEventListener('close', () => figureTrigger?.focus({preventScroll: true}));
  new ResizeObserver(() => {
    document.documentElement.style.setProperty('--toolbar', toolbar.offsetHeight + 'px');
    scheduleVariables();
  }).observe(toolbar);
  render();
  function openLinkedTopic() {
    if (window.location.hash === '#share-calculation') {
      stepMode.checked = true;
      reveal(points.findIndex(point => point.dataset.frame === 'operands'));
      calculation.scrollIntoView({block: 'start'});
      return;
    }
    const topic = topics.find(item => '#' + item.id === window.location.hash);
    if (topic) reveal(firstPoint(topic), topic);
  }

  window.addEventListener('hashchange', openLinkedTopic);
  requestAnimationFrame(openLinkedTopic);
})();
