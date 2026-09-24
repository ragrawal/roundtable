const AGENT_NAME_PATTERN = /^[a-z][a-z0-9_-]{0,31}$/;

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value;
  return div.innerHTML;
}

// ---- Tabs -------------------------------------------------------------------------

for (const button of document.querySelectorAll(".tab-button")) {
  button.addEventListener("click", () => {
    for (const other of document.querySelectorAll(".tab-button")) {
      other.classList.toggle("active", other === button);
    }
    const targetId = `${button.dataset.tab}-tab`;
    for (const panel of document.querySelectorAll(".tab-panel")) {
      panel.classList.toggle("active", panel.id === targetId);
    }
  });
}

// ---- Roster editor ------------------------------------------------------------------

const rosterRows = document.getElementById("roster-rows");
const rosterMessage = document.getElementById("roster-message");
const roundLimitInput = document.getElementById("round-limit");

function showRosterMessage(text, kind) {
  rosterMessage.textContent = text;
  rosterMessage.className = `message ${kind}`;
  rosterMessage.hidden = false;
}

function clearRosterMessage() {
  rosterMessage.hidden = true;
}

function addAgentRow(agent = { name: "", role: "", persona: "", kind: "" }) {
  const row = document.createElement("tr");
  row.innerHTML = `
    <td><input type="text" class="agent-name" value="${escapeHtml(agent.name)}" /></td>
    <td><input type="text" class="agent-role" value="${escapeHtml(agent.role)}" /></td>
    <td><input type="text" class="agent-persona" value="${escapeHtml(agent.persona)}" /></td>
    <td><input type="text" class="agent-kind" value="${escapeHtml(agent.kind)}" /></td>
    <td><button type="button" class="remove-agent">Remove</button></td>
  `;
  row.querySelector(".remove-agent").addEventListener("click", () => row.remove());
  rosterRows.appendChild(row);
}

document.getElementById("add-agent").addEventListener("click", () => addAgentRow());

function readAgentsFromTable() {
  return [...rosterRows.querySelectorAll("tr")].map((row) => ({
    name: row.querySelector(".agent-name").value.trim(),
    role: row.querySelector(".agent-role").value.trim(),
    persona: row.querySelector(".agent-persona").value.trim(),
    kind: row.querySelector(".agent-kind").value.trim(),
  }));
}

function validateRoster(agents) {
  const developers = agents.filter((agent) => agent.role === "developer");
  if (developers.length === 0) {
    return "Roster must include exactly one developer agent; none was found.";
  }
  if (developers.length > 1) {
    const names = developers.map((agent) => agent.name).join(", ");
    return `Roster must include exactly one developer agent; found ${developers.length}: ${names}.`;
  }
  if (agents.length === developers.length) {
    return "Roster must include at least one reviewer agent; none was found.";
  }
  const names = agents.map((agent) => agent.name);
  const duplicates = [...new Set(names.filter((name) => names.filter((n) => n === name).length > 1))].sort();
  if (duplicates.length > 0) {
    return `Agent names must be unique; duplicated: ${duplicates.join(", ")}.`;
  }
  for (const agent of agents) {
    if (!AGENT_NAME_PATTERN.test(agent.name)) {
      return `'${agent.name}' is not a valid agent name: must start with a lowercase letter and contain only lowercase letters, digits, '-', or '_' (max 32 characters).`;
    }
  }
  return null;
}

async function loadRoster() {
  const response = await fetch("/api/roster");
  const body = await response.json();
  rosterRows.innerHTML = "";
  for (const agent of body.agents) {
    addAgentRow(agent);
  }
  roundLimitInput.value = body.round_limit;
}

document.getElementById("save-roster").addEventListener("click", async () => {
  clearRosterMessage();
  const agents = readAgentsFromTable();

  const validationError = validateRoster(agents);
  if (validationError) {
    showRosterMessage(validationError, "error");
    return;
  }

  const response = await fetch("/api/roster", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agents, round_limit: Number(roundLimitInput.value) }),
  });

  if (response.status === 409) {
    const body = await response.json();
    showRosterMessage(body.detail || "Someone else is editing the roster. Try again.", "locked");
    return;
  }
  if (response.status === 422) {
    const body = await response.json();
    showRosterMessage(body.detail, "error");
    return;
  }
  if (!response.ok) {
    showRosterMessage(`Save failed (${response.status}).`, "error");
    return;
  }

  const saved = await response.json();
  roundLimitInput.value = saved.round_limit;
  showRosterMessage("Roster saved.", "success");
});

loadRoster();

// ---- Event feed ---------------------------------------------------------------------

const outcomeLabelBadge = document.getElementById("outcome-label");
const connectionHealthBadge = document.getElementById("connection-health");
const eventGroupsContainer = document.getElementById("event-groups");
const versionList = document.getElementById("version-list");

let socket = null;
let reconnectAttempt = 0;
let reconnectTimer = null;
const seenEventIds = new Set();
const eventsByRound = new Map();
let currentSpecificationId = null;

function outcomeBadgeClass(outcomeLabel) {
  if (outcomeLabel === "consensus reached") return "consensus-reached";
  if (outcomeLabel === "deadlocked (may still be active)") return "deadlocked";
  if (outcomeLabel.includes("estimated") || outcomeLabel.includes("may be drafting")) return "estimate";
  return "";
}

function renderStatus(status) {
  outcomeLabelBadge.textContent = status.outcome_label;
  outcomeLabelBadge.className = `badge ${outcomeBadgeClass(status.outcome_label)}`;
  connectionHealthBadge.textContent = status.connection_health;
  connectionHealthBadge.className = `badge ${status.connection_health}`;
}

function markDisconnected() {
  connectionHealthBadge.textContent = "disconnected";
  connectionHealthBadge.className = "badge disconnected";
}

const ENVELOPE_FIELDS = new Set([
  "event_id",
  "timestamp",
  "specification_id",
  "emitter",
  "event_type",
  "round",
]);

function formatPayloadValue(value) {
  const text = typeof value === "string" ? value : JSON.stringify(value);
  return escapeHtml(text);
}

function renderPayloadFields(event) {
  return Object.entries(event)
    .filter(([key]) => !ENVELOPE_FIELDS.has(key))
    .map(([key, value]) => `<div><strong>${escapeHtml(key)}:</strong> ${formatPayloadValue(value)}</div>`)
    .join("");
}

function renderEventGroups() {
  eventGroupsContainer.innerHTML = "";
  const roundNumbers = [...eventsByRound.keys()].sort((a, b) => Number(a) - Number(b));
  for (const roundNumber of roundNumbers) {
    const groupElement = document.createElement("div");
    groupElement.className = "round-group";
    const heading = document.createElement("h4");
    heading.textContent = `Round ${roundNumber}`;
    groupElement.appendChild(heading);
    for (const event of eventsByRound.get(roundNumber)) {
      const item = document.createElement("div");
      item.className = "event-item";
      item.innerHTML = `
        <div><span class="event-type">${escapeHtml(event.event_type)}</span> — ${escapeHtml(event.emitter)} — ${escapeHtml(event.timestamp)}</div>
        ${renderPayloadFields(event)}
      `;
      groupElement.appendChild(item);
    }
    eventGroupsContainer.appendChild(groupElement);
  }
}

function currentFilters() {
  return {
    emitter: document.getElementById("filter-emitter").value.trim(),
    event_type: document.getElementById("filter-event-type").value,
    round: document.getElementById("filter-round").value.trim(),
    keyword: document.getElementById("filter-keyword").value.trim(),
  };
}

async function refreshVersions(specificationId) {
  const response = await fetch(`/api/specifications/${encodeURIComponent(specificationId)}/versions`);
  const versions = await response.json();
  versionList.innerHTML = "";
  for (const version of versions) {
    const item = document.createElement("li");
    item.innerHTML = `<span class="summary-label">Summary (${escapeHtml(version.emitter)}, ${escapeHtml(version.version_id)})</span>${escapeHtml(version.content)}`;
    versionList.appendChild(item);
  }
}

function scheduleReconnect(specificationId) {
  reconnectAttempt += 1;
  const delaySeconds = Math.min(2 ** reconnectAttempt, 16);
  reconnectTimer = setTimeout(() => connectFeed(specificationId), delaySeconds * 1000);
}

function connectFeed(specificationId) {
  currentSpecificationId = specificationId;
  clearTimeout(reconnectTimer);

  const filters = currentFilters();
  const query = new URLSearchParams();
  if (filters.emitter) query.set("emitter", filters.emitter);
  if (filters.event_type) query.set("event_type", filters.event_type);
  if (filters.round) query.set("round", filters.round);
  if (filters.keyword) query.set("keyword", filters.keyword);

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${protocol}//${window.location.host}/ws/specifications/${encodeURIComponent(specificationId)}/events?${query}`;

  socket = new WebSocket(url);

  socket.addEventListener("open", () => {
    reconnectAttempt = 0;
  });

  socket.addEventListener("message", (messageEvent) => {
    const payload = JSON.parse(messageEvent.data);
    let sawNewDraft = false;
    for (const event of payload.events) {
      if (seenEventIds.has(event.event_id)) continue;
      seenEventIds.add(event.event_id);
      if (!eventsByRound.has(event.round)) eventsByRound.set(event.round, []);
      eventsByRound.get(event.round).push(event);
      if (event.event_type === "ArtifactDrafted") sawNewDraft = true;
    }
    renderEventGroups();
    renderStatus(payload.status);
    if (sawNewDraft) refreshVersions(specificationId);
  });

  socket.addEventListener("close", () => {
    markDisconnected();
    scheduleReconnect(specificationId);
  });
}

document.getElementById("connect-feed").addEventListener("click", () => {
  const specificationId = document.getElementById("specification-id").value.trim();
  if (!specificationId) return;

  if (socket) {
    socket.onclose = null;
    socket.close();
  }
  clearTimeout(reconnectTimer);
  reconnectAttempt = 0;
  seenEventIds.clear();
  eventsByRound.clear();
  renderEventGroups();
  versionList.innerHTML = "";

  refreshVersions(specificationId);
  connectFeed(specificationId);
});

for (const filterId of ["filter-emitter", "filter-event-type", "filter-round", "filter-keyword"]) {
  document.getElementById(filterId).addEventListener("change", () => {
    if (!currentSpecificationId) return;
    if (socket) {
      socket.onclose = null;
      socket.close();
    }
    clearTimeout(reconnectTimer);
    reconnectAttempt = 0;
    seenEventIds.clear();
    eventsByRound.clear();
    renderEventGroups();
    connectFeed(currentSpecificationId);
  });
}
