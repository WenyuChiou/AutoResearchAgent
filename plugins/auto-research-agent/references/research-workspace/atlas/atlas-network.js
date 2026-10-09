/* Shared Stage 1/2 presentation lifecycle. No producer data or execution changes. */
(function (root) {
  "use strict";
  function mount(parent, options) {
    const {papers, model, language, t, onSelect, focus, pose, settings} = options;
    let spatial = null, dead = false, ticket = 0; const faults = [];
    const controls = document.createElement("div"), host = document.createElement("div");
    controls.className = "atlas-actions atlas-spatial-controls";
    host.className = "atlas-spatial-host"; host.setAttribute("aria-label", t("networkTitle"));
    host.atlasDiagnostics = () => spatial?.diagnostics() || {mounted: false, faults: [...faults]};
    const choose = (label, action) => {
      const control = document.createElement("button"); control.type = "button";
      control.textContent = label; control.onclick = action; controls.append(control); return control;
    };
    const modeButtons = [2, 3].map(mode => choose(`${mode}D`, () => {
      if (!spatial || dead) return;
      spatial.setMode(mode); settings.mode = mode;
      modeButtons.forEach((b, i) => b.setAttribute("aria-pressed", String([2, 3][i] === mode)));
    }));
    modeButtons.forEach((b, i) => b.setAttribute("aria-pressed", String([2, 3][i] === settings.mode)));
    const toggle = document.createElement("label"), input = document.createElement("input"), caption = document.createElement("span");
    toggle.className = "atlas-check"; input.type = "checkbox"; input.checked = settings.computed;
    caption.textContent = t("computedLinks"); toggle.append(input, caption); controls.append(toggle);
    input.onchange = () => {settings.computed = input.checked; options.onSettings?.();};
    const labels = document.createElement("label"), labelInput = document.createElement("input"), labelCaption = document.createElement("span");
    labels.className = "atlas-check"; labelInput.type = "checkbox"; labelInput.checked = settings.showLabels === true;
    labelCaption.textContent = t("showAllNames"); labels.append(labelInput, labelCaption); controls.append(labels);
    labelInput.onchange = () => {if (dead) return; settings.showLabels = labelInput.checked; spatial?.setLabels(labelInput.checked);};
    choose(t("fit"), () => {if (!dead) spatial?.fit();});
    const help = document.createElement("p"); help.className = "atlas-small"; help.textContent = t("spatialHelp");
    const shapes = document.createElement("div"); shapes.className = "atlas-node-legend";
    for (const [kind, label] of [["paper", "paperShape"], ["topic", "topicShape"], ["method", "methodShape"]]) {
      const item = document.createElement("span"), icon = document.createElement("i"), text = document.createElement("span");
      icon.dataset.nodeKind = kind; icon.setAttribute("aria-hidden", "true"); text.textContent = t(label); item.append(icon, text); shapes.append(item);
    }
    const legend = document.createElement("div"); legend.className = "atlas-graph-legend";
    for (const [kind, label] of [["direction", "directionLink"], ["method", "methodLink"], ["overlap", "overlapLink"], ...(settings.computed ? [["similarity", "computedLinks"]] : [])]) {
      const item = document.createElement("span"), sample = document.createElement("i"), text = document.createElement("span");
      sample.dataset.kind = kind; text.textContent = t(label); item.append(sample, text); legend.append(item);
    }
    const relationBox = document.createElement("details"), relationTitle = document.createElement("summary");
    relationTitle.textContent = t("graphBasis"); relationBox.className = "atlas-relation-list";
    relationBox.append(relationTitle);
    const associations = root.AtlasAssociations.build(papers, {neighbors: 2, threshold: .09});
    const extraLinks = [...associations.recorded, ...(settings.computed ? [...associations.lexical, ...associations.lexicalTopics] : [])];
    const paperById = new Map(papers.map(p => [p.key, p]));
    const endpointTitle = p => p.type === "paper" ? paperById.get(p.key)?.title || p.key : p.key;
    extraLinks.forEach(edge => {
      const row = document.createElement("p"), computed = edge.kind.startsWith("lexical"); row.translate = false;
      const terms = edge.shared_terms?.length ? edge.shared_terms : edge.shared_papers || [];
      row.textContent = `${endpointTitle(edge.from)} ↔ ${endpointTitle(edge.to)} · ${computed ? t("computedLinks") + " " + (100 * edge.score).toFixed(1) + "%" : t("overlapLink")} · ${terms.join(" / ")}`;
      relationBox.append(row);
    });
    const note = document.createElement("p"); note.className = "atlas-small"; note.textContent = t("spatialBasis");
    parent.append(controls, host, help, shapes, legend, note, relationBox);
    const current = ++ticket;
    root.queueMicrotask(() => {
      if (dead || current !== ticket || !host.isConnected) return;
      try {
        spatial = root.AtlasSpatial.mount(host, {papers, model, language, focus, pose,
          mode: settings.mode, showLabels: settings.showLabels === true, extraLinks, topicColors: options.topicColors, paperAliases: options.paperAliases, onSelect: value => {if (!dead) onSelect(value);}});
      } catch (cause) {
        faults.push(String(cause));
        const error = document.createElement("p"); error.className = "atlas-note";
        error.textContent = t("spatialUnavailable"); host.append(error);
        const fallback = document.createElement("button"); fallback.type = "button";
        fallback.textContent = t("planarFallback"); fallback.onclick = () => options.onFallback?.(); host.append(fallback);
      }
    });
    return {
      snapshot: () => spatial?.snapshot() || pose,
      diagnostics: host.atlasDiagnostics,
      destroy: () => {if (dead) return; dead = true; ticket++; spatial?.destroy();}
    };
  }
  root.AtlasNetwork = {mount};
})(window);
