(() => {
  "use strict";

  const state = {
    incidents: [],
    filter: "all",
    selectedId: null,
    lastReport: null,
    toastTimer: null,
  };

  const $ = (id) => document.getElementById(id);
  const elements = {
    analyze: $("analyzeIncident"),
    auditList: $("auditList"),
    caseActions: $("caseActions"),
    caseContent: $("caseContent"),
    caseReference: $("caseReference"),
    caseStatus: $("caseStatus"),
    closeSourceDialog: $("closeSourceDialog"),
    evaluationCount: $("evaluationCount"),
    healthLabel: $("healthLabel"),
    healthStatus: document.querySelector(".topbar-status"),
    incidentList: $("incidentList"),
    openCount: $("openCount"),
    queueCount: $("queueCount"),
    refreshAudit: $("refreshAudit"),
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

  const severityOrder = { "SEV-1": 1, "SEV-2": 2, "SEV-3": 3 };
  const closedStatuses = new Set(["resolved", "closed"]);

  const labels = {
    status: { investigating: "en investigation", triage: "en triage", open: "ouvert", resolved: "résolu", closed: "clos" },
    tier: { critical: "critique", high: "élevé", medium: "moyen", low: "faible" },
    kind: { quality: "qualité", lineage: "lignage", consumer: "consommateurs", contract: "contrat", freshness: "fraîcheur" },
    gate: { blocked: "publication bloquée", review_required: "revue requise" },
    sourceType: { data_contract: "contrat", runbook: "runbook", signal: "signal" },
    check: { pass: "OK", needs_review: "À revoir" },
    event: {
      triage_generated: "Triage produit",
      operator_review_recorded: "Revue enregistrée",
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

  function formatDate(value) {
    if (!value) return "heure non enregistrée";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return new Intl.DateTimeFormat("fr-FR", {
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "UTC",
    }).format(date) + " UTC";
  }

  const formatScore = (value) =>
    Number(value).toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const plural = (count, singular, pluralForm) => `${count} ${count > 1 ? pluralForm : singular}`;

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

  function setTriageState(text, modifier = "") {
    elements.triageState.textContent = text;
    elements.triageState.className = `triage-state${modifier ? ` ${modifier}` : ""}`;
  }

  const selectedIncident = () => state.incidents.find((incident) => incident.id === state.selectedId);

  function sortIncidents(incidents) {
    return [...incidents].sort((a, b) => {
      const severityDiff = (severityOrder[a.severity] || 9) - (severityOrder[b.severity] || 9);
      if (severityDiff) return severityDiff;
      return new Date(a.opened_at || 0) - new Date(b.opened_at || 0);
    });
  }

  function renderQueue() {
    const visible = state.incidents.filter((incident) => state.filter === "all" || incident.severity === state.filter);
    const open = state.incidents.filter((incident) => !closedStatuses.has(incident.status)).length;

    elements.openCount.textContent = plural(open, "incident ouvert", "incidents ouverts");
    elements.queueCount.textContent = visible.length;

    if (!visible.length) {
      elements.incidentList.innerHTML = '<p class="empty-list">Aucun incident de cette sévérité dans la file.</p>';
      return;
    }

    elements.incidentList.innerHTML = visible
      .map((incident) => {
        const selected = incident.id === state.selectedId;
        return `
          <button class="incident-card${selected ? " is-selected" : ""}" type="button" data-incident-id="${escapeHtml(incident.id)}" aria-pressed="${selected}">
            <span class="incident-meta">
              <span class="incident-id">${escapeHtml(incident.id)}</span>
              <span class="severity ${escapeHtml(String(incident.severity).toLowerCase())}">${escapeHtml(incident.severity)}</span>
            </span>
            <strong>${escapeHtml(incident.title)}</strong>
            <small>${escapeHtml(label("status", incident.status))} · ${escapeHtml(formatDate(incident.opened_at))}</small>
          </button>`;
      })
      .join("");
  }

  function renderCase({ incident, contract }) {
    elements.caseReference.textContent = incident.id;
    elements.caseStatus.textContent = label("status", incident.status);
    elements.caseActions.hidden = false;

    const signals = incident.signals || [];
    const controls = contract.controls || [];
    const consumers = contract.consumers || [];

    elements.caseContent.innerHTML = `
      <div class="case-heading">
        <p class="case-time">Ouvert le ${escapeHtml(formatDate(incident.opened_at))} · <span class="severity ${escapeHtml(incident.severity.toLowerCase())}">${escapeHtml(incident.severity)}</span></p>
        <h2 id="case-title">${escapeHtml(incident.title)}</h2>
        <p class="case-summary">${escapeHtml(incident.summary)}</p>
      </div>
      <div class="case-grid">
        <section class="content-block signals-block">
          <h3>Signaux observés</h3>
          ${
            signals.length
              ? `<table class="signal-table">
                  <thead><tr><th scope="col">Signal</th><th scope="col">Observé</th><th scope="col">Attendu</th></tr></thead>
                  <tbody>
                    ${signals
                      .map(
                        (signal) => `
                        <tr>
                          <th scope="row">${escapeHtml(signal.name)}<small>${escapeHtml(label("kind", signal.kind))}</small></th>
                          <td class="signal-value" data-label="Observé">${escapeHtml(signal.value)}</td>
                          <td data-label="Attendu">${escapeHtml(signal.threshold)}</td>
                        </tr>`
                      )
                      .join("")}
                  </tbody>
                </table>`
              : '<p class="empty-list">Aucun signal rattaché à cet incident.</p>'
          }
        </section>
        <section class="content-block">
          <h3>Contrat de données</h3>
          <div class="contract-card">
            <span class="contract-id">${escapeHtml(contract.id)} · v${escapeHtml(contract.version)}</span>
            <h4>${escapeHtml(contract.dataset)}</h4>
            <p>Domaine ${escapeHtml(contract.domain)} · niveau ${escapeHtml(label("tier", contract.tier))}</p>
            <dl class="contract-meta">
              <div><dt>Responsable</dt><dd>${escapeHtml(contract.owner)}</dd></div>
              <div><dt>SLA</dt><dd>${escapeHtml(contract.sla_minutes)} min</dd></div>
            </dl>
          </div>
        </section>
        <section class="content-block">
          <h3>Contrôles du contrat</h3>
          <ul class="control-list">
            ${controls.map((control) => `<li>${escapeHtml(control)}</li>`).join("") || "<li>Aucun contrôle déclaré.</li>"}
          </ul>
        </section>
        <section class="content-block">
          <h3>Consommateurs connus</h3>
          <ul class="consumer-list">
            ${
              consumers
                .map(
                  (consumer) =>
                    `<li><code>${escapeHtml(consumer.id)}</code> <span>· ${escapeHtml(label("tier", consumer.tier))}</span><br /><span>${escapeHtml(consumer.reason)}</span></li>`
                )
                .join("") || "<li>Aucun consommateur déclaré.</li>"
            }
          </ul>
        </section>
      </div>`;
  }

  function renderScore(report) {
    const ranking = report.ranking || {};
    const top = (ranking.candidates || [])[0];
    if (!top) return "";
    const parts = top.components || {};
    const threshold = formatScore(ranking.minimum_routing_score);
    const terms = (top.matched_terms || []).join(", ") || "aucun";
    const verdict = ranking.selected_runbook
      ? `au-dessus du seuil de ${threshold} : runbook retenu.`
      : `aucun runbook retenu (seuil ${threshold} et au moins un symptôme commun requis).`;
    return `
      <section class="triage-section">
        <h3>Score de correspondance</h3>
        <p class="score-line">
          contrat ${formatScore(parts.contract_affinity)} + symptômes ${formatScore(parts.symptom_overlap)}
          + sévérité ${formatScore(parts.severity_context)} = <b>${formatScore(report.match_score)}</b>
        </p>
        <p class="section-note">Meilleur candidat : <code>${escapeHtml(top.runbook_id)}</code>, symptômes retrouvés : ${escapeHtml(terms)} ; ${verdict}</p>
      </section>`;
  }

  function renderTriage(report, narrative) {
    const checks = report.quality_gate?.checks || [];
    const provenance = report.provenance || {};
    const candidates = report.ranking?.candidates || [];

    elements.triageIntro.hidden = true;
    elements.triageResult.hidden = false;
    setTriageState("Prêt", "is-ready");

    const provenanceRows = [
      ["Trace", provenance.trace_id],
      ["Contrat", provenance.contract_id && `${provenance.contract_id} ${provenance.contract_version}`],
      ["Runbook", provenance.runbook_id ? `${provenance.runbook_id} ${provenance.runbook_version}` : "aucun retenu"],
      ["Lot de preuves", provenance.source_snapshot_id],
      ["Empreinte", provenance.evidence_hash],
    ].filter(([, value]) => value);

    elements.triageResult.innerHTML = `
      <section class="triage-section">
        <h3>Décision proposée</h3>
        <p class="decision-text">${escapeHtml(report.decision)}</p>
        <dl class="decision-facts">
          <div><dt>Code</dt><dd><code>${escapeHtml(report.decision_code)}</code></dd></div>
          <div><dt>Contrôle</dt><dd class="gate gate-${escapeHtml(report.gate_state)}">${escapeHtml(label("gate", report.gate_state))}</dd></div>
        </dl>
      </section>
      ${renderScore(report)}
      <section class="triage-section">
        <h3>Hypothèse de travail</h3>
        <p>${escapeHtml(report.hypothesis)}</p>
      </section>
      <section class="triage-section">
        <h3>Premières actions</h3>
        <ol class="action-steps">
          ${(report.first_actions || []).map((action) => `<li>${escapeHtml(action)}</li>`).join("")}
        </ol>
        ${report.escalation ? `<p class="section-note">${escapeHtml(report.escalation)}</p>` : ""}
      </section>
      <section class="triage-section">
        <h3>Consommateurs touchés</h3>
        <ul class="impact-list">
          ${
            (report.impact || [])
              .map(
                (impact) =>
                  `<li><strong><code>${escapeHtml(impact.consumer)}</code> · ${escapeHtml(label("tier", impact.tier))}</strong><span>${escapeHtml(impact.reason)}</span></li>`
              )
              .join("") || "<li>Aucun consommateur déclaré dans le contrat.</li>"
          }
        </ul>
      </section>
      <section class="triage-section">
        <h3>Contrôles du triage</h3>
        <ul class="check-list">
          ${checks
            .map(
              (check) =>
                `<li><span class="check-status ${check.status === "pass" ? "is-pass" : "is-review"}">${escapeHtml(label("check", check.status))}</span><span>${escapeHtml(check.label)}<small>${escapeHtml(check.detail)}</small></span></li>`
            )
            .join("")}
        </ul>
      </section>
      <details class="triage-details">
        <summary>Éléments cités, classement et provenance</summary>
      <section class="triage-section">
        <h3>Éléments cités</h3>
        <ul class="evidence-list">
          ${(report.evidence || [])
            .map(
              (item) => `
                <li>
                  <strong>${escapeHtml(item.title)}</strong>
                  <p>${escapeHtml(item.excerpt)}</p>
                  <small>${escapeHtml(label("sourceType", item.source_type))} · ${escapeHtml(item.source_snapshot_id)}</small>
                </li>`
            )
            .join("")}
        </ul>
      </section>
      <section class="triage-section">
        <h3>Classement des runbooks</h3>
        <ol class="ranking-list">
          ${candidates
            .map(
              (item) =>
                `<li><span><code>${escapeHtml(item.runbook_id)}</code><small>${item.contract_match ? "même contrat" : "autre contrat"}</small></span><span class="score-line">${formatScore(item.score)}</span></li>`
            )
            .join("")}
        </ol>
      </section>
      <section class="triage-section">
        <h3>Provenance</h3>
        <ul class="provenance-list">
          ${provenanceRows.map(([name, value]) => `<li><span>${name}</span><code>${escapeHtml(value)}</code></li>`).join("")}
        </ul>
      </section>
      </details>
      ${
        narrative?.text
          ? `<section class="triage-section">
              <h3>Synthèse générée par règles</h3>
              <p>${escapeHtml(narrative.text)}</p>
              <span class="narrative-provider"><code>${escapeHtml(narrative.provider)}</code> · ${plural((narrative.citations || []).length, "élément cité", "éléments cités")}</span>
            </section>`
          : ""
      }
      <section class="review-box" aria-labelledby="reviewTitle">
        <h3 id="reviewTitle">Décision humaine</h3>
        <p>Enregistrez votre décision. Sillage n'applique jamais la remédiation proposée.</p>
        <label class="review-note-label" for="reviewNote">Note de revue (facultative)</label>
        <textarea id="reviewNote" class="review-note" rows="3" maxlength="420" placeholder="Ce que vous avez vérifié, contesté ou transmis"></textarea>
        <div class="review-actions">
          <button type="button" class="review-action" data-review-outcome="accepted">Accepter le triage</button>
          <button type="button" class="review-action" data-review-outcome="needs_evidence">Demander des éléments</button>
          <button type="button" class="review-action" data-review-outcome="rejected">Rejeter</button>
        </div>
        <p class="review-feedback" id="reviewFeedback" aria-live="polite"></p>
      </section>
      <p class="safety-note">${escapeHtml(report.safety_note)}</p>`;
  }

  function describeAuditEvent(event) {
    const payload = event.payload || {};
    const incident = event.incident_id ? `${event.incident_id} · ` : "";
    if (event.event_type === "triage_generated") {
      return `${incident}${payload.decision_code || ""}${payload.runbook?.id ? ` · ${payload.runbook.id}` : " · aucun runbook retenu"}`;
    }
    if (event.event_type === "operator_review_recorded") {
      return `${incident}${label("outcome", payload.outcome)}${payload.note ? ` · «\u00a0${payload.note}\u00a0»` : ""}`;
    }
    if (event.event_type === "public_source_synced") return label("indicator", payload.indicator);
    return incident.replace(/ · $/, "");
  }

  function renderAudit(payload) {
    const events = payload.items || [];
    if (!events.length) {
      elements.auditList.innerHTML =
        '<p class="loading-copy">Journal vide. Le prochain triage, la prochaine revue ou synchronisation y laissera un reçu.</p>';
      return;
    }
    elements.auditList.innerHTML = events
      .map(
        (event) => `
          <article class="audit-item">
            <span class="audit-time">${escapeHtml(formatDate(event.occurred_at))}</span>
            <span class="audit-event">${escapeHtml(label("event", event.event_type))}</span>
            <span class="audit-description">${escapeHtml(describeAuditEvent(event))}</span>
          </article>`
      )
      .join("");
  }

  async function loadAudit() {
    try {
      renderAudit(await api("/api/audit"));
    } catch (error) {
      elements.auditList.innerHTML = `<p class="loading-copy is-error-copy">Journal indisponible : ${escapeHtml(error.message)}</p>`;
    }
  }

  async function selectIncident(id) {
    state.selectedId = id;
    state.lastReport = null;
    renderQueue();
    elements.triageIntro.hidden = false;
    elements.triageResult.hidden = true;
    setTriageState("En attente");

    elements.caseContent.innerHTML = '<p class="loading-copy">Chargement du dossier…</p>';
    try {
      renderCase(await api(`/api/incidents/${encodeURIComponent(id)}`));
    } catch (error) {
      elements.caseActions.hidden = true;
      elements.caseContent.innerHTML = `<div class="empty-case is-error"><h2 id="case-title">Le dossier n'a pas pu être ouvert</h2><p>${escapeHtml(error.message)}</p></div>`;
      showToast("Le détail de l'incident n'a pas pu être chargé.", true);
    }
  }

  async function analyzeSelectedIncident() {
    const incident = selectedIncident();
    if (!incident) return;

    elements.analyze.disabled = true;
    elements.analyze.textContent = "Triage en cours…";
    setTriageState("En cours");

    try {
      const response = await api(`/api/incidents/${encodeURIComponent(incident.id)}/analyze`, { method: "POST" });
      state.lastReport = response.report;
      renderTriage(response.report, response.narrative);
      await loadAudit();
      showToast("Triage prêt. Relisez les éléments cités avant de décider.");
    } catch (error) {
      setTriageState("Échec", "is-failed");
      showToast(`Le triage n'a pas pu être produit : ${error.message}`, true);
    } finally {
      elements.analyze.disabled = false;
      elements.analyze.textContent = "Produire le triage";
    }
  }

  async function submitReview(outcome, trigger) {
    const incident = selectedIncident();
    if (!incident) return;

    const note = $("reviewNote")?.value.trim();
    const feedback = $("reviewFeedback");
    const buttons = [...elements.triageResult.querySelectorAll("[data-review-outcome]")];
    buttons.forEach((button) => (button.disabled = true));
    feedback.className = "review-feedback";
    feedback.textContent = "Enregistrement de la revue…";

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
      buttons.forEach((button) => button.classList.toggle("is-chosen", button === trigger));
      feedback.classList.add("is-recorded");
      feedback.textContent = `Revue enregistrée : ${label("outcome", review.outcome)}, le ${formatDate(review.recorded_at)}. Reçu n° ${review.review_id}.`;
      await loadAudit();
    } catch (error) {
      feedback.classList.add("is-error");
      feedback.textContent = `La revue n'a pas pu être enregistrée : ${error.message}`;
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
      elements.sourceCount.textContent = `statut GitHub : ${status}`;
      elements.sourceCardText.textContent = snapshot.ok
        ? `GitHub Status, lu le ${formatDate(snapshot.retrieved_at)} : ${status} («\u00a0${snapshot.description}\u00a0»). Signal informatif, sans effet sur le triage.`
        : `${snapshot.description}`;
      elements.sourceDetails.hidden = false;
      elements.sourceReceipt.textContent = JSON.stringify(snapshot, null, 2);
      await loadAudit();
    } catch (error) {
      elements.sourceCount.textContent = "statut GitHub indisponible";
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
      elements.healthLabel.textContent = `Service disponible · v${health.version}`;
      elements.healthStatus.classList.add("is-healthy");
    } catch (_) {
      elements.healthLabel.textContent = "Service indisponible";
      elements.healthStatus.classList.add("is-unavailable");
    }
  }

  async function loadEvaluation() {
    try {
      const { passed, total } = await api("/api/evaluation");
      elements.evaluationCount.textContent = `${passed}/${total} cas de référence validés`;
    } catch (_) {
      elements.evaluationCount.textContent = "cas de référence non vérifiés";
    }
  }

  async function loadIncidents() {
    try {
      const payload = await api("/api/incidents");
      state.incidents = sortIncidents(payload.items || []);
      renderQueue();
      if (state.incidents.length) await selectIncident(state.incidents[0].id);
    } catch (error) {
      elements.openCount.textContent = "file indisponible";
      elements.queueCount.textContent = "0";
      elements.incidentList.innerHTML = `<p class="empty-list is-error-copy">La file est indisponible : ${escapeHtml(error.message)}</p>`;
      elements.caseContent.innerHTML =
        '<div class="empty-case is-error"><h2 id="case-title">Aucune donnée chargée</h2><p>Démarrez le service pour charger les incidents de démonstration.</p></div>';
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
    elements.triageResult.addEventListener("click", (event) => {
      const trigger = event.target.closest("[data-review-outcome]");
      if (trigger) submitReview(trigger.dataset.reviewOutcome, trigger);
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
  Promise.all([loadHealth(), loadEvaluation(), loadAudit(), loadIncidents()]);
})();
