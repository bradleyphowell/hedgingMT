const marketForm = document.getElementById("market-form");
const marketInput = document.getElementById("market-input");
const presetBar = document.getElementById("preset-bar");
const selectedMarket = document.getElementById("selected-market");
const binanceSymbol = document.getElementById("binance-symbol");
const clockOffset = document.getElementById("clock-offset");
const updatedAt = document.getElementById("updated-at");

const bookEventP50 = document.getElementById("book-event-p50");
const decisionToQuoteP95 = document.getElementById("decision-to-quote-p95");
const bookProcessP95 = document.getElementById("book-process-p95");
const quoteCreateP50 = document.getElementById("quote-create-p50");
const makerUpsertP95 = document.getElementById("maker-upsert-p95");
const tradeEventP50 = document.getElementById("trade-event-p50");
const bookRate = document.getElementById("book-rate");
const tradeRate = document.getElementById("trade-rate");
const bookAge = document.getElementById("book-age");
const bookQueueDepth = document.getElementById("book-queue-depth");
const tradeQueueDepth = document.getElementById("trade-queue-depth");
const orderAck = document.getElementById("order-ack");

const latencyRows = document.getElementById("latency-rows");

const state = {
  socket: null,
  latest: null,
};

function connect() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${window.location.host}/ws`);
  state.socket = socket;

  socket.addEventListener("message", (event) => {
    const payload = JSON.parse(event.data);
    state.latest = payload;
    render(payload);
  });

  socket.addEventListener("close", () => {
    window.setTimeout(connect, 1000);
  });
}

function render(payload) {
  selectedMarket.textContent = payload.market.market;
  binanceSymbol.textContent = payload.market.binance_symbol;
  clockOffset.textContent = formatSignedMs(payload.clockOffsetMs);
  updatedAt.textContent = formatTime(payload.updatedAtMs);

  renderPresets(payload.presets || []);
  renderSummary(payload.summary || {});
  renderRows(payload.stages || []);
}

function renderPresets(presets) {
  if (presetBar.children.length > 0) {
    return;
  }
  presets.forEach((market) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "preset";
    button.textContent = market;
    button.addEventListener("click", () => {
      marketInput.value = market;
      selectMarket(market);
    });
    presetBar.appendChild(button);
  });
}

function renderSummary(summary) {
  bookEventP50.textContent = formatMs(summary.bookEventP50Ms);
  decisionToQuoteP95.textContent = formatMs(summary.decisionToQuoteP95Ms);
  bookProcessP95.textContent = formatMs(summary.bookProcessP95Ms);
  quoteCreateP50.textContent = formatMs(summary.quoteCreateP50Ms);
  makerUpsertP95.textContent = formatMs(summary.makerUpsertP95Ms);
  tradeEventP50.textContent = formatMs(summary.tradeEventP50Ms);
  bookRate.textContent = formatRate(summary.bookRatePerSec);
  tradeRate.textContent = formatRate(summary.tradeRatePerSec);
  bookAge.textContent = formatAgeValue(summary.currentBookAgeMs);
  bookQueueDepth.textContent = formatCount(summary.bookQueueDepth);
  tradeQueueDepth.textContent = formatCount(summary.tradeQueueDepth);
  orderAck.textContent = summary.orderAckMs == null ? "Pending" : formatMs(summary.orderAckMs);
}

function renderRows(rows) {
  latencyRows.innerHTML = "";
  if (!rows.length) {
    const empty = document.createElement("tr");
    empty.innerHTML = `<td colspan="9" class="empty-cell">Waiting for latency samples...</td>`;
    latencyRows.appendChild(empty);
    return;
  }

  rows.forEach((rowData) => {
    const row = document.createElement("tr");
    row.className = `latency-row latency-${rowData.status || "idle"}`;
    row.innerHTML = `
      <td class="stage-cell">
        <span class="stage-name">${rowData.label}</span>
      </td>
      <td><span class="status-pill status-${rowData.status || "idle"}">${formatStatus(rowData.status)}</span></td>
      <td>${formatMs(rowData.lastMs)}</td>
      <td>${formatMs(rowData.p50Ms)}</td>
      <td>${formatMs(rowData.p95Ms)}</td>
      <td>${formatMs(rowData.meanMs)}</td>
      <td>${formatMs(rowData.maxMs)}</td>
      <td>${formatCount(rowData.count)}</td>
      <td class="desc-cell">${rowData.description}</td>
    `;
    latencyRows.appendChild(row);
  });
}

function selectMarket(market) {
  if (!state.socket || state.socket.readyState !== WebSocket.OPEN) {
    return;
  }
  state.socket.send(JSON.stringify({ type: "select_market", market }));
}

marketForm.addEventListener("submit", (event) => {
  event.preventDefault();
  selectMarket(marketInput.value);
});

function formatMs(value) {
  if (value == null || Number.isNaN(value)) {
    return "--";
  }
  if (value >= 1000) {
    return `${(Number(value) / 1000).toFixed(2)} s`;
  }
  if (value >= 100) {
    return `${Number(value).toFixed(1)} ms`;
  }
  return `${Number(value).toFixed(3)} ms`;
}

function formatSignedMs(value) {
  if (value == null || Number.isNaN(value)) {
    return "--";
  }
  const sign = value > 0 ? "+" : "";
  return `${sign}${Number(value).toFixed(1)} ms`;
}

function formatRate(value) {
  if (value == null || Number.isNaN(value)) {
    return "--";
  }
  return `${Number(value).toFixed(1)} /s`;
}

function formatAgeValue(value) {
  if (value == null || Number.isNaN(value)) {
    return "--";
  }
  if (value < 1000) {
    return `${Math.round(value)} ms`;
  }
  return `${(Number(value) / 1000).toFixed(2)} s`;
}

function formatCount(value) {
  if (value == null || Number.isNaN(value)) {
    return "--";
  }
  return String(value);
}

function formatStatus(value) {
  if (!value) {
    return "Idle";
  }
  if (value === "placeholder") {
    return "Pending";
  }
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function formatTime(value) {
  if (!value) {
    return "Waiting...";
  }
  return new Date(value).toLocaleTimeString();
}

window.setInterval(() => {
  if (state.latest) {
    updatedAt.textContent = formatTime(state.latest.updatedAtMs);
    const summary = state.latest.summary || {};
    bookAge.textContent = formatAgeValue(summary.currentBookAgeMs);
  }
}, 250);

connect();
