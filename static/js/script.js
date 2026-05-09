async function api(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error || `Request failed (${response.status})`);
  }
  const ct = response.headers.get("content-type") || "";
  if (ct.includes("application/json")) {
    return response.json();
  }
  return response.blob();
}

function simulationId() {
  return Number(document.getElementById("simulation-id").value);
}

function setStatus(message, kind = "info") {
  const box = document.getElementById("status-box");
  box.className = `alert alert-${kind}`;
  box.textContent = message;
}

function updateMetrics(sim) {
  const metrics = sim.metrics || {};
  const body = document.getElementById("metrics-body");
  body.innerHTML = `
    <tr><th>MSE</th><td>${metrics.mse ?? "-"}</td></tr>
    <tr><th>PSNR</th><td>${metrics.psnr ?? "-"}</td></tr>
    <tr><th>SSIM</th><td>${metrics.ssim ?? "-"}</td></tr>
    <tr><th>Q Index</th><td>${metrics.q_index ?? "-"}</td></tr>
    <tr><th>Embedding Time (ms)</th><td>${sim.embedding_time_ms ?? "-"}</td></tr>
    <tr><th>Extraction Accuracy (%)</th><td>${sim.extraction_accuracy ?? "-"}</td></tr>
  `;
}

function updateGraphs(graphs = {}) {
  const container = document.getElementById("graph-links");
  const entries = Object.entries(graphs);
  if (!entries.length) {
    container.innerHTML = "No graphs generated yet.";
    return;
  }
  container.innerHTML = entries
    .map(([k, v]) => {
      const file = String(v).split("/").pop();
      if (!/^[A-Za-z0-9_.-]+$/.test(file) || file.includes("..")) {
        return "";
      }
      return `<a class="graph-link" href="/results/${encodeURIComponent(file)}" target="_blank">${k}</a>`;
    })
    .join("");
}

function toggleSimulationActions(isLocked) {
  ["upload-btn", "encode-btn", "decode-btn", "graph-btn", "blackbox-btn", "whitebox-btn"].forEach((id) => {
    document.getElementById(id).disabled = Boolean(isLocked);
  });
}

async function loadSimulations() {
  const data = await api("/api/simulations");
  const root = document.getElementById("simulation-cards");
  root.innerHTML = data.simulations
    .map((sim) => {
      const locked = sim.locked ? "locked" : "";
      const status = sim.status || "pending";
      const lockText = sim.locked ? "Locked" : "Open";
      return `
      <div class="col-md-6">
        <div class="card simulation-card ${locked}">
          <div class="card-body">
            <h6>Simulation ${sim.id}</h6>
            <div>Status: <span class="badge bg-secondary">${status}</span></div>
            <div>State: ${lockText}</div>
          </div>
        </div>
      </div>`;
    })
    .join("");
}

async function refreshSimulationDetails() {
  const sim = await api(`/api/simulation/${simulationId()}`);
  updateMetrics(sim);
  updateGraphs(sim.graphs || {});
  toggleSimulationActions(sim.locked);
}

document.getElementById("upload-btn").addEventListener("click", async () => {
  try {
    const fileInput = document.getElementById("cover-image");
    if (!fileInput.files.length) {
      throw new Error("Choose an image first");
    }
    const formData = new FormData();
    formData.append("image", fileInput.files[0]);
    formData.append("simulation_id", simulationId());
    await api("/api/upload-image", { method: "POST", body: formData });
    setStatus("Image uploaded", "success");
    await loadSimulations();
    await refreshSimulationDetails();
  } catch (error) {
    setStatus(error.message, "danger");
  }
});

document.getElementById("encode-btn").addEventListener("click", async () => {
  try {
    const payload_size_kb = Number(document.getElementById("payload-size").value);
    const secret_message = document.getElementById("secret-message").value;
    await api("/api/encode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ simulation_id: simulationId(), payload_size_kb, secret_message }),
    });
    setStatus("Encoding completed and metrics computed", "success");
    await loadSimulations();
    await refreshSimulationDetails();
  } catch (error) {
    setStatus(error.message, "danger");
  }
});

document.getElementById("decode-btn").addEventListener("click", async () => {
  try {
    await api("/api/decode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ simulation_id: simulationId() }),
    });
    setStatus("Decoding completed", "success");
    await loadSimulations();
    await refreshSimulationDetails();
  } catch (error) {
    setStatus(error.message, "danger");
  }
});

document.getElementById("graph-btn").addEventListener("click", async () => {
  try {
    await api(`/api/generate-graphs/${simulationId()}`, { method: "POST" });
    setStatus("Graphs generated", "success");
    await refreshSimulationDetails();
  } catch (error) {
    setStatus(error.message, "danger");
  }
});

document.getElementById("lock-btn").addEventListener("click", async () => {
  try {
    await api(`/api/lock-simulation/${simulationId()}`, { method: "POST" });
    setStatus("Simulation locked", "warning");
    await loadSimulations();
    await refreshSimulationDetails();
  } catch (error) {
    setStatus(error.message, "danger");
  }
});

document.getElementById("blackbox-btn").addEventListener("click", async () => {
  try {
    await api(`/api/testing/blackbox/${simulationId()}`, { method: "POST" });
    setStatus("Black-box test executed", "success");
    await refreshSimulationDetails();
  } catch (error) {
    setStatus(error.message, "danger");
  }
});

document.getElementById("whitebox-btn").addEventListener("click", async () => {
  try {
    await api(`/api/testing/whitebox/${simulationId()}`, { method: "POST" });
    setStatus("White-box test executed", "success");
    await refreshSimulationDetails();
  } catch (error) {
    setStatus(error.message, "danger");
  }
});

document.getElementById("export-btn").addEventListener("click", async () => {
  try {
    const response = await fetch(`/api/export-results/${simulationId()}`, { method: "POST" });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || "Export failed");
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `simulation_${simulationId()}_evidence.json`;
    a.click();
    URL.revokeObjectURL(url);
    setStatus("Results exported", "success");
  } catch (error) {
    setStatus(error.message, "danger");
  }
});

document.getElementById("simulation-id").addEventListener("change", async () => {
  try {
    await refreshSimulationDetails();
  } catch (error) {
    setStatus(error.message, "danger");
  }
});

loadSimulations().then(refreshSimulationDetails).catch((e) => setStatus(e.message, "danger"));
