const HISTORY_LENGTH = 30;
const REFRESH_MS = 10000;

const targetsEl = document.getElementById("targets");
const summaryEl = document.getElementById("summary");
const emptyEl = document.getElementById("empty");
const updatedEl = document.getElementById("updated");
const formEl = document.getElementById("add-form");
const errorEl = document.getElementById("form-error");

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function stat(label, value) {
  const span = el("span");
  span.append(label + " ", el("b", "", value));
  return span;
}

function renderBars(history) {
  const bars = el("div", "bars");
  const slowest = Math.max(1, ...history.map((check) => check.ms || 0));

  for (let i = history.length; i < HISTORY_LENGTH; i++) bars.append(el("div", "bar empty"));

  for (const check of history) {
    const bar = el("div", check.ok ? "bar" : "bar down");
    bar.style.height = Math.max(18, Math.round(100 * (check.ms || 0) / slowest)) + "%";
    bar.title = new Date(check.at).toLocaleTimeString() + " · " + (check.ok ? check.ms + " ms" : "down");
    bars.append(bar);
  }
  return bars;
}

function renderTarget(target) {
  const card = el("div", "target");

  const head = el("div", "target-head");
  const remove = el("button", "remove", "×");
  remove.title = "Stop monitoring";
  remove.addEventListener("click", async () => {
    await fetch("/api/targets/" + target.id, { method: "DELETE" });
    refresh();
  });
  head.append(el("span", "dot " + target.status), el("span", "target-name", target.name),
              el("span", "target-url", target.url), remove);

  const stats = el("div", "stats");
  stats.append(
    stat("Status", target.status.toUpperCase()),
    stat("Uptime 24h", target.uptime_24h === null ? "–" : target.uptime_24h + "%"),
    stat("Response", target.last_response_ms === null ? "–" : target.last_response_ms + " ms"),
    stat("Average", target.avg_response_ms === null ? "–" : target.avg_response_ms + " ms")
  );
  if (target.last_error) stats.append(stat("Error", target.last_error));

  card.append(head, renderBars(target.history), stats);
  return card;
}

function renderSummary(targets) {
  const down = targets.filter((target) => target.status === "down").length;
  if (targets.length === 0) {
    summaryEl.textContent = "Nothing monitored";
    summaryEl.className = "summary";
  } else if (down === 0) {
    summaryEl.textContent = "All systems operational";
    summaryEl.className = "summary ok";
  } else {
    summaryEl.textContent = down + " of " + targets.length + " down";
    summaryEl.className = "summary bad";
  }
}

async function refresh() {
  try {
    const targets = await (await fetch("/api/targets")).json();
    targetsEl.replaceChildren(...targets.map(renderTarget));
    emptyEl.hidden = targets.length > 0;
    renderSummary(targets);
    updatedEl.textContent = "updated " + new Date().toLocaleTimeString();
  } catch (error) {
    summaryEl.textContent = "API unreachable";
    summaryEl.className = "summary bad";
  }
}

formEl.addEventListener("submit", async (event) => {
  event.preventDefault();
  errorEl.textContent = "";
  const body = { name: formEl.elements.name.value, url: formEl.elements.url.value };
  const response = await fetch("/api/targets", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    errorEl.textContent = (await response.json()).error;
    return;
  }
  formEl.reset();
  await fetch("/api/check", { method: "POST" });
  refresh();
});

document.getElementById("check-now").addEventListener("click", async () => {
  await fetch("/api/check", { method: "POST" });
  refresh();
});

refresh();
setInterval(refresh, REFRESH_MS);
