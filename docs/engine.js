// docs/engine.js
// When the page is served by your local FastAPI (port 8000), call the same server.
// Otherwise (GitHub Pages) call the tunnel.
const IS_LOCAL_SERVER =
  ["127.0.0.1", "localhost"].includes(location.hostname) && location.port === "8000";
const API = IS_LOCAL_SERVER ? "" : "https://advertise-word-genre-channels.trycloudflare.com";

const HEADERS = { "x-api-key": "marg-test-key-123" };   // must match ENGINE_API_KEY in .env

const btn = document.getElementById("runEngineBtn");
const statusEl = document.getElementById("engineStatus");
const table = document.getElementById("rankingTable");
const tbody = table.querySelector("tbody");
const emptyMsg = document.getElementById("emptyMsg");

function resetView() {
  tbody.innerHTML = "";
  table.style.display = "none";
  emptyMsg.style.display = "block";
}

btn.addEventListener("click", async () => {
  btn.disabled = true;
  resetView();                                  // clear any old list first
  statusEl.textContent = "Starting engine...";
  try {
    const res = await fetch(`${API}/engine/run`, { method: "POST", headers: HEADERS });
    if (res.status === 409) {
      statusEl.textContent = "Engine is already running. Try again shortly.";
      return;
    }
    if (!res.ok) throw new Error("Could not start engine (HTTP " + res.status + ")");
    const data = await res.json();
    await pollStatus(data.run_id);
  } catch (err) {
    statusEl.textContent = "Error: " + err.message;
  } finally {
    btn.disabled = false;
  }
});

async function pollStatus(runId) {
  statusEl.textContent = "Engine running...";
  while (true) {
    await new Promise((r) => setTimeout(r, 2000));
    const res = await fetch(`${API}/engine/status/${runId}`, { headers: HEADERS });
    const data = await res.json();
    if (data.status === "done") {
      statusEl.textContent = "Done: " + data.message;
      await loadRanking();
      return;
    }
    if (data.status === "failed") {
      statusEl.textContent = "Failed: " + data.message;
      return;
    }
  }
}

function cell(text) {
  const td = document.createElement("td");
  td.textContent = text ?? "";
  return td;
}

async function loadRanking() {
  const res = await fetch(`${API}/engine/ranking`, { headers: HEADERS });
  if (!res.ok) { statusEl.textContent = "Could not load the ranking."; return; }
  const rows = await res.json();
  tbody.innerHTML = "";
  rows.forEach((r) => {
    const tr = document.createElement("tr");
    tr.appendChild(cell(r.rank));
    tr.appendChild(cell(r.block_id));
    tr.appendChild(cell(r.department));
    tr.appendChild(cell(r.reason));
    tr.appendChild(cell(r.requested_date));
    tr.appendChild(cell(Number(r.topsis_score).toFixed(4)));
    tbody.appendChild(tr);
  });
  if (rows.length > 0) {
    emptyMsg.style.display = "none";
    table.style.display = "table";
  }
}
// No call to loadRanking() here: nothing is shown until Run Engine is clicked.