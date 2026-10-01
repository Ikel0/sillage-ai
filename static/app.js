(() => {
  "use strict";

  const state = {
    incidents: [],
    filter: "all",
    selectedId: null,
    lastReport: null,
    sourceSnapshot: null,
    toastTimer: null,
  };

  const elements = {
    activeCount: document.getElementById("activeCount"),
    auditList: document.getElementById("auditList"),
    analyze: document.getElementById("analyzeIncident"),
    caseActions: document.getElementById("caseActions"),
    caseContent: document.getElementById("caseContent"),
    caseReference: document.getElementById("caseReference"),
    caseStatus: document.getElementById("caseStatus"),
    closeSourceDialog: document.getElementById("closeSourceDialog"),
    evaluationNote: document.getElementById("evaluationNote"),
    evaluationScore: document.getElementById("evaluationScore"),
    healthLabel: document.getElementById("healthLabel"),
    healthStatus: document.querySelector(".topbar-status"),
    incidentList: document.getElementById("incidentList"),
    ledgerState: document.getElementById("ledgerState"),
    queueCount: document.getElementById("queueCount"),
    refreshAudit: document.getElementById("refreshAudit"),
    reasoningIntro: document.getElementById("reasoningIntro"),
    sourceCard: document.querySelector(".source-card"),
    sourceCardText: document.getElementById("sourceCardText"),
    sourceDetails: document.getElementById("sourceDetails"),
    sourceDialog: document.getElementById("sourceDialog"),
    sourceNote: document.getElementById("sourceNote"),
    sourceReceipt: document.getElementById("sourceReceipt"),
    sourceStatus: document.getElementById("sourceStatus"),
    syncSource: document.getElementById("syncSource"),
    toast: document.getElementById("toast"),
    triageResult: document.getElementById("triageResult"),
  };

  const severityOrder = { "SEV-1": 1, "SEV-2": 2, "SEV-3": 3 };

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function formatDate(value) {
    if (!value) return "time not recorded";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return new Intl.DateTimeFormat("en", {
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZone: "UTC",
      timeZoneName: "short",
    }).format(date);
  }

  function sentenceCase(value) {
    return String(value ?? "").replaceAll("_", " ");
  }

  function collectionFrom(payload, keys) {
    if (Array.isArray(payload)) return payload;
    for (const key of keys) {
      if (Array.isArray(payload?.[key])) return payload[key];
    }
    return [];
  }

  function listFrom(value) {
    if (Array.isArray(value)) return value;
    if (value === undefined || value === null || value === "") return [];
    return [value];
  }

  function textFrom(value, fallback = "Not recorded") {
    if (typeof value === "string" || typeof value === "number") return String(value);
    if (!value || typeof value !== "object") return fallback;
    return String(
      value.label ||
        value.title ||
        value.name ||
        value.dataset ||
        value.scope ||
        value.source_id ||
        value.runbook_id ||
        value.id ||
        value.value ||
        value.description ||
        fallback
    );
  }

  function codeLabel(value, fallback = "Not classified") {
    if (!value) return fallback;
    return String(value).replaceAll("_", " ").replaceAll("-", " ");
  }

  function qualityCheckLabel(check) {
    if (!check || typeof check !== "object") return textFrom(check);
    const state = check.status ? ` (${codeLabel(check.status)})` : "";
    const detail = check.detail ? `: ${check.detail}` : "";
    return `${check.label || check.id || "Check"}${state}${detail}`;
  }

  function stateClass(value) {
    return String(value || "unknown").toLowerCase().replaceAll(/[^a-z0-9]+/g, "-");
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      headers: { Accept: "application/json", ...(options.headers || {}) },
      ...options,
    });
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json")
      ? await response.json()
      : await response.text();

    if (!response.ok) {
      const detail = typeof payload === "object" ? payload.detail : payload;
      throw new Error(detail || `Request failed with ${response.status}`);
    }
    return payload;
  }

  function showToast(message, isError = false) {
    clearTimeout(state.toastTimer);
    elements.toast.textContent = message;
    elements.toast.classList.toggle("is-error", isError);
    elements.toast.classList.add("is-visible");
    state.toastTimer = window.setTimeout(() => {
      elements.toast.classList.remove("is-visible");
    }, 4300);
  }

  function selectedIncident() {
    return state.incidents.find((incident) => incident.id === state.selectedId);
  }

  function sortIncidents(incidents) {
    return [...incidents].sort((a, b) => {
      const severityDiff = (severityOrder[a.severity] || 9) - (severityOrder[b.severity] || 9);
      if (severityDiff) return severityDiff;
      return new Date(a.opened_at || 0) - new Date(b.opened_at || 0);
    });
  }

  function renderQueue() {
    const visible = sortIncidents(state.incidents).filter((incident) => {
      return state.filter === "all" || incident.severity === state.filter;
    });

    elements.activeCount.textContent = state.incidents.length.toString().padStart(2, "0");
    elements.queueCount.textContent = visible.length;

    if (!visible.length) {
      elements.incidentList.innerHTML = '<p class="empty-list">No incident matches this view.</p>';
      return;
    }

    elements.incidentList.innerHTML = visible
      .map((incident) => {
        const selected = incident.id === state.selectedId ? " is-selected" : "";
        const severity = String(incident.severity || "SEV-3").toLowerCase();
        return `
          <button class="incident-card${selected}" type="button" data-incident-id="${escapeHtml(incident.id)}" aria-pressed="${incident.id === state.selectedId}">
            <span class="incident-meta">
              <span class="incident-id">${escapeHtml(incident.id)}</span>
              <span class="severity ${severity}">${escapeHtml(incident.severity)}</span>
            </span>
            <strong>${escapeHtml(incident.title)}</strong>
            <small>${escapeHtml(sentenceCase(incident.status))} · ${escapeHtml(formatDate(incident.opened_at))}</small>
          </button>`;
      })
      .join("");
  }

  function renderCase(detail) {
    const incident = detail?.incident || detail || selectedIncident();
    const contract = detail?.contract || incident?.contract || {};

    if (!incident?.id) return;

    elements.caseReference.textContent = incident.id;
    elements.caseStatus.textContent = sentenceCase(incident.status || "open");
    elements.caseStatus.className = `case-status status-${String(incident.status || "open").toLowerCase()}`;
    elements.caseActions.hidden = false;

    const signals = Array.isArray(incident.signals) ? incident.signals : [];
    const controls = Array.isArray(contract.controls) ? contract.controls : [];
    const consumers = Array.isArray(contract.consumers) ? contract.consumers : [];

    elements.caseContent.innerHTML = `
      <div class="case-heading">
        <p class="case-time">Opened ${escapeHtml(formatDate(incident.opened_at))} · ${escapeHtml(incident.severity || "severity unknown")}</p>
        <h2 id="case-title">${escapeHtml(incident.title)}</h2>
        <p class="case-summary">${escapeHtml(incident.summary || "No incident summary is available.")}</p>
      </div>
      <div class="case-grid">
        <section class="content-block">
          <h3>Observed signals</h3>
          <ul class="signal-list">
            ${signals
              .map(
                (signal) => `
                  <li class="signal-row">
                    <span class="signal-kind kind-${escapeHtml(signal.kind || "quality")}" aria-hidden="true"></span>
                    <span>
                      <strong>${escapeHtml(signal.name)}</strong>
                      <small>Expected: ${escapeHtml(signal.threshold)}</small>
                    </span>
                    <span class="signal-value">${escapeHtml(signal.value)}</span>
                  </li>`
              )
              .join("") || '<li class="empty-list">No signals were attached to this incident.</li>'}
          </ul>
        </section>
        <section class="content-block">
          <h3>Contract anchor</h3>
          <div class="contract-card">
            <span class="contract-id">${escapeHtml(contract.id || incident.contract_id || "contract not loaded")}</span>
            <h4>${escapeHtml(contract.dataset || "Data contract")}</h4>
            <p>${escapeHtml(contract.domain || "domain not recorded")}</p>
            <div class="contract-meta">
              <div><span>Owner</span><strong>${escapeHtml(contract.owner || "not assigned")}</strong></div>
              <div><span>SLA</span><strong>${escapeHtml(contract.sla_minutes ? `${contract.sla_minutes} min` : "not set")}</strong></div>
            </div>
          </div>
        </section>
        <section class="content-block">
          <h3>Contract controls</h3>
          <ul class="control-list">
            ${controls.map((control) => `<li>${escapeHtml(control)}</li>`).join("") || '<li>No controls recorded.</li>'}
          </ul>
        </section>
        <section class="content-block">
          <h3>Known consumers</h3>
          <ul class="consumer-list">
            ${
              consumers
                .map((consumer) => {
                  if (consumer && typeof consumer === "object") {
                    return `<li title="${escapeHtml(consumer.reason || "")}">${escapeHtml(consumer.id || "consumer")} <span>${escapeHtml(consumer.tier || "")}</span></li>`;
                  }
                  return `<li>${escapeHtml(consumer)}</li>`;
                })
                .join("") || '<li>None recorded</li>'
            }
          </ul>
        </section>
      </div>`;
  }

  function renderTriage(report, narrative = null) {
    const evidence = Array.isArray(report.evidence) ? report.evidence : [];
    const firstActions = Array.isArray(report.first_actions) ? report.first_actions : [];
    const confidence = Math.round(Number(report.confidence || 0) * 100);
    const impacts = listFrom(report.impact);
    const qualityGate = report.quality_gate && typeof report.quality_gate === "object" ? report.quality_gate : {};
    const gateState = report.gate_state || qualityGate.state || qualityGate.status || "not recorded";
    const gateReason =
      qualityGate.reason ||
      qualityGate.description ||
      qualityGate.note ||
      (qualityGate.status
        ? qualityGate.all_passed
          ? "All evidence checks passed. An operator must still decide what happens next."
          : "One or more evidence checks need operator context before the plan can be trusted."
        : "No quality gate explanation was returned.");
    const qualityChecks = listFrom(qualityGate.checks || qualityGate.controls || qualityGate.evidence);
    const provenancePayload = report.provenance;
    const provenance = Array.isArray(provenancePayload)
      ? provenancePayload
      : listFrom(provenancePayload?.items || provenancePayload?.sources || provenancePayload?.citations).length
        ? listFrom(provenancePayload?.items || provenancePayload?.sources || provenancePayload?.citations)
        : [
            provenancePayload?.contract_id
              ? {
                  title: "Contract anchor",
                  detail: `${provenancePayload.contract_id} ${provenancePayload.contract_version || ""}`.trim(),
                }
              : null,
            provenancePayload?.runbook_id
              ? {
                  title: "Runbook anchor",
                  detail: `${provenancePayload.runbook_id} ${provenancePayload.runbook_version || ""}`.trim(),
                }
              : null,
            provenancePayload?.source_snapshot_id
              ? { title: "Evidence bundle", detail: provenancePayload.source_snapshot_id }
              : null,
            provenancePayload?.evidence_hash
              ? { title: "Evidence hash", detail: provenancePayload.evidence_hash }
              : null,
          ].filter(Boolean);
    const rankingPayload = report.ranking;
    const ranking = Array.isArray(rankingPayload)
      ? rankingPayload
      : listFrom(rankingPayload?.items || rankingPayload?.candidates || rankingPayload?.ranked);
    const traceLabel = provenancePayload?.trace_id ? `Trace ${provenancePayload.trace_id}` : "";
    const decisionCode = report.decision_code || "not classified";

    elements.reasoningIntro.hidden = true;
    elements.triageResult.hidden = false;
    elements.ledgerState.textContent = "Trace ready";
    elements.ledgerState.className = "ledger-state is-ready";
    elements.triageResult.innerHTML = `
      <section class="triage-summary">
        <span>Suggested decision</span>
        <strong>${escapeHtml(report.decision || "No decision was returned.")}</strong>
        <div class="confidence"><span>Evidence confidence</span><b>${confidence}%</b></div>
      </section>
      <section class="decision-frame">
        <div class="decision-frame-heading">
          <div>
            <h3>Decision checkpoint</h3>
            <p>This is a recommendation, not an operation.</p>
          </div>
          <span class="gate-badge gate-${escapeHtml(stateClass(gateState))}">${escapeHtml(codeLabel(gateState))}</span>
        </div>
        <dl class="decision-facts">
          <div><dt>Decision code</dt><dd>${escapeHtml(codeLabel(decisionCode))}</dd></div>
          <div><dt>Gate state</dt><dd>${escapeHtml(codeLabel(gateState))}</dd></div>
        </dl>
        <div class="impact-block">
          <span>Expected impact</span>
          <ul class="impact-list">
            ${
              impacts
                .map((impact) => {
                  if (impact && typeof impact === "object") {
                    return `<li><strong>${escapeHtml(impact.consumer || "consumer")} · ${escapeHtml(impact.tier || "tier not recorded")}</strong><span>${escapeHtml(impact.reason || impact.recommended_action || "Impact details were not returned.")}</span></li>`;
                  }
                  return `<li>${escapeHtml(textFrom(impact))}</li>`;
                })
                .join("") || "<li>No impact scope was returned.</li>"
            }
          </ul>
        </div>
        <div class="quality-gate">
          <span class="quality-gate-mark" aria-hidden="true">✓</span>
          <div>
            <strong>Quality gate</strong>
            <p>${escapeHtml(gateReason)}</p>
            ${qualityChecks.length ? `<ul>${qualityChecks.map((check) => `<li>${escapeHtml(qualityCheckLabel(check))}</li>`).join("")}</ul>` : ""}
          </div>
        </div>
      </section>
      <section class="triage-section">
        <h3>Working hypothesis</h3>
        <p>${escapeHtml(report.hypothesis || "No hypothesis was returned.")}</p>
      </section>
      <section class="triage-section">
        <h3>First actions</h3>
        <ol class="action-steps">
          ${firstActions
            .map((action, index) => `<li><b>0${index + 1}</b><span>${escapeHtml(action)}</span></li>`)
            .join("") || "<li><span>No actions were returned.</span></li>"}
        </ol>
      </section>
      <section class="triage-section">
        <h3>Evidence ledger</h3>
        <ul class="evidence-list">
          ${evidence
            .map(
              (item) => `
                <li>
                  <strong>${escapeHtml(item.title || item.source_id || "Evidence")}</strong>
                  <p>${escapeHtml(item.excerpt || "No excerpt available.")}</p>
                  <span>${escapeHtml(sentenceCase(item.source_type || "source"))} · ${Math.round(Number(item.confidence || 0) * 100)}% confidence</span>
                </li>`
            )
            .join("") || "<li><strong>No evidence was returned.</strong></li>"}
        </ul>
      </section>
      ${
        provenance.length || ranking.length
          ? `<section class="triage-section reasoning-details">
              <h3>Decision provenance</h3>
              ${traceLabel ? `<p class="trace-id">${escapeHtml(traceLabel)}</p>` : ""}
              ${
                provenance.length
                  ? `<ul class="provenance-list">
                      ${provenance
                        .map((item) => {
                          const detail = item && typeof item === "object" ? item.detail || item.excerpt || item.source_type || item.reason : "";
                          return `<li><strong>${escapeHtml(textFrom(item))}</strong>${detail ? `<span>${escapeHtml(detail)}</span>` : ""}</li>`;
                        })
                        .join("")}
                    </ul>`
                  : ""
              }
              ${
                ranking.length
                  ? `<div class="ranking-block"><span>Candidate ranking</span><ol>
                      ${ranking
                        .map((item, index) => {
                          const label = textFrom(item, `candidate ${index + 1}`);
                          const score = item && typeof item === "object" && item.score !== undefined ? ` ${Math.round(Number(item.score) * 100)}%` : "";
                          return `<li><b>0${index + 1}</b><span>${escapeHtml(label)}</span><em>${escapeHtml(score)}</em></li>`;
                        })
                        .join("")}
                    </ol></div>`
                  : ""
              }
            </section>`
          : ""
      }
      ${
        narrative?.text
          ? `<section class="triage-section narrative-section">
              <h3>Narrative trace</h3>
              <p>${escapeHtml(narrative.text)}</p>
              <span class="narrative-provider">${escapeHtml(narrative.provider || "local provider")} · ${escapeHtml((narrative.citations || []).length)} cited records</span>
            </section>`
          : ""
      }
      <section class="review-box" aria-labelledby="reviewTitle">
        <div class="review-heading">
          <div>
            <h3 id="reviewTitle">Human review required</h3>
            <p>Record the operator decision. Sillage never applies the proposed remediation.</p>
          </div>
          <span>Manual gate</span>
        </div>
        <label class="review-note-label" for="reviewNote">Optional review note</label>
        <textarea id="reviewNote" class="review-note" rows="3" maxlength="420" placeholder="What did you verify, challenge or hand off?"></textarea>
        <div class="review-actions">
          <button type="button" class="review-action review-accept" data-review-outcome="accepted">Accept triage</button>
          <button type="button" class="review-action review-evidence" data-review-outcome="needs_evidence">Need more evidence</button>
          <button type="button" class="review-action review-reject" data-review-outcome="rejected">Reject proposal</button>
        </div>
        <p class="review-feedback" id="reviewFeedback" aria-live="polite"></p>
      </section>
      <p class="safety-note">${escapeHtml(report.safety_note || "This suggestion is advisory. A responsible team member must approve and execute any action.")}</p>`;
  }

  function describeAuditEvent(event) {
    const type = sentenceCase(event.event_type || "event");
    const id = event.incident_id ? ` for ${event.incident_id}` : "";
    const payload = event.payload || {};
    if (payload.message) return payload.message;
    if (payload.status) return `${type}${id}: ${payload.status}`;
    if (payload.outcome) return `${type}${id}: ${codeLabel(payload.outcome)}`;
    return `${type}${id}`;
  }

  function renderAudit(payload) {
    const events = collectionFrom(payload, ["events", "audit", "items"]);
    if (!events.length) {
      elements.auditList.innerHTML = '<p class="loading-copy">No decisions have been generated yet. The next triage or source sync will leave a receipt here.</p>';
      return;
    }
    elements.auditList.innerHTML = events
      .map(
        (event) => `
          <article class="audit-item">
            <span class="audit-time">${escapeHtml(formatDate(event.occurred_at))}</span>
            <span class="audit-event">${escapeHtml(sentenceCase(event.event_type || "event"))}</span>
            <span class="audit-description">${escapeHtml(describeAuditEvent(event))}</span>
          </article>`
      )
      .join("");
  }

  async function loadAudit() {
    try {
      const payload = await api("/api/audit");
      renderAudit(payload);
    } catch (error) {
      elements.auditList.innerHTML = `<p class="loading-copy">Audit trail unavailable: ${escapeHtml(error.message)}</p>`;
    }
  }

  async function selectIncident(id, preserveTriage = false) {
    state.selectedId = id;
    renderQueue();
    if (!preserveTriage) {
      state.lastReport = null;
      elements.reasoningIntro.hidden = false;
      elements.triageResult.hidden = true;
      elements.ledgerState.textContent = "Ready";
      elements.ledgerState.className = "ledger-state";
    }

    elements.caseContent.innerHTML = '<p class="loading-copy">Loading case file...</p>';
    try {
      const detail = await api(`/api/incidents/${encodeURIComponent(id)}`);
      renderCase(detail);
    } catch (error) {
      elements.caseActions.hidden = true;
      elements.caseContent.innerHTML = `<div class="empty-case"><span class="empty-symbol" aria-hidden="true">!</span><h2 id="case-title">The case file could not be opened.</h2><p>${escapeHtml(error.message)}</p></div>`;
      showToast("The incident detail could not be loaded.", true);
    }
  }

  async function analyzeSelectedIncident() {
    const incident = selectedIncident();
    if (!incident) return;

    elements.analyze.disabled = true;
    elements.analyze.querySelector("span").textContent = "Reviewing evidence";
    elements.ledgerState.textContent = "Working";
    elements.ledgerState.className = "ledger-state is-working";

    try {
      const response = await api(`/api/incidents/${encodeURIComponent(incident.id)}/analyze`, { method: "POST" });
      state.lastReport = response.report ?? response;
      renderTriage(state.lastReport, response.narrative ?? null);
      await loadAudit();
      showToast("Grounded triage prepared. Review the evidence ledger before acting.");
    } catch (error) {
      elements.ledgerState.textContent = "Failed";
      elements.ledgerState.className = "ledger-state";
      showToast(`Triage could not be generated: ${error.message}`, true);
    } finally {
      elements.analyze.disabled = false;
      elements.analyze.querySelector("span").textContent = "Produce triage";
    }
  }

  async function submitReview(outcome, trigger) {
    const incident = selectedIncident();
    if (!incident) return;

    const note = document.getElementById("reviewNote")?.value.trim();
    const feedback = document.getElementById("reviewFeedback");
    const buttons = [...elements.triageResult.querySelectorAll("[data-review-outcome]")];
    buttons.forEach((button) => (button.disabled = true));
    if (feedback) feedback.textContent = "Recording human review...";

    try {
      const payload = { outcome };
      if (note) payload.note = note;
      const traceId = state.lastReport?.provenance?.trace_id;
      if (traceId) payload.trace_id = traceId;
      const response = await api(`/api/incidents/${encodeURIComponent(incident.id)}/reviews`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const review = response.review ?? response;
      const recordedOutcome = codeLabel(review.outcome || outcome);
      const recordedAt = review.recorded_at || review.created_at || review.occurred_at;
      if (feedback) {
        feedback.classList.remove("is-error");
        feedback.classList.add("is-recorded");
        const receipt = review.review_id ? ` Receipt ${review.review_id}.` : " Review receipt created.";
        const recordedNote = review.note ? ` Note: ${review.note}` : "";
        feedback.textContent = `Review recorded: ${recordedOutcome}${recordedAt ? ` at ${formatDate(recordedAt)}` : ""}.${receipt}${recordedNote}`;
      }
      trigger.classList.add("is-chosen");
      await loadAudit();
      showToast("Human review recorded in the decision trail.");
    } catch (error) {
      if (feedback) {
        feedback.classList.remove("is-recorded");
        feedback.classList.add("is-error");
        feedback.textContent = `Review could not be recorded: ${error.message}`;
      }
      showToast(`Review could not be recorded: ${error.message}`, true);
    } finally {
      buttons.forEach((button) => (button.disabled = false));
    }
  }

  async function syncPublicSource() {
    elements.syncSource.disabled = true;
    elements.syncSource.lastChild.textContent = "Syncing";
    try {
      const response = await api("/api/sources/github-status/sync", { method: "POST" });
      const snapshot = response.snapshot ?? response;
      state.sourceSnapshot = snapshot;
      const status = snapshot.status || snapshot.indicator || "synced";
      const description = snapshot.description || snapshot.message || "Public source snapshot captured for this session.";
      elements.sourceStatus.textContent = sentenceCase(status);
      elements.sourceNote.textContent = "public GitHub status signal";
      elements.sourceCardText.textContent = description;
      elements.sourceCard.classList.add("is-synced");
      elements.sourceDetails.hidden = false;
      elements.sourceReceipt.textContent = JSON.stringify(snapshot, null, 2);
      await loadAudit();
      showToast("Public context signal synced and recorded.");
    } catch (error) {
      elements.sourceStatus.textContent = "Unavailable";
      elements.sourceNote.textContent = "public source could not be reached";
      elements.sourceCardText.textContent = "The control room remains usable without this optional external signal.";
      showToast(`Public source unavailable: ${error.message}`, true);
    } finally {
      elements.syncSource.disabled = false;
      elements.syncSource.lastChild.textContent = "Sync public signal";
    }
  }

  async function loadHealth() {
    try {
      const health = await api("/api/health");
      const mode = health.mode ? ` · ${sentenceCase(health.mode)}` : "";
      elements.healthLabel.textContent = `Service available${mode}`;
      elements.healthStatus.classList.add("is-healthy");
    } catch (_) {
      elements.healthLabel.textContent = "Service unavailable";
      elements.healthStatus.classList.add("is-unavailable");
    }
  }

  async function loadEvaluation() {
    try {
      const payload = await api("/api/evaluation");
      const total = Number(payload.total ?? payload.total_cases ?? payload.count ?? 0);
      const passed = Number(payload.passed ?? payload.passed_cases ?? payload.score ?? 0);
      elements.evaluationScore.textContent = total ? `${passed}/${total} passed` : "Available";
      elements.evaluationNote.textContent = payload.note || "golden checks on known incident patterns";
    } catch (_) {
      elements.evaluationScore.textContent = "Local";
      elements.evaluationNote.textContent = "evaluation endpoint unavailable";
    }
  }

  async function loadIncidents() {
    try {
      const payload = await api("/api/incidents");
      state.incidents = sortIncidents(collectionFrom(payload, ["incidents", "items", "data"]));
      renderQueue();
      if (state.incidents.length) await selectIncident(state.incidents[0].id);
    } catch (error) {
      elements.activeCount.textContent = "0";
      elements.queueCount.textContent = "0";
      elements.incidentList.innerHTML = `<p class="empty-list">The queue is unavailable: ${escapeHtml(error.message)}</p>`;
      elements.caseContent.innerHTML = '<div class="empty-case"><span class="empty-symbol" aria-hidden="true">!</span><h2 id="case-title">No data is connected.</h2><p>Start the service to load the local incident scenarios.</p></div>';
    }
  }

  function bindEvents() {
    document.querySelectorAll(".filter").forEach((button) => {
      button.addEventListener("click", () => {
        state.filter = button.dataset.filter || "all";
        document.querySelectorAll(".filter").forEach((item) => item.classList.toggle("is-active", item === button));
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
      button.addEventListener("click", () => document.getElementById(button.dataset.jump)?.scrollIntoView({ behavior: "smooth", block: "start" }));
    });
  }

  async function init() {
    bindEvents();
    await Promise.all([loadHealth(), loadEvaluation(), loadAudit(), loadIncidents()]);
  }

  init();
})();
