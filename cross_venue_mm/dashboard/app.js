const marketForm = document.getElementById("market-form");
const marketInput = document.getElementById("market-input");
const presetBar = document.getElementById("preset-bar");
const selectedMarket = document.getElementById("selected-market");
const binanceSymbol = document.getElementById("binance-symbol");
const quoteMode = document.getElementById("quote-mode");
const currentOfi = document.getElementById("current-ofi");
const updatedAt = document.getElementById("updated-at");
const pnlMark = document.getElementById("pnl-mark");
const netPnl = document.getElementById("net-pnl");
const realizedPnl = document.getElementById("realized-pnl");
const unrealizedPnl = document.getElementById("unrealized-pnl");
const feesPaid = document.getElementById("fees-paid");
const positionSide = document.getElementById("position-side");
const positionQty = document.getElementById("position-qty");
const netExposure = document.getElementById("net-exposure");
const grossExposure = document.getElementById("gross-exposure");
const avgEntry = document.getElementById("avg-entry");
const workingBidUsd = document.getElementById("working-bid-usd");
const workingAskUsd = document.getElementById("working-ask-usd");
const workingTotalUsd = document.getElementById("working-total-usd");
const controlsForm = document.getElementById("controls-form");
const controlsGrid = document.getElementById("controls-grid");
const controlsStatus = document.getElementById("controls-status");
const controlsError = document.getElementById("controls-error");
const applyInputsButton = document.getElementById("apply-inputs");

const binanceStatus = document.getElementById("binance-status");
const binanceSpread = document.getElementById("binance-spread");
const binanceQuoteSpread = document.getElementById("binance-quote-spread");
const binanceMid = document.getElementById("binance-mid");
const quoteMid = document.getElementById("quote-mid");
const binanceAge = document.getElementById("binance-age");
const binanceError = document.getElementById("binance-error");
const binanceBook = document.getElementById("binance-book");

const chartLast = document.getElementById("chart-last");
const chartHigh = document.getElementById("chart-high");
const chartLow = document.getElementById("chart-low");
const chartStart = document.getElementById("chart-start");
const chartEnd = document.getElementById("chart-end");
const priceChart = document.getElementById("price-chart");

const tradeCount = document.getElementById("trade-count");
const recentTrades = document.getElementById("recent-trades");

const LADDER_LEVELS = 10;
const CHART_WIDTH = 640;
const CHART_HEIGHT = 240;
const CHART_PADDING_X = 18;
const CHART_PADDING_Y = 18;

const state = {
  socket: null,
  latest: null,
  ladder: { centerPx: null, centeredAtMs: 0, symbol: null },
  controls: { initialized: false, dirty: false, applying: false },
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
  quoteMode.textContent = formatMode(payload.myQuotes?.mode);
  currentOfi.textContent = formatSigned(payload.myQuotes?.ofiValue, 3);
  updatedAt.textContent = formatTime(payload.updatedAtMs);

  renderPresets(payload.presets || []);
  renderControlPanel(payload.inputSchema || [], payload.inputs || {}, payload.inputError || null);
  renderAccount(payload.account || null);
  renderBook(payload.market.binance_symbol, payload.book, payload.myQuotes);
  renderTrades(payload.recentTrades || []);
  renderPriceChart(payload.priceHistory || []);
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
      resetLadderCenter();
      selectMarket(market);
    });
    presetBar.appendChild(button);
  });
}

function renderBook(symbol, book, myQuotes) {
  binanceStatus.textContent = capitalize(book.status || "idle");
  binanceStatus.className = `status-pill status-${book.status || "idle"}`;
  binanceSpread.textContent = book.spreadBps == null ? "Spread --" : `Spread ${book.spreadBps.toFixed(2)} bps`;
  binanceQuoteSpread.textContent = myQuotes?.quotedSpreadBps == null
    ? "Quoted --"
    : `Quoted ${myQuotes.quotedSpreadBps.toFixed(2)} bps`;
  binanceMid.textContent = formatNumber(book.midPx);
  quoteMid.textContent = formatNumber(myQuotes?.quotedMidPx);
  binanceAge.textContent = book.recvTsMs ? formatAge(book.recvTsMs) : "--";

  if (book.error) {
    binanceError.textContent = book.error;
    binanceError.classList.remove("hidden");
  } else {
    binanceError.textContent = "";
    binanceError.classList.add("hidden");
  }

  const displayCenter = updateLadderCenter(symbol, book);
  binanceBook.innerHTML = "";

  const askRows = buildLadderRows((book.asks || []).slice(0, LADDER_LEVELS), myQuotes?.ask || null, "ask").reverse();
  while (askRows.length < LADDER_LEVELS) {
    askRows.unshift(blankRow());
  }
  askRows.forEach((ask, index) => {
    binanceBook.appendChild(
      createLadderRow({
        myBidSize: null,
        bidSize: null,
        bidPx: null,
        askPx: ask.px,
        askSize: ask.sz,
        myAskSize: ask.mySz,
        quotedBid: false,
        quotedAsk: ask.isQuoted,
        rowClass: `ladder-row ask-row${index === askRows.length - 1 ? " near-mid" : ""}`,
      }),
    );
  });

  const divider = document.createElement("tr");
  divider.className = "mid-divider";
  divider.innerHTML = `
    <td colspan="6">
      <div class="mid-band">
        <span class="mid-band-label">Center</span>
        <span class="mid-band-price">${formatNumber(displayCenter)}</span>
      </div>
    </td>
  `;
  binanceBook.appendChild(divider);

  const bidRows = buildLadderRows((book.bids || []).slice(0, LADDER_LEVELS), myQuotes?.bid || null, "bid");
  while (bidRows.length < LADDER_LEVELS) {
    bidRows.push(blankRow());
  }
  bidRows.forEach((bid, index) => {
    binanceBook.appendChild(
      createLadderRow({
        myBidSize: bid.mySz,
        bidSize: bid.sz,
        bidPx: bid.px,
        askPx: null,
        askSize: null,
        myAskSize: null,
        quotedBid: bid.isQuoted,
        quotedAsk: false,
        rowClass: `ladder-row bid-row${index === 0 ? " near-mid" : ""}`,
      }),
    );
  });
}

function renderAccount(account) {
  pnlMark.textContent = formatNumber(account?.markPx);
  avgEntry.textContent = formatNumber(account?.averageEntryPx);
  positionQty.textContent = formatSignedSize(account?.positionQty);
  workingBidUsd.textContent = formatUsd(account?.workingBidUsd);
  workingAskUsd.textContent = formatUsd(account?.workingAskUsd);
  workingTotalUsd.textContent = formatUsd(account?.workingTotalUsd);

  setSignedValue(netPnl, account?.netUsd, formatSignedUsd);
  setSignedValue(realizedPnl, account?.realizedUsd, formatSignedUsd);
  setSignedValue(unrealizedPnl, account?.unrealizedUsd, formatSignedUsd);
  feesPaid.textContent = formatSignedUsd(-(account?.feesUsd ?? 0));
  feesPaid.className = `stat-value ${toneClass(-(account?.feesUsd ?? 0))}`;

  setSignedValue(netExposure, account?.exposureUsd, formatSignedUsd);
  grossExposure.textContent = formatUsd(account?.grossExposureUsd);

  const side = account?.positionSide || "flat";
  positionSide.textContent = capitalize(side);
  positionSide.className = `status-pill position-pill position-${side}`;
}

function renderControlPanel(schema, values, inputError) {
  if (!state.controls.initialized) {
    buildControlPanel(schema, values);
    state.controls.initialized = true;
  } else if (!state.controls.dirty && !controlPanelHasFocus()) {
    syncControlValues(values);
  }

  if (inputError) {
    controlsError.textContent = inputError;
    controlsError.classList.remove("hidden");
    state.controls.applying = false;
  } else {
    controlsError.textContent = "";
    controlsError.classList.add("hidden");
  }

  if (state.controls.applying && valuesMatchControls(values)) {
    state.controls.applying = false;
    state.controls.dirty = false;
  }

  if (state.controls.applying) {
    controlsStatus.textContent = "Applying inputs...";
  } else if (state.controls.dirty) {
    controlsStatus.textContent = "Unsaved changes";
  } else {
    controlsStatus.textContent = "Live config";
  }
}

function buildControlPanel(schema, values) {
  controlsGrid.innerHTML = "";
  const grouped = new Map();
  schema.forEach((item) => {
    if (!grouped.has(item.section)) {
      grouped.set(item.section, []);
    }
    grouped.get(item.section).push(item);
  });

  grouped.forEach((items, section) => {
    const group = document.createElement("section");
    group.className = "control-group";
    group.innerHTML = `<div class="control-group-head"><p class="venue-kicker">${section}</p></div>`;

    const body = document.createElement("div");
    body.className = "control-group-body";

    items.forEach((item) => {
      const field = document.createElement("label");
      field.className = "control-field";
      field.innerHTML = `
        <span class="control-label-row">
          <span class="control-label">${item.label}</span>
          <span class="control-unit">${item.unit || ""}</span>
        </span>
        <input
          class="control-input"
          data-key="${item.key}"
          type="${item.inputType || "number"}"
          step="${item.step || "1"}"
          ${item.min != null ? `min="${item.min}"` : ""}
        >
        <span class="control-help">${item.description || ""}</span>
      `;
      const input = field.querySelector("input");
      input.value = formatControlValue(values[item.key]);
      input.addEventListener("input", () => {
        state.controls.dirty = true;
        controlsStatus.textContent = "Unsaved changes";
      });
      body.appendChild(field);
    });

    group.appendChild(body);
    controlsGrid.appendChild(group);
  });
}

function syncControlValues(values) {
  controlsGrid.querySelectorAll("[data-key]").forEach((input) => {
    input.value = formatControlValue(values[input.dataset.key]);
  });
}

function collectControlValues() {
  const values = {};
  controlsGrid.querySelectorAll("[data-key]").forEach((input) => {
    values[input.dataset.key] = input.value;
  });
  return values;
}

function valuesMatchControls(values) {
  const current = collectControlValues();
  return Object.keys(values).every((key) => {
    const left = formatControlValue(values[key]);
    const right = current[key];
    if (left === "" || right === "") {
      return left === right;
    }
    return Number(left) === Number(right);
  });
}

function controlPanelHasFocus() {
  return controlsForm.contains(document.activeElement);
}

function formatControlValue(value) {
  return value == null ? "" : String(value);
}

function renderTrades(trades) {
  recentTrades.innerHTML = "";
  tradeCount.textContent = `${trades.length} prints`;

  if (trades.length === 0) {
    const row = document.createElement("tr");
    row.innerHTML = `<td colspan="4" class="empty-cell">Waiting for public trades...</td>`;
    recentTrades.appendChild(row);
    return;
  }

  trades.forEach((trade) => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${formatClock(trade.tsMs)}</td>
      <td class="${trade.side === "buy" ? "trade-buy" : "trade-sell"}">${trade.side.toUpperCase()}</td>
      <td>${formatNumber(trade.px)}</td>
      <td>${formatSize(trade.sz)}</td>
    `;
    recentTrades.appendChild(row);
  });
}

function renderPriceChart(points) {
  priceChart.setAttribute("viewBox", `0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`);
  if (!points || points.length === 0) {
    priceChart.innerHTML = `
      <text x="${CHART_WIDTH / 2}" y="${CHART_HEIGHT / 2}" text-anchor="middle" class="chart-empty">
        Waiting for price history...
      </text>
    `;
    chartLast.textContent = "--";
    chartHigh.textContent = "--";
    chartLow.textContent = "--";
    chartStart.textContent = "--";
    chartEnd.textContent = "--";
    return;
  }

  const firstTs = points[0].tsMs;
  const lastTs = points[points.length - 1].tsMs;
  const minPx = Math.min(...points.map((point) => point.px));
  const maxPx = Math.max(...points.map((point) => point.px));
  const priceRange = Math.max(maxPx - minPx, maxPx * 0.0005, 1e-9);
  const timeRange = Math.max(lastTs - firstTs, 1);
  const plotWidth = CHART_WIDTH - CHART_PADDING_X * 2;
  const plotHeight = CHART_HEIGHT - CHART_PADDING_Y * 2;

  const polyline = points.map((point) => {
    const x = CHART_PADDING_X + ((point.tsMs - firstTs) / timeRange) * plotWidth;
    const y = CHART_HEIGHT - CHART_PADDING_Y - ((point.px - minPx) / priceRange) * plotHeight;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(" ");

  const lastPoint = polyline.split(" ").at(-1) || `${CHART_WIDTH / 2},${CHART_HEIGHT / 2}`;
  const [lastX, lastY] = lastPoint.split(",");
  priceChart.innerHTML = `
    ${buildChartGrid()}
    <polyline class="chart-trace" points="${polyline}"></polyline>
    <circle class="chart-marker" cx="${lastX}" cy="${lastY}" r="4"></circle>
  `;

  chartLast.textContent = formatNumber(points[points.length - 1].px);
  chartHigh.textContent = formatNumber(maxPx);
  chartLow.textContent = formatNumber(minPx);
  chartStart.textContent = formatClock(firstTs);
  chartEnd.textContent = formatClock(lastTs);
}

function buildChartGrid() {
  const lines = [];
  const innerWidth = CHART_WIDTH - CHART_PADDING_X * 2;
  const innerHeight = CHART_HEIGHT - CHART_PADDING_Y * 2;

  for (let idx = 0; idx <= 4; idx += 1) {
    const y = CHART_PADDING_Y + (idx / 4) * innerHeight;
    lines.push(
      `<line class="chart-grid-line" x1="${CHART_PADDING_X}" y1="${y}" x2="${CHART_WIDTH - CHART_PADDING_X}" y2="${y}"></line>`,
    );
  }

  for (let idx = 0; idx <= 4; idx += 1) {
    const x = CHART_PADDING_X + (idx / 4) * innerWidth;
    lines.push(
      `<line class="chart-grid-line" x1="${x}" y1="${CHART_PADDING_Y}" x2="${x}" y2="${CHART_HEIGHT - CHART_PADDING_Y}"></line>`,
    );
  }

  return lines.join("");
}

function selectMarket(market) {
  if (!state.socket || state.socket.readyState !== WebSocket.OPEN) {
    return;
  }
  state.socket.send(JSON.stringify({ type: "select_market", market }));
}

marketForm.addEventListener("submit", (event) => {
  event.preventDefault();
  resetLadderCenter();
  selectMarket(marketInput.value);
});

applyInputsButton.addEventListener("click", () => {
  if (!state.socket || state.socket.readyState !== WebSocket.OPEN) {
    return;
  }
  state.controls.applying = true;
  state.controls.dirty = false;
  controlsStatus.textContent = "Applying inputs...";
  state.socket.send(JSON.stringify({ type: "update_inputs", values: collectControlValues() }));
});

function createLadderRow({
  myBidSize,
  bidSize,
  bidPx,
  askPx,
  askSize,
  myAskSize,
  quotedBid,
  quotedAsk,
  rowClass,
}) {
  const row = document.createElement("tr");
  row.className = rowClass;
  row.innerHTML = `
    <td class="mine bid${myBidSize != null ? " active-own" : ""}">${formatOwnSize(myBidSize)}</td>
    <td class="bid">${formatSize(bidSize)}</td>
    <td class="bid price-cell${quotedBid ? " quoted-price" : ""}">${formatNumber(bidPx)}</td>
    <td class="ask price-cell${quotedAsk ? " quoted-price" : ""}">${formatNumber(askPx)}</td>
    <td class="ask">${formatSize(askSize)}</td>
    <td class="mine ask${myAskSize != null ? " active-own" : ""}">${formatOwnSize(myAskSize)}</td>
  `;
  return row;
}

function buildLadderRows(levels, ownQuote, side) {
  const marketByPrice = new Map(
    levels.map((level) => [priceKey(level.px), { px: level.px, sz: level.sz }]),
  );
  const displayPrices = levels.map((level) => level.px).slice(0, LADDER_LEVELS);
  if (ownQuote && ownQuote.px != null && !displayPrices.some((px) => isSamePrice(px, ownQuote.px))) {
    if (displayPrices.length >= LADDER_LEVELS) {
      displayPrices[displayPrices.length - 1] = ownQuote.px;
    } else {
      displayPrices.push(ownQuote.px);
    }
  }

  const uniquePrices = [...new Map(displayPrices.map((px) => [priceKey(px), px])).values()];
  uniquePrices.sort((left, right) => (side === "ask" ? left - right : right - left));

  return uniquePrices.map((px) => {
    const marketLevel = marketByPrice.get(priceKey(px));
    const isQuoted = Boolean(ownQuote && isSamePrice(ownQuote.px, px));
    return {
      px,
      sz: marketLevel?.sz ?? null,
      mySz: isQuoted ? ownQuote.sz : null,
      isQuoted,
    };
  });
}

function blankRow() {
  return { px: null, sz: null, mySz: null, isQuoted: false };
}

function priceKey(value) {
  return Number(value).toFixed(8);
}

function isSamePrice(left, right) {
  return Math.abs(Number(left) - Number(right)) <= 1e-8;
}

function formatNumber(value) {
  if (value == null || Number.isNaN(value)) {
    return "--";
  }
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: value < 1 ? 4 : 2,
    maximumFractionDigits: value < 1 ? 6 : 2,
  });
}

function formatSize(value) {
  if (value == null || Number.isNaN(value)) {
    return "--";
  }
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 4,
  });
}

function formatOwnSize(value) {
  if (value == null || Number.isNaN(value)) {
    return "";
  }
  return formatSize(value);
}

function formatSignedSize(value) {
  if (value == null || Number.isNaN(value)) {
    return "--";
  }
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatSize(value)}`;
}

function formatMode(value) {
  if (!value || value === "idle") {
    return "Idle";
  }
  return value;
}

function formatSigned(value, digits) {
  if (value == null || Number.isNaN(value)) {
    return "--";
  }
  const sign = value > 0 ? "+" : "";
  return `${sign}${Number(value).toFixed(digits)}`;
}

function formatUsd(value) {
  if (value == null || Number.isNaN(value)) {
    return "--";
  }
  return Number(value).toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatSignedUsd(value) {
  if (value == null || Number.isNaN(value)) {
    return "--";
  }
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatUsd(value)}`;
}

function setSignedValue(element, value, formatter) {
  element.textContent = formatter(value);
  const baseClass = element.className.split(" ").filter((name) => !name.startsWith("metric-"))[0];
  element.className = `${baseClass} ${toneClass(value)}`;
}

function toneClass(value) {
  if (value > 1e-9) {
    return "metric-positive";
  }
  if (value < -1e-9) {
    return "metric-negative";
  }
  return "metric-neutral";
}

function formatTime(value) {
  if (!value) {
    return "Waiting...";
  }
  return new Date(value).toLocaleTimeString();
}

function formatClock(value) {
  if (!value) {
    return "--";
  }
  return new Date(value).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatAge(value) {
  const ageMs = Date.now() - value;
  if (ageMs < 1000) {
    return `${ageMs} ms`;
  }
  return `${(ageMs / 1000).toFixed(1)} s`;
}

function capitalize(value) {
  return value ? value.charAt(0).toUpperCase() + value.slice(1) : "";
}

function resetLadderCenter() {
  state.ladder = { centerPx: null, centeredAtMs: 0, symbol: null };
}

function updateLadderCenter(symbol, book) {
  if (state.ladder.symbol !== symbol) {
    resetLadderCenter();
    state.ladder.symbol = symbol;
  }

  const midPx = book.midPx;
  if (midPx == null || Number.isNaN(midPx)) {
    return state.ladder.centerPx;
  }

  const nowMs = Date.now();
  if (state.ladder.centerPx == null) {
    state.ladder.centerPx = midPx;
    state.ladder.centeredAtMs = nowMs;
    return state.ladder.centerPx;
  }

  const moveBps = Math.abs(midPx - state.ladder.centerPx) / Math.max(midPx, 1e-9) * 1e4;
  const timeSinceCenterMs = nowMs - state.ladder.centeredAtMs;
  if (moveBps >= 1.5 || (moveBps >= 0.4 && timeSinceCenterMs >= 5000)) {
    state.ladder.centerPx = midPx;
    state.ladder.centeredAtMs = nowMs;
  }

  return state.ladder.centerPx;
}

window.setInterval(() => {
  if (state.latest) {
    const book = state.latest.book;
    binanceAge.textContent = book.recvTsMs ? formatAge(book.recvTsMs) : "--";
    updatedAt.textContent = formatTime(state.latest.updatedAtMs);
  }
}, 250);

connect();
