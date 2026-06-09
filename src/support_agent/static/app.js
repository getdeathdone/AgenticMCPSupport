const form = document.querySelector("#chat-form");
const input = document.querySelector("#message-input");
const messages = document.querySelector("#messages");
const sendButton = document.querySelector("#send-button");
const tabButtons = document.querySelectorAll("[data-view]");
const views = document.querySelectorAll(".view");
const tableSelect = document.querySelector("#table-select");
const dataTable = document.querySelector("#data-table");
const activeDb = document.querySelector("#active-db");
const addRowButton = document.querySelector("#add-row-button");
const resetSnapshotButton = document.querySelector("#reset-snapshot-button");
const rowDialog = document.querySelector("#row-dialog");
const rowForm = document.querySelector("#row-form");
const rowFields = document.querySelector("#row-fields");
const rowDialogTitle = document.querySelector("#row-dialog-title");
const closeRowDialogButton = document.querySelector("#close-row-dialog");
const cancelRowButton = document.querySelector("#cancel-row-button");
const localDocUpload = document.querySelector("#local-doc-upload");
const localDocList = document.querySelector("#local-doc-list");
const clearLocalDocsButton = document.querySelector("#clear-local-docs-button");

const DB_CACHE_KEY = "support-agent-default-db-snapshot";
const DB_DEFAULT_CACHE_KEY = "support-agent-default-db-original-snapshot";
const LOCAL_DOCS_KEY = "support-agent-local-documents";
const TABLE_COLUMNS = {
  tickets: [
    "id",
    "requester_email",
    "subject",
    "category",
    "priority",
    "status",
    "assigned_team",
    "created_at",
    "updated_at",
    "latest_note",
  ],
  services: ["id", "name", "status", "owner_team", "region", "last_checked", "details"],
  incidents: ["id", "service_name", "severity", "status", "title", "started_at", "updated_at", "summary"],
  users: ["id", "name", "email", "department", "role", "location", "support_tier"],
  devices: ["id", "user_email", "hostname", "os", "encryption_status", "last_seen", "health"],
  knowledge_articles: ["id", "title", "category", "keywords", "content", "updated_at"],
};
let cachedSnapshot = null;
let editingRowIndex = null;
let localDocuments = loadLocalDocuments();

function appendMessage({ role, text, route, latencyMs, source, reason, error = false }) {
  const article = document.createElement("article");
  article.className = `message ${role}${error ? " error" : ""}`;

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = role === "user" ? "You" : "AI";

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;

  if (route || latencyMs !== undefined || source || reason) {
    const meta = document.createElement("div");
    meta.className = "meta";

    if (route) {
      meta.appendChild(createChip(route.toUpperCase(), route));
    }
    if (latencyMs !== undefined) {
      meta.appendChild(createChip(`${latencyMs} ms`, "latency"));
    }
    if (source) {
      meta.appendChild(createChip(source, "source"));
    }
    if (reason) {
      meta.appendChild(createChip(reason, "reason"));
    }

    bubble.appendChild(meta);
  }

  article.appendChild(avatar);
  article.appendChild(bubble);
  messages.appendChild(article);
  messages.scrollTop = messages.scrollHeight;
}

function createChip(text, type) {
  const chip = document.createElement("span");
  chip.className = `chip ${type}`;
  chip.textContent = text;
  return chip;
}

async function sendMessage(message) {
  appendMessage({ role: "user", text: message });
  sendButton.disabled = true;
  input.disabled = true;

  try {
    const sessionContext = buildSessionContext(message);
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session_context: sessionContext }),
    });

    if (!response.ok) {
      throw new Error("The agent API returned an error.");
    }

    const data = await response.json();
    appendMessage({
      role: "agent",
      text: data.answer,
      route: data.route,
      latencyMs: data.latency_ms,
      source: data.source,
      reason: data.reason,
    });
  } catch (error) {
    appendMessage({
      role: "agent",
      text: "I could not reach the support agent API. Check the Python service logs and try again.",
      error: true,
    });
  } finally {
    sendButton.disabled = false;
    input.disabled = false;
    input.focus();
  }
}

function buildSessionContext(message) {
  if (!cachedSnapshot || !cachedSnapshot.tables) {
    return { source: "none", rows: {} };
  }

  const rows = {};
  const normalized = message.toLowerCase();
  const ticketId = extractTicketId(normalized);
  const email = extractEmail(normalized);
  const serviceName = extractServiceName(normalized);

  if (ticketId !== null) {
    rows.tickets = cachedSnapshot.tables.tickets.filter((ticket) => Number(ticket.id) === ticketId);
  }

  if (serviceName) {
    rows.services = cachedSnapshot.tables.services.filter(
      (service) => String(service.name).toLowerCase() === serviceName,
    );
    rows.incidents = cachedSnapshot.tables.incidents.filter(
      (incident) => String(incident.service_name).toLowerCase() === serviceName,
    );
  }

  if (email) {
    rows.users = cachedSnapshot.tables.users.filter(
      (user) => String(user.email).toLowerCase() === email,
    );
    rows.devices = cachedSnapshot.tables.devices.filter(
      (device) => String(device.user_email).toLowerCase() === email,
    );
  }

  if (Object.keys(rows).length === 0) {
    rows.knowledge_articles = findKnowledgeArticles(normalized);
  }

  const documents = findLocalDocuments(normalized);

  return {
    source: "browser_local_snapshot",
    database: cachedSnapshot.name,
    version: cachedSnapshot.version,
    rows,
    documents,
  };
}

function extractTicketId(text) {
  const direct = text.match(/(?:ticket|tiket|case|issue)\s*#?\s*(\d{3,})/i);
  if (direct) {
    return Number(direct[1]);
  }

  const loose = text.match(/#\s*(\d{3,})/);
  return loose ? Number(loose[1]) : null;
}

function extractEmail(text) {
  const match = text.match(/[\w.+-]+@[\w-]+\.[\w.-]+/);
  return match ? match[0].toLowerCase() : null;
}

function extractServiceName(text) {
  const services = cachedSnapshot.tables.services || [];
  const terms = text.split(/[^a-z0-9-]+/).filter(Boolean);

  for (const service of services) {
    const serviceName = String(service.name).toLowerCase();
    if (text.includes(serviceName) || terms.some((term) => isClose(term, serviceName))) {
      return serviceName;
    }
  }
  return null;
}

function findKnowledgeArticles(text) {
  const terms = text.split(/[^a-z0-9-]+/).filter((term) => term.length > 2);
  const articles = cachedSnapshot.tables.knowledge_articles || [];

  return articles
    .map((article) => ({
      article,
      score: scoreTextMatch(terms, `${article.title} ${article.category} ${article.keywords} ${article.content}`),
    }))
    .filter((item) => item.score > 0)
    .sort((left, right) => right.score - left.score)
    .slice(0, 2)
    .map((item) => item.article);
}

function findLocalDocuments(text) {
  const terms = text.split(/[^a-z0-9-]+/).filter((term) => term.length > 2);
  return localDocuments
    .flatMap((document) =>
      chunkDocument(document).map((chunk) => ({
        ...chunk,
        score: scoreTextMatch(terms, `${chunk.name} ${chunk.heading} ${chunk.content}`),
      })),
    )
    .filter((chunk) => chunk.score > 0)
    .sort((left, right) => right.score - left.score)
    .slice(0, 2)
    .map(({ score, ...chunk }) => chunk);
}

function chunkDocument(document) {
  const sections = [];
  const matches = [...document.content.matchAll(/^##\s+(.+)$/gim)];
  if (!matches.length) {
    return [
      {
        name: document.name,
        heading: document.name,
        content: compactText(document.content),
      },
    ];
  }

  matches.forEach((match, index) => {
    const start = match.index + match[0].length;
    const end = index + 1 < matches.length ? matches[index + 1].index : document.content.length;
    sections.push({
      name: document.name,
      heading: match[1].trim(),
      content: compactText(document.content.slice(start, end)),
    });
  });

  return sections;
}

function compactText(text) {
  return text.replace(/^#+\s+/gm, "").replace(/\s+/g, " ").trim();
}

function scoreTextMatch(terms, targetText) {
  const targetTerms = targetText.toLowerCase().split(/[^a-z0-9-]+/).filter(Boolean);
  return terms.reduce((score, term) => {
    if (targetTerms.includes(term)) {
      return score + 2;
    }
    return targetTerms.some((targetTerm) => isClose(term, targetTerm)) ? score + 1 : score;
  }, 0);
}

function isClose(left, right) {
  if (left === right || left.includes(right) || right.includes(left)) {
    return true;
  }

  const rows = Array.from({ length: left.length + 1 }, (_, index) => [index]);
  for (let col = 1; col <= right.length; col += 1) {
    rows[0][col] = col;
  }

  for (let row = 1; row <= left.length; row += 1) {
    for (let col = 1; col <= right.length; col += 1) {
      const cost = left[row - 1] === right[col - 1] ? 0 : 1;
      rows[row][col] = Math.min(
        rows[row - 1][col] + 1,
        rows[row][col - 1] + 1,
        rows[row - 1][col - 1] + cost,
      );
    }
  }

  const distance = rows[left.length][right.length];
  const maxLength = Math.max(left.length, right.length);
  return maxLength > 0 && 1 - distance / maxLength >= 0.78;
}

async function loadDatabaseSnapshot() {
  const localSnapshot = localStorage.getItem(DB_CACHE_KEY);
  if (localSnapshot) {
    const parsedSnapshot = JSON.parse(localSnapshot);
    if (parsedSnapshot.local_edits) {
      cachedSnapshot = parsedSnapshot;
      activeDb.textContent = `Local session edits: ${cachedSnapshot.name} (${cachedSnapshot.version})`;
      renderTableSelector();
      return;
    }
  }

  try {
    const response = await fetch("/api/database/snapshot", { cache: "no-store" });
    if (!response.ok) {
      throw new Error("Could not fetch database snapshot.");
    }

    cachedSnapshot = await response.json();
    if (!localStorage.getItem(DB_DEFAULT_CACHE_KEY)) {
      localStorage.setItem(DB_DEFAULT_CACHE_KEY, JSON.stringify(cachedSnapshot));
    }
    localStorage.setItem(DB_CACHE_KEY, JSON.stringify(cachedSnapshot));
    activeDb.textContent = `Cached locally: ${cachedSnapshot.name} (${cachedSnapshot.version})`;
  } catch (error) {
    const cached = localStorage.getItem(DB_CACHE_KEY);
    if (!cached) {
      activeDb.textContent = "Database snapshot is unavailable.";
      throw error;
    }

    cachedSnapshot = JSON.parse(cached);
    activeDb.textContent = `Loaded from browser cache: ${cachedSnapshot.name} (${cachedSnapshot.version})`;
  }

  renderTableSelector();
}

function renderTableSelector() {
  const tableNames = Object.keys(cachedSnapshot.tables);
  tableSelect.innerHTML = "";

  tableNames.forEach((table) => {
    const option = document.createElement("option");
    option.value = table;
    option.textContent = table;
    tableSelect.appendChild(option);
  });

  if (tableNames.length > 0) {
    tableSelect.value = tableNames[0];
    renderTable(cachedSnapshot.tables[tableNames[0]]);
  }
}

function renderTable(rows) {
  const thead = dataTable.querySelector("thead");
  const tbody = dataTable.querySelector("tbody");
  thead.innerHTML = "";
  tbody.innerHTML = "";

  const columns = getColumnsForCurrentTable();
  const headerRow = document.createElement("tr");
  columns.forEach((column) => {
    const th = document.createElement("th");
    th.textContent = column;
    headerRow.appendChild(th);
  });
  const actionsHeader = document.createElement("th");
  actionsHeader.textContent = "actions";
  headerRow.appendChild(actionsHeader);
  thead.appendChild(headerRow);

  if (!rows.length) {
    const emptyRow = document.createElement("tr");
    const emptyCell = document.createElement("td");
    emptyCell.colSpan = columns.length + 1;
    emptyCell.textContent = "No local rows";
    emptyRow.appendChild(emptyCell);
    tbody.appendChild(emptyRow);
    return;
  }

  rows.forEach((row, index) => {
    const tr = document.createElement("tr");
    columns.forEach((column) => {
      const td = document.createElement("td");
      td.textContent = row[column] ?? "";
      tr.appendChild(td);
    });
    const actions = document.createElement("td");
    actions.className = "row-actions";
    actions.appendChild(createRowAction("Edit", () => openRowDialog(index)));
    actions.appendChild(createRowAction("Delete", () => deleteRow(index)));
    tr.appendChild(actions);
    tbody.appendChild(tr);
  });
}

function createRowAction(label, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.addEventListener("click", onClick);
  return button;
}

function getCurrentTableName() {
  return tableSelect.value;
}

function getCurrentRows() {
  return cachedSnapshot.tables[getCurrentTableName()] || [];
}

function getColumnsForCurrentTable() {
  const rows = getCurrentRows();
  if (rows.length > 0) {
    return Object.keys(rows[0]);
  }
  return TABLE_COLUMNS[getCurrentTableName()] || [];
}

function openRowDialog(rowIndex = null) {
  editingRowIndex = rowIndex;
  const isEdit = rowIndex !== null;
  const row = isEdit ? getCurrentRows()[rowIndex] : buildEmptyRow();
  rowDialogTitle.textContent = `${isEdit ? "Edit" : "Add"} ${getCurrentTableName()} row`;
  rowFields.innerHTML = "";

  Object.entries(row).forEach(([key, value]) => {
    const label = document.createElement("label");
    label.textContent = key;

    const input = document.createElement("input");
    input.name = key;
    input.value = value ?? "";
    input.autocomplete = "off";

    label.appendChild(input);
    rowFields.appendChild(label);
  });

  rowDialog.showModal();
}

function buildEmptyRow() {
  const columns = getColumnsForCurrentTable();
  return Object.fromEntries(columns.map((column) => [column, ""]));
}

function saveRowFromDialog() {
  const formData = new FormData(rowForm);
  const row = {};
  formData.forEach((value, key) => {
    row[key] = coerceValue(value);
  });

  const rows = getCurrentRows();
  if (editingRowIndex === null) {
    rows.push(row);
  } else {
    rows[editingRowIndex] = row;
  }

  persistSnapshot();
  renderTable(rows);
  rowDialog.close();
}

function deleteRow(rowIndex) {
  if (!confirm("Delete this local row?")) {
    return;
  }

  const rows = getCurrentRows();
  rows.splice(rowIndex, 1);
  persistSnapshot();
  renderTable(rows);
}

function resetSnapshot() {
  if (!confirm("Reset local snapshot to the default site database?")) {
    return;
  }

  const original = localStorage.getItem(DB_DEFAULT_CACHE_KEY);
  if (!original) {
    localStorage.removeItem(DB_CACHE_KEY);
    void loadDatabaseSnapshot();
    return;
  }

  cachedSnapshot = JSON.parse(original);
  localStorage.setItem(DB_CACHE_KEY, JSON.stringify(cachedSnapshot));
  activeDb.textContent = `Reset locally: ${cachedSnapshot.name} (${cachedSnapshot.version})`;
  renderTableSelector();
}

function persistSnapshot() {
  cachedSnapshot.local_edits = true;
  localStorage.setItem(DB_CACHE_KEY, JSON.stringify(cachedSnapshot));
  activeDb.textContent = `Local session edits: ${cachedSnapshot.name} (${cachedSnapshot.version})`;
}

function coerceValue(value) {
  const text = String(value);
  if (/^-?\d+$/.test(text)) {
    return Number(text);
  }
  return text;
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message) {
    return;
  }

  input.value = "";
  void sendMessage(message);
});

tabButtons.forEach((button) => {
  button.addEventListener("click", () => {
    tabButtons.forEach((tab) => tab.classList.remove("active"));
    views.forEach((view) => view.classList.remove("active"));
    button.classList.add("active");
    document.querySelector(`#${button.dataset.view}`).classList.add("active");
  });
});

tableSelect.addEventListener("change", () => {
  renderTable(cachedSnapshot.tables[tableSelect.value]);
});

addRowButton.addEventListener("click", () => {
  openRowDialog();
});

resetSnapshotButton.addEventListener("click", resetSnapshot);

rowForm.addEventListener("submit", (event) => {
  event.preventDefault();
  saveRowFromDialog();
});

closeRowDialogButton.addEventListener("click", () => rowDialog.close());
cancelRowButton.addEventListener("click", () => rowDialog.close());

localDocUpload.addEventListener("change", async () => {
  const files = [...localDocUpload.files];
  const loadedDocs = await Promise.all(files.map(readLocalDocument));
  localDocuments = mergeDocuments(localDocuments, loadedDocs);
  persistLocalDocuments();
  renderLocalDocuments();
  localDocUpload.value = "";
});

clearLocalDocsButton.addEventListener("click", () => {
  if (!confirm("Clear local documents from this browser?")) {
    return;
  }
  localDocuments = [];
  persistLocalDocuments();
  renderLocalDocuments();
});

function readLocalDocument(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      resolve({
        id: `${file.name}-${file.size}-${file.lastModified}`,
        name: file.name,
        content: String(reader.result || ""),
      });
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsText(file);
  });
}

function mergeDocuments(existingDocs, incomingDocs) {
  const byId = new Map(existingDocs.map((document) => [document.id, document]));
  incomingDocs.forEach((document) => byId.set(document.id, document));
  return [...byId.values()];
}

function loadLocalDocuments() {
  const stored = localStorage.getItem(LOCAL_DOCS_KEY);
  return stored ? JSON.parse(stored) : [];
}

function persistLocalDocuments() {
  localStorage.setItem(LOCAL_DOCS_KEY, JSON.stringify(localDocuments));
}

function renderLocalDocuments() {
  localDocList.innerHTML = "";
  if (!localDocuments.length) {
    localDocList.textContent = "No local docs attached";
    return;
  }

  localDocuments.forEach((localDocument) => {
    const item = window.document.createElement("div");
    item.className = "local-doc-item";
    const name = window.document.createElement("span");
    name.textContent = localDocument.name;
    const remove = window.document.createElement("button");
    remove.type = "button";
    remove.textContent = "Remove";
    remove.addEventListener("click", () => {
      localDocuments = localDocuments.filter((candidate) => candidate.id !== localDocument.id);
      persistLocalDocuments();
      renderLocalDocuments();
    });
    item.appendChild(name);
    item.appendChild(remove);
    localDocList.appendChild(item);
  });
}

renderLocalDocuments();
void loadDatabaseSnapshot();
