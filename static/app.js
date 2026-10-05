(() => {
  "use strict";

  const state = {
    incidents: [],
    filter: "all",
    selectedId: null,
    lastReport: null,
    toastTimer: null,
    contracts: {},
    original: null,
    scenario: null,
    referenceSim: null,
    simSequence: 0,
    simTimer: null,
    evaluation: null,
    started: false,
  };

  const $ = (id) => document.getElementById(id);
  const elements = {
    analyze: $("analyzeIncident"),
    auditList: $("auditList"),
    caseActions: $("caseActions"),
    caseContent: $("caseContent"),
    caseFacts: $("caseFacts"),
    caseReference: $("caseReference"),
    caseStatus: $("caseStatus"),
    closeSourceDialog: $("closeSourceDialog"),
    decision: $("decision"),
    decisionHint: $("decisionHint"),
    decisionReceipt: $("decisionReceipt"),
    decisionTime: $("decisionTime"),
    evaluationCount: $("evaluationCount"),
    healthLabel: $("healthLabel"),
    incidentList: $("incidentList"),
    openCount: $("openCount"),
    queueCount: $("queueCount"),
    refreshAudit: $("refreshAudit"),
    reviewFeedback: $("reviewFeedback"),
    resetScenario: $("resetScenario"),
    resetScenarioBanner: $("resetScenarioBanner"),
    reviewNote: $("reviewNote"),
    scenarioBanner: $("scenarioBanner"),
    scenarioState: $("scenarioState"),
    scoreResult: $("scoreResult"),
    triageScope: $("triageScope"),
    sourceCardText: $("sourceCardText"),
    sourceCount: $("sourceCount"),
    sourceDetails: $("sourceDetails"),
    sourceDialog: $("sourceDialog"),
    sourceReceipt: $("sourceReceipt"),
    syncSource: $("syncSource"),
    toast: $("toast"),
    triageIntro: $("triageIntro"),
    triageResult: $("triageResult"),
    triageState: $("triageState"),
  };
  const choiceButtons = () => [...elements.decision.querySelectorAll("[data-review-outcome]")];

  const severityOrder = { "SEV-1": 1, "SEV-2": 2, "SEV-3": 3 };
  const closedStatuses = new Set(["resolved", "closed"]);

  const labels = {
    status: { investigating: "en investigation", triage: "en triage", open: "ouvert", resolved: "résolu", closed: "clos" },
    tier: { critical: "critique", high: "élevé", medium: "moyen", low: "faible" },
    kind: { quality: "qualité", lineage: "lignage", consumer: "consommateurs", contract: "contrat", freshness: "fraîcheur" },
    gate: { blocked: "publication bloquée", review_required: "revue requise avant publication" },
    sourceType: { data_contract: "contrat", runbook: "runbook", signal: "signal" },
    check: { pass: "conforme", needs_review: "à revoir" },
    event: {
      triage_generated: "Triage produit",
      operator_review_recorded: "Décision enregistrée",
      public_source_synced: "Statut GitHub lu",
    },
    outcome: { accepted: "triage accepté", needs_evidence: "éléments demandés", rejected: "proposition rejetée" },
    indicator: {
      none: "aucune perturbation signalée",
      minor: "perturbation mineure",
      major: "perturbation majeure",
      critical: "panne critique",
      unavailable: "source injoignable",
    },
  };

  const label = (group, value) => labels[group]?.[value] ?? String(value ?? "").replaceAll("_", " ");

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function formatDate(value, { seconds = false, year = false } = {}) {
    if (!value) return "heure non enregistrée";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return (
      new Intl.DateTimeFormat("fr-FR", {
        day: "numeric",
        month: "short",
        ...(year ? { year: "numeric" } : {}),
        hour: "2-digit",
        minute: "2-digit",
        ...(seconds ? { second: "2-digit" } : {}),
        timeZone: "UTC",
      }).format(date) + " UTC"
    );
  }

  const formatScore = (value) =>
    Number(value || 0).toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const plural = (count, singular, pluralForm) => `${count} ${count > 1 ? pluralForm : singular}`;

  const severityTag = (severity) =>
    `<span class="sev${severity === "SEV-1" ? " is-critical" : ""}">${escapeHtml(severity)}</span>`;

  const fieldList = (rows) =>
    `<dl class="form-fields">${rows
      .filter(([, value]) => value !== undefined && value !== null && value !== "")
      .map(([name, value]) => `<div><dt>${name}</dt><dd>${value}</dd></div>`)
      .join("")}</dl>`;

  const sectionTitle = (num, text) => `<h3><span class="num">${num}</span>${text}</h3>`;

  async function api(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: { Accept: "application/json", ...(options.headers || {}) },
    });
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
      const detail = typeof payload === "object" ? payload.detail : payload;
      throw new Error(typeof detail === "string" && detail ? detail : `erreur HTTP ${response.status}`);
    }
    return payload;
  }

  function showToast(message, isError = false) {
    clearTimeout(state.toastTimer);
    elements.toast.textContent = message;
    elements.toast.classList.toggle("is-error", isError);
    elements.toast.classList.add("is-visible");
    state.toastTimer = window.setTimeout(() => elements.toast.classList.remove("is-visible"), 4300);
  }

  function setTriageState(text) {
    elements.triageState.textContent = text;
  }

  const selectedIncident = () => state.incidents.find((incident) => incident.id === state.selectedId);

  function sortIncidents(incidents) {
    return [...incidents].sort((a, b) => {
      const severityDiff = (severityOrder[a.severity] || 9) - (severityOrder[b.severity] || 9);
      if (severityDiff) return severityDiff;
      return new Date(a.opened_at || 0) - new Date(b.opened_at || 0);
    });
  }

  /* File */

  function renderQueue() {
    const visible = state.incidents.filter((incident) => state.filter === "all" || incident.severity === state.filter);
    const open = state.incidents.filter((incident) => !closedStatuses.has(incident.status)).length;

    elements.openCount.textContent = plural(open, "incident ouvert", "incidents ouverts");
    elements.queueCount.textContent = `${plural(visible.length, "incident affiché", "incidents affichés")}, triés par sévérité puis par heure d'ouverture.`;

    if (!visible.length) {
      elements.incidentList.innerHTML = '<p class="quiet">Aucun incident de cette sévérité dans la file.</p>';
      return;
    }

    elements.incidentList.innerHTML = `<ul class="queue-list">${visible
      .map((incident) => {
        const selected = incident.id === state.selectedId;
        return `
          <li>
            <button class="queue-item${selected ? " is-selected" : ""}" type="button" data-incident-id="${escapeHtml(incident.id)}" aria-pressed="${selected}">
              <span class="queue-line"><span class="code">${escapeHtml(incident.id)}</span>${severityTag(incident.severity)}<span class="queue-status">${escapeHtml(label("status", incident.status))}</span></span>
              <span class="queue-title">${escapeHtml(incident.title)}</span>
              <span class="queue-time">ouvert le ${escapeHtml(formatDate(incident.opened_at))}</span>
            </button>
          </li>`;
      })
      .join("")}</ul>`;
  }

  /* Fiche */

  function renderCase({ incident, contract }) {
    elements.caseReference.textContent = incident.id;
    elements.caseStatus.textContent = label("status", incident.status);
    elements.caseActions.hidden = false;
    elements.decision.hidden = false;

    state.original = { incident, contract };
    if (!state.contracts[contract.id]) state.contracts[contract.id] = contract;
    state.scenario = referenceScenario();
    state.referenceSim = null;

    const signals = incident.signals || [];
    const contractIds = Object.keys(state.contracts);
    const severities = ["SEV-1", "SEV-2", "SEV-3"];

    elements.caseContent.innerHTML = `<h2 id="case-title">${escapeHtml(incident.title)}</h2>`;

    elements.caseFacts.innerHTML = `
      <p class="edit-hint small quiet">Les champs encadrés sont modifiables : le score se recalcule avec le moteur de Sillage, sans rien enregistrer.</p>
      <section>
        ${sectionTitle(1, "Identification")}
        ${fieldList([
          [
            '<label for="scSeverity">Sévérité</label>',
            `<select class="field" id="scSeverity">${severities
              .map((sev) => `<option value="${sev}"${sev === incident.severity ? " selected" : ""}>${sev}</option>`)
              .join("")}</select>`,
          ],
          ["Ouvert le", `<span class="nums">${escapeHtml(formatDate(incident.opened_at, { year: true }))}</span>`],
          [
            '<label for="scContract">Contrat rattaché</label>',
            `<select class="field code" id="scContract">${contractIds
              .map((id) => `<option value="${escapeHtml(id)}"${id === incident.contract_id ? " selected" : ""}>${escapeHtml(id)}</option>`)
              .join("")}</select>`,
          ],
          ["Constat", escapeHtml(incident.summary)],
        ])}
      </section>
      <section>
        ${sectionTitle(2, "Signaux observés")}
        ${
          signals.length
            ? `<div class="table-wrap"><table class="grid signals">
                <thead><tr><th scope="col" class="keep-col">Retenu</th><th scope="col">Signal</th><th scope="col">Observé</th><th scope="col">Attendu</th></tr></thead>
                <tbody>${signals
                  .map(
                    (signal, index) => `
                    <tr data-signal-row="${index}">
                      <td class="keep-col"><label class="check-target"><input type="checkbox" data-signal-keep="${index}" checked aria-label="Retenir le signal ${escapeHtml(signal.name)}" /></label></td>
                      <th scope="row">${escapeHtml(signal.name)}<span class="sub">${escapeHtml(label("kind", signal.kind))} · relevé le ${escapeHtml(formatDate(signal.observed_at))}</span></th>
                      <td class="observed"><input class="field" type="text" maxlength="200" data-signal-value="${index}" value="${escapeHtml(signal.value)}" aria-label="Valeur observée : ${escapeHtml(signal.name)}" /></td>
                      <td>${escapeHtml(signal.threshold)}</td>
                    </tr>`
                  )
                  .join("")}</tbody>
              </table></div>`
            : '<p class="quiet">Aucun signal rattaché à cet incident.</p>'
        }
        <fieldset class="terms">
          <legend>Symptômes de runbook repérés dans la fiche</legend>
          <div id="termList"><p class="quiet small">Calcul en cours…</p></div>
        </fieldset>
      </section>
      <div id="contractSections"></div>`;

    renderContractSections();
  }

  function renderContractSections() {
    const contract = state.contracts[state.scenario.contract_id] || state.original.contract;
    const changed = contract.id !== state.original.contract.id;
    const controls = contract.controls || [];
    const consumers = contract.consumers || [];
    $("contractSections").innerHTML = `
      <section>
        ${sectionTitle(3, `Contrat de données${changed ? ' <span class="changed-tag">choisi par vous</span>' : ""}`)}
        ${fieldList([
          ["Contrat", `<span class="code">${escapeHtml(contract.id)}</span>, version ${escapeHtml(contract.version)}`],
          ["Jeu de données", `<span class="code">${escapeHtml(contract.dataset)}</span>`],
          ["Domaine", escapeHtml(contract.domain)],
          ["Niveau", escapeHtml(label("tier", contract.tier))],
          ["Responsable", escapeHtml(contract.owner)],
          ["SLA", `<span class="nums">${escapeHtml(contract.sla_minutes)} min</span>`],
          ["Mis à jour le", contract.updated_at && `<span class="nums">${escapeHtml(formatDate(contract.updated_at, { year: true }))}</span>`],
        ])}
      </section>
      <section>
        ${sectionTitle(4, "Contrôles déclarés")}
        <ul class="plain-list">
          ${controls.map((control) => `<li>${escapeHtml(control)}</li>`).join("") || "<li>Aucun contrôle déclaré.</li>"}
        </ul>
      </section>
      <section>
        ${sectionTitle(5, "Consommateurs connus")}
        ${
          consumers.length
            ? `<div class="table-wrap"><table class="grid">
                <thead><tr><th scope="col">Consommateur</th><th scope="col">Niveau</th><th scope="col">Dépendance</th></tr></thead>
                <tbody>${consumers
                  .map(
                    (consumer) =>
                      `<tr><th scope="row"><span class="code">${escapeHtml(consumer.id)}</span></th><td>${escapeHtml(label("tier", consumer.tier))}</td><td>${escapeHtml(consumer.reason)}</td></tr>`
                  )
                  .join("")}</tbody>
              </table></div>`
            : '<p class="quiet">Aucun consommateur déclaré.</p>'
        }
      </section>`;
  }

  /* Scénario : la fiche modifiée par le visiteur, recalculée par le moteur */

  function referenceScenario() {
    const incident = state.original.incident;
    return {
      severity: incident.severity,
      contract_id: incident.contract_id,
      signals: (incident.signals || []).map((signal) => ({ value: signal.value, included: true })),
      excluded: new Set(),
    };
  }

  function isModified() {
    const reference = referenceScenario();
    const scenario = state.scenario;
    return (
      scenario.severity !== reference.severity ||
      scenario.contract_id !== reference.contract_id ||
      scenario.excluded.size > 0 ||
      scenario.signals.some((signal, index) => signal.included !== true || signal.value !== reference.signals[index].value)
    );
  }

  function syncScenarioControls() {
    const scenario = state.scenario;
    $("scSeverity").value = scenario.severity;
    $("scContract").value = scenario.contract_id;
    scenario.signals.forEach((signal, index) => {
      const keep = document.querySelector(`[data-signal-keep="${index}"]`);
      const value = document.querySelector(`[data-signal-value="${index}"]`);
      if (keep) keep.checked = signal.included;
      if (value) {
        value.value = signal.value;
        value.disabled = !signal.included;
      }
      document.querySelector(`[data-signal-row="${index}"]`)?.classList.toggle("is-dropped", !signal.included);
    });
  }

  function updateScenarioState() {
    const modified = isModified();
    elements.scenarioBanner.hidden = !modified;
    elements.resetScenario.hidden = !modified;
    elements.triageScope.hidden = !modified;
    elements.scenarioState.textContent = modified
      ? "Scénario modifié par vous, comparé au cas de référence (réf.)."
      : "Cas de référence : la fiche telle qu'enregistrée.";
    elements.scenarioState.classList.toggle("is-modified", modified);
  }

  function scheduleSimulation(delay = 0) {
    clearTimeout(state.simTimer);
    updateScenarioState();
    state.simTimer = window.setTimeout(runSimulation, delay);
  }

  async function runSimulation() {
    const incident = state.original?.incident;
    if (!incident) return;
    const scenario = state.scenario;
    const sequence = ++state.simSequence;
    const payload = {
      severity: scenario.severity,
      contract_id: scenario.contract_id,
      signals: scenario.signals.map((signal, index) => ({ index, value: signal.value, included: signal.included })),
      excluded_terms: [...scenario.excluded],
    };
    try {
      const { simulation } = await api(`/api/incidents/${encodeURIComponent(incident.id)}/simulate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (sequence !== state.simSequence || incident !== state.original?.incident) return;
      if (!state.referenceSim && !isModified()) state.referenceSim = simulation;
      renderTerms(simulation);
      renderSimulation(simulation);
    } catch (error) {
      if (sequence !== state.simSequence) return;
      $("scoreVerdict")?.remove();
      const message = document.createElement("p");
      message.className = "is-error";
      message.id = "scoreVerdict";
      message.textContent = `Le score n'a pas pu être recalculé : ${error.message}`;
      elements.scoreResult.replaceChildren(message);
    }
  }

  function renderTerms(simulation) {
    const list = $("termList");
    if (!list) return;
    const focused = document.activeElement?.dataset?.term;
    const terms = simulation.detected_terms || [];
    if (!terms.length) {
      list.innerHTML = '<p class="quiet small">Aucun symptôme de runbook dans le texte de la fiche.</p>';
      return;
    }
    list.innerHTML = terms
      .map(
        (term) => `<label class="term"><input type="checkbox" data-term="${escapeHtml(term)}"${state.scenario.excluded.has(term) ? "" : " checked"} /><span class="code">${escapeHtml(term)}</span></label>`
      )
      .join("");
    if (focused) list.querySelector(`[data-term="${CSS.escape(focused)}"]`)?.focus();
  }

  function abstentionReason(top, threshold) {
    if (!top.contract_match) return "le meilleur candidat porte sur un autre contrat";
    if (!(top.matched_terms || []).length) return "aucun symptôme commun avec le runbook";
    return `score sous le seuil de ${threshold}`;
  }

  function renderSimulation(simulation) {
    const top = (simulation.candidates || [])[0];
    if (!top) {
      elements.scoreResult.innerHTML = '<p class="quiet">Aucun runbook actif à classer.</p>';
      return;
    }
    const reference = state.referenceSim;
    const refTop = reference?.candidates?.[0];
    const parts = top.components || {};
    const refParts = refTop?.components || {};
    const sameRunbook = refTop && refTop.runbook_id === top.runbook_id;
    const threshold = formatScore(simulation.minimum_routing_score);
    const terms = top.matched_terms || [];

    const value = (current, previous) => {
      const changed = reference && previous !== undefined && Number(current) !== Number(previous);
      return `<td class="val${changed ? " is-changed" : ""}">${formatScore(current)}${
        changed ? `<span class="ref">réf. ${formatScore(previous)}</span>` : ""
      }</td>`;
    };
    const verdict = simulation.selected_runbook
      ? `${formatScore(simulation.match_score)} atteint le seuil de ${threshold} avec ${plural(terms.length, "symptôme commun", "symptômes communs")} : ${simulation.selected_runbook} retenu.`
      : `Sillage s'abstient (INSUFFICIENT_EVIDENCE) : ${abstentionReason(top, threshold)}.`;
    const gate = `<span class="${simulation.gate_state === "blocked" ? "is-critical strong" : ""}">${escapeHtml(label("gate", simulation.gate_state))}</span>`;
    const evaluationNote =
      isModified() && state.evaluation
        ? `<p class="small quiet">Les ${state.evaluation.passed} cas de référence validés portent sur les fiches d'origine ; ils ne valident pas ce scénario.</p>`
        : "";

    elements.scoreResult.innerHTML = `
      <div class="calc-block">
        <p class="calc-caption" id="calcCaption">Meilleur candidat : <span class="code${sameRunbook || !reference ? "" : " is-changed"}">${escapeHtml(top.runbook_id)}</span></p>
        <table class="calc" aria-labelledby="calcCaption">
          <tbody>
            <tr><th scope="row">${top.contract_match ? "Même contrat" : "Autre contrat"}</th><td class="op"></td>${value(parts.contract_affinity, sameRunbook ? refParts.contract_affinity : undefined)}</tr>
            <tr><th scope="row">Symptômes retrouvés<span class="sub">${escapeHtml(terms.join(", ") || "aucun")}</span></th><td class="op">+</td>${value(parts.symptom_overlap, sameRunbook ? refParts.symptom_overlap : undefined)}</tr>
            <tr><th scope="row">Sévérité ${escapeHtml(simulation.severity)}</th><td class="op">+</td>${value(parts.severity_context, sameRunbook ? refParts.severity_context : undefined)}</tr>
            <tr class="total"><th scope="row">Score</th><td class="op">=</td>${value(simulation.match_score, reference?.match_score)}</tr>
            <tr class="threshold"><th scope="row">Seuil de retenue</th><td class="op"></td><td class="val">${threshold}</td></tr>
          </tbody>
        </table>
        <p class="small${simulation.selected_runbook ? "" : " strong"}" id="scoreVerdict" aria-live="polite">${escapeHtml(verdict)}</p>
      </div>
      ${fieldList([
        ["Proposition", `${escapeHtml(simulation.decision)}<span class="sub code">${escapeHtml(simulation.decision_code)}</span>`],
        ["Publication", gate],
      ])}
      ${evaluationNote}
      <details class="justification">
        <summary>Classement des ${plural((simulation.candidates || []).length, "runbook", "runbooks")}</summary>
        <div class="table-wrap"><table class="grid">
          <thead><tr><th scope="col">Runbook</th><th scope="col">Contrat</th><th scope="col">Symptômes</th><th scope="col" class="num-col">Score</th></tr></thead>
          <tbody>${(simulation.candidates || [])
            .map(
              (item) =>
                `<tr><th scope="row"><span class="code">${escapeHtml(item.runbook_id)}</span></th><td>${item.contract_match ? "même" : "autre"}</td><td>${escapeHtml((item.matched_terms || []).join(", ") || "aucun")}</td><td class="num-col">${formatScore(item.score)}</td></tr>`
            )
            .join("")}</tbody>
        </table></div>
      </details>`;
  }

  function resetScenario() {
    if (!state.original) return;
    state.scenario = referenceScenario();
    syncScenarioControls();
    renderContractSections();
    scheduleSimulation(0);
    $("scSeverity")?.focus();
  }

  function onScenarioInput(event) {
    const target = event.target;
    const scenario = state.scenario;
    if (!scenario) return;
    if (target.id === "scSeverity") {
      scenario.severity = target.value;
      scheduleSimulation(0);
    } else if (target.id === "scContract") {
      scenario.contract_id = target.value;
      renderContractSections();
      scheduleSimulation(0);
    } else if (target.dataset.signalKeep !== undefined) {
      const index = Number(target.dataset.signalKeep);
      scenario.signals[index].included = target.checked;
      syncScenarioControls();
      scheduleSimulation(0);
    } else if (target.dataset.signalValue !== undefined) {
      scenario.signals[Number(target.dataset.signalValue)].value = target.value.slice(0, 200);
      scheduleSimulation(250);
    } else if (target.dataset.term !== undefined) {
      if (target.checked) scenario.excluded.delete(target.dataset.term);
      else scenario.excluded.add(target.dataset.term);
      scheduleSimulation(0);
    }
  }

  /* Triage */

  function renderTriage(report, narrative) {
    const checks = report.quality_gate?.checks || [];
    const provenance = report.provenance || {};
    const candidates = report.ranking?.candidates || [];

    elements.triageIntro.hidden = true;
    elements.triageResult.hidden = false;
    setTriageState(`produit le ${formatDate(report.generated_at, { seconds: true })}`);

    const gate = `<span class="${report.gate_state === "blocked" ? "is-critical strong" : ""}">${escapeHtml(label("gate", report.gate_state))}</span>`;
    const runbook = provenance.runbook_id
      ? `<span class="code">${escapeHtml(provenance.runbook_id)}</span>, version ${escapeHtml(provenance.runbook_version)}`
      : "aucun runbook retenu";

    elements.triageResult.innerHTML = `
      ${fieldList([
        ["Proposition", `${escapeHtml(report.decision)}<span class="sub code">${escapeHtml(report.decision_code)}</span>`],
        ["Publication", gate],
        ["Runbook", runbook],
        ["Score", `<span class="nums">${formatScore(report.match_score)}</span> pour un seuil de ${formatScore(report.ranking?.minimum_routing_score)}`],
      ])}
      <h4>Hypothèse de travail</h4>
      <p>${escapeHtml(report.hypothesis)}</p>
      <h4>Premières actions proposées</h4>
      <ol class="steps">
        ${(report.first_actions || []).map((action) => `<li>${escapeHtml(action)}</li>`).join("")}
      </ol>
      ${report.escalation ? `<p class="small">${escapeHtml(report.escalation)}</p>` : ""}
      <details class="justification">
        <summary>Justification : contrôles, éléments cités, classement, provenance</summary>
        <h4>Contrôles du triage</h4>
        <div class="table-wrap"><table class="grid">
          <thead><tr><th scope="col">Contrôle</th><th scope="col">État</th></tr></thead>
          <tbody>${checks
            .map(
              (check) =>
                `<tr><th scope="row">${escapeHtml(check.label)}<span class="sub">${escapeHtml(check.detail)}</span></th><td class="${check.status === "pass" ? "" : "strong"}">${escapeHtml(label("check", check.status))}</td></tr>`
            )
            .join("")}</tbody>
        </table></div>
        <h4>Consommateurs touchés</h4>
        <ul class="plain-list">
          ${
            (report.impact || [])
              .map((impact) => `<li><span class="code">${escapeHtml(impact.consumer)}</span> (${escapeHtml(label("tier", impact.tier))}) : ${escapeHtml(impact.reason)}</li>`)
              .join("") || "<li>Aucun consommateur déclaré dans le contrat.</li>"
          }
        </ul>
        <h4>Éléments cités</h4>
        <ul class="plain-list">
          ${(report.evidence || [])
            .map(
              (item) =>
                `<li><span class="strong">${escapeHtml(item.title)}</span> : ${escapeHtml(item.excerpt)}<span class="sub">${escapeHtml(label("sourceType", item.source_type))} · <span class="code">${escapeHtml(item.source_snapshot_id)}</span></span></li>`
            )
            .join("")}
        </ul>
        <h4>Classement des runbooks</h4>
        <div class="table-wrap"><table class="grid">
          <thead><tr><th scope="col">Runbook</th><th scope="col">Contrat</th><th scope="col" class="num-col">Score</th></tr></thead>
          <tbody>${candidates
            .map(
              (item) =>
                `<tr><th scope="row"><span class="code">${escapeHtml(item.runbook_id)}</span></th><td>${item.contract_match ? "même contrat" : "autre contrat"}</td><td class="num-col">${formatScore(item.score)}</td></tr>`
            )
            .join("")}</tbody>
        </table></div>
        <h4>Provenance</h4>
        ${fieldList([
          ["Trace", provenance.trace_id && `<span class="code">${escapeHtml(provenance.trace_id)}</span>`],
          ["Contrat", provenance.contract_id && `<span class="code">${escapeHtml(provenance.contract_id)} ${escapeHtml(provenance.contract_version)}</span>`],
          ["Lot de preuves", provenance.source_snapshot_id && `<span class="code">${escapeHtml(provenance.source_snapshot_id)}</span>`],
          ["Empreinte", provenance.evidence_hash && `<span class="code hash">${escapeHtml(provenance.evidence_hash)}</span>`],
        ])}
        ${
          narrative?.text
            ? `<h4>Synthèse produite par règles</h4>
               <p>${escapeHtml(narrative.text)}</p>
               <p class="small quiet"><span class="code">${escapeHtml(narrative.provider)}</span> · ${plural((narrative.citations || []).length, "élément cité", "éléments cités")}</p>`
            : ""
        }
      </details>
      <p class="small quiet">${escapeHtml(report.safety_note)}</p>`;

    choiceButtons().forEach((button) => {
      button.disabled = false;
      button.classList.remove("is-chosen");
    });
    elements.decisionHint.textContent = "Votre décision est consignée au journal ; elle ne déclenche aucune action.";
  }

  function resetDecision() {
    elements.reviewNote.value = "";
    elements.reviewFeedback.textContent = "";
    elements.reviewFeedback.className = "review-feedback small";
    elements.decisionTime.textContent = "pas encore décidé";
    elements.decisionReceipt.textContent = "—";
    elements.decisionHint.textContent =
      "Produisez le triage avant de décider. Votre décision est consignée au journal ; elle ne déclenche aucune action.";
    choiceButtons().forEach((button) => {
      button.disabled = true;
      button.classList.remove("is-chosen");
    });
  }

  function showRecordedDecision(outcome, recordedAt, receiptId, note) {
    elements.decisionTime.textContent = `${label("outcome", outcome)}, le ${formatDate(recordedAt, { seconds: true, year: true })}`;
    elements.decisionReceipt.textContent = `n° ${receiptId}${note ? ` · « ${note} »` : ""}`;
  }

  async function loadLastDecision(id) {
    try {
      const { items } = await api(`/api/incidents/${encodeURIComponent(id)}/reviews?limit=1`);
      const last = (items || [])[0];
      if (last && state.selectedId === id) {
        showRecordedDecision(last.payload?.outcome, last.occurred_at, last.id, last.payload?.note);
        elements.decisionHint.textContent =
          "Une décision a déjà été enregistrée pour cet incident. Produisez un nouveau triage pour en consigner une autre.";
      }
    } catch (_) {
      /* La fiche reste utilisable sans l'historique des décisions. */
    }
  }

  /* Journal */

  function describeAuditEvent(event) {
    const payload = event.payload || {};
    if (event.event_type === "triage_generated") {
      return `${payload.decision_code || ""}${payload.runbook?.id ? ` · ${payload.runbook.id}` : " · aucun runbook retenu"}`;
    }
    if (event.event_type === "operator_review_recorded") {
      return `${label("outcome", payload.outcome)}${payload.note ? ` · « ${payload.note} »` : ""}`;
    }
    if (event.event_type === "public_source_synced") return label("indicator", payload.indicator);
    return "";
  }

  function renderAudit(payload) {
    const events = payload.items || [];
    if (!events.length) {
      elements.auditList.innerHTML =
        '<p class="quiet">Journal vide. Le prochain triage, la prochaine décision ou synchronisation y laissera un reçu.</p>';
      return;
    }
    elements.auditList.innerHTML = `<div class="table-wrap"><table class="grid journal-table">
      <thead><tr><th scope="col" class="num-col">Reçu</th><th scope="col">Heure</th><th scope="col">Événement</th><th scope="col">Incident</th><th scope="col">Détail</th></tr></thead>
      <tbody>${events
        .map(
          (event) => `
          <tr>
            <td class="num-col">${escapeHtml(event.id)}</td>
            <td class="nowrap nums">${escapeHtml(formatDate(event.occurred_at, { seconds: true }))}</td>
            <td>${escapeHtml(label("event", event.event_type))}</td>
            <td class="code nowrap">${escapeHtml(event.incident_id || "—")}</td>
            <td>${escapeHtml(describeAuditEvent(event))}</td>
          </tr>`
        )
        .join("")}</tbody>
    </table></div>`;
  }

  async function loadAudit() {
    try {
      renderAudit(await api("/api/audit"));
    } catch (error) {
      elements.auditList.innerHTML = `<p class="is-error">Journal indisponible : ${escapeHtml(error.message)}</p>`;
    }
  }

  /* Actions */

  async function selectIncident(id) {
    state.selectedId = id;
    state.lastReport = null;
    renderQueue();
    elements.triageIntro.hidden = false;
    elements.triageResult.hidden = true;
    elements.triageResult.innerHTML = "";
    setTriageState("non produit");
    resetDecision();
    elements.analyze.textContent = "Produire le triage";
    elements.analyze.classList.remove("is-secondary");

    state.original = null;
    elements.scenarioBanner.hidden = true;
    elements.resetScenario.hidden = true;
    elements.triageScope.hidden = true;
    elements.caseFacts.innerHTML = '<p class="quiet">Chargement de la fiche…</p>';
    try {
      renderCase(await api(`/api/incidents/${encodeURIComponent(id)}`));
      updateScenarioState();
      elements.scoreResult.innerHTML = '<p class="quiet">Calcul en cours…</p>';
      runSimulation();
      loadLastDecision(id);
    } catch (error) {
      elements.caseActions.hidden = true;
      elements.decision.hidden = true;
      elements.caseContent.innerHTML = '<h2 id="case-title">La fiche n\'a pas pu être ouverte</h2>';
      elements.caseFacts.innerHTML = `<p class="is-error">${escapeHtml(error.message)}</p>`;
      showToast("Le détail de l'incident n'a pas pu être chargé.", true);
    }
  }

  async function analyzeSelectedIncident() {
    const incident = selectedIncident();
    if (!incident) return;

    elements.analyze.disabled = true;
    elements.analyze.textContent = "Triage en cours…";
    setTriageState("en cours");

    try {
      const response = await api(`/api/incidents/${encodeURIComponent(incident.id)}/analyze`, { method: "POST" });
      state.lastReport = response.report;
      renderTriage(response.report, response.narrative);
      $("triageSection").focus();
      elements.analyze.textContent = "Produire à nouveau";
      elements.analyze.classList.add("is-secondary");
      await loadAudit();
      showToast("Triage prêt. Relisez le calcul et les éléments cités avant de décider.");
    } catch (error) {
      setTriageState("échec");
      elements.analyze.textContent = "Produire le triage";
      showToast(`Le triage n'a pas pu être produit : ${error.message}`, true);
    } finally {
      elements.analyze.disabled = false;
    }
  }

  async function submitReview(outcome, trigger) {
    const incident = selectedIncident();
    if (!incident || !state.lastReport) return;

    const note = elements.reviewNote.value.trim();
    const feedback = elements.reviewFeedback;
    const buttons = choiceButtons();
    buttons.forEach((button) => (button.disabled = true));
    feedback.className = "review-feedback small";
    feedback.textContent = "Enregistrement de la décision…";

    try {
      const payload = { outcome };
      if (note) payload.note = note;
      const traceId = state.lastReport?.provenance?.trace_id;
      if (traceId) payload.trace_id = traceId;
      const { review } = await api(`/api/incidents/${encodeURIComponent(incident.id)}/reviews`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      buttons.forEach((button) => {
        button.classList.toggle("is-chosen", button === trigger);
        button.setAttribute("aria-pressed", String(button === trigger));
      });
      showRecordedDecision(review.outcome, review.recorded_at, review.review_id, review.note);
      feedback.textContent = "Décision consignée au journal. Aucune action n'a été déclenchée.";
      await loadAudit();
    } catch (error) {
      feedback.classList.add("is-error");
      feedback.textContent = `La décision n'a pas pu être enregistrée : ${error.message}`;
    } finally {
      buttons.forEach((button) => (button.disabled = false));
    }
  }

  async function syncPublicSource() {
    elements.syncSource.disabled = true;
    elements.syncSource.textContent = "Synchronisation…";
    try {
      const { snapshot } = await api("/api/sources/github-status/sync", { method: "POST" });
      const status = label("indicator", snapshot.indicator);
      elements.sourceCount.textContent = `Statut GitHub : ${status}`;
      elements.sourceCardText.textContent = snapshot.ok
        ? `GitHub Status lu le ${formatDate(snapshot.retrieved_at, { seconds: true })} : « ${snapshot.description} ». Signal informatif, sans effet sur le triage.`
        : `${snapshot.description}`;
      elements.sourceDetails.hidden = false;
      elements.sourceReceipt.textContent = JSON.stringify(snapshot, null, 2);
      await loadAudit();
    } catch (error) {
      elements.sourceCount.textContent = "Statut GitHub : indisponible";
      elements.sourceCardText.textContent = "La source publique n'a pas répondu. Le triage local reste utilisable.";
      showToast(`Source publique indisponible : ${error.message}`, true);
    } finally {
      elements.syncSource.disabled = false;
      elements.syncSource.textContent = "Synchroniser le statut GitHub";
    }
  }

  async function loadHealth() {
    try {
      const health = await api("/api/health");
      state.started = true;
      elements.healthLabel.textContent = `Service : disponible, v${health.version}`;
    } catch (_) {
      state.started = true;
      elements.healthLabel.textContent = "Service : indisponible";
      elements.healthLabel.classList.add("is-error");
    }
  }

  async function loadEvaluation() {
    try {
      const { passed, total } = await api("/api/evaluation");
      state.evaluation = { passed, total };
      elements.evaluationCount.textContent = `Cas de référence : ${passed} sur ${total} validés (fiches d'origine)`;
    } catch (_) {
      elements.evaluationCount.textContent = "Cas de référence : non vérifiés";
    }
  }

  async function loadIncidents() {
    try {
      const [payload, contractList] = await Promise.all([api("/api/incidents"), api("/api/contracts")]);
      for (const contract of contractList.items || []) state.contracts[contract.id] = contract;
      state.incidents = sortIncidents(payload.items || []);
      renderQueue();
      if (state.incidents.length) await selectIncident(state.incidents[0].id);
    } catch (error) {
      elements.openCount.textContent = "file indisponible";
      elements.queueCount.textContent = "";
      elements.incidentList.innerHTML = `<p class="is-error">La file est indisponible : ${escapeHtml(error.message)}</p>`;
      elements.caseContent.innerHTML = '<h2 id="case-title">Aucune donnée chargée</h2>';
      elements.caseFacts.innerHTML = '<p class="quiet">Démarrez le service pour charger les incidents de démonstration.</p>';
    }
  }

  function bindEvents() {
    document.querySelectorAll(".filter").forEach((button) => {
      button.addEventListener("click", () => {
        state.filter = button.dataset.filter || "all";
        document.querySelectorAll(".filter").forEach((item) => {
          item.classList.toggle("is-active", item === button);
          item.setAttribute("aria-pressed", String(item === button));
        });
        renderQueue();
      });
    });

    elements.incidentList.addEventListener("click", (event) => {
      const trigger = event.target.closest("[data-incident-id]");
      if (trigger) selectIncident(trigger.dataset.incidentId);
    });

    elements.analyze.addEventListener("click", analyzeSelectedIncident);
    elements.caseFacts.addEventListener("input", onScenarioInput);
    elements.resetScenario.addEventListener("click", resetScenario);
    elements.resetScenarioBanner.addEventListener("click", resetScenario);
    elements.decision.addEventListener("click", (event) => {
      const trigger = event.target.closest("[data-review-outcome]");
      if (trigger && !trigger.disabled) submitReview(trigger.dataset.reviewOutcome, trigger);
    });
    elements.refreshAudit.addEventListener("click", loadAudit);
    elements.syncSource.addEventListener("click", syncPublicSource);
    elements.sourceDetails.addEventListener("click", () => elements.sourceDialog.showModal());
    elements.closeSourceDialog.addEventListener("click", () => elements.sourceDialog.close());
    elements.sourceDialog.addEventListener("click", (event) => {
      if (event.target === elements.sourceDialog) elements.sourceDialog.close();
    });

    document.querySelectorAll("[data-jump]").forEach((button) => {
      button.addEventListener("click", () => $(button.dataset.jump)?.scrollIntoView({ block: "start" }));
    });
  }

  bindEvents();
  // Sur l'offre gratuite de Render, le service s'endort : la première requête attend son réveil.
  window.setTimeout(() => {
    if (state.started) return;
    elements.healthLabel.textContent = "Service : démarrage en cours, environ 40 s (hébergement gratuit en veille)";
    elements.incidentList.innerHTML =
      '<p class="quiet">Le service démarre, environ 40 s. La file s\'affichera d\'elle-même.</p>';
  }, 2500);
  Promise.all([loadHealth(), loadEvaluation(), loadAudit(), loadIncidents()]);
})();
