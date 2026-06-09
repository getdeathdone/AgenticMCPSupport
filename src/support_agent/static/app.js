const form = document.querySelector("#chat-form");
const input = document.querySelector("#message-input");
const messages = document.querySelector("#messages");
const sendButton = document.querySelector("#send-button");
const tabButtons = document.querySelectorAll("[data-view]");
const views = document.querySelectorAll(".view");
const tableSelect = document.querySelector("#table-select");
const dataTable = document.querySelector("#data-table");
const activeDb = document.querySelector("#active-db");

const DB_CACHE_KEY = "support-agent-default-db-snapshot";
let cachedSnapshot = null;

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
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
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

async function loadDatabaseSnapshot() {
  try {
    const response = await fetch("/api/database/snapshot", { cache: "no-store" });
    if (!response.ok) {
      throw new Error("Could not fetch database snapshot.");
    }

    cachedSnapshot = await response.json();
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
    renderTable(cachedSnapshot.tables[tableNames[0]]);
  }
}

function renderTable(rows) {
  const thead = dataTable.querySelector("thead");
  const tbody = dataTable.querySelector("tbody");
  thead.innerHTML = "";
  tbody.innerHTML = "";

  if (!rows.length) {
    tbody.innerHTML = "<tr><td>No rows</td></tr>";
    return;
  }

  const columns = Object.keys(rows[0]);
  const headerRow = document.createElement("tr");
  columns.forEach((column) => {
    const th = document.createElement("th");
    th.textContent = column;
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);

  rows.forEach((row) => {
    const tr = document.createElement("tr");
    columns.forEach((column) => {
      const td = document.createElement("td");
      td.textContent = row[column] ?? "";
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
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

void loadDatabaseSnapshot();
