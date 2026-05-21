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

const SIMULATION_ID = 1;
let currentSimulation = null;
let preprocessTimer = null;

function el(id) {
  return document.getElementById(id);
}

function setStatus(message, kind = "info") {
  const box = el("status-box");
  box.className = `alert alert-${kind}`;
  box.textContent = message;
}

function wordCount(text) {
  const value = String(text || "").trim();
  return value ? value.split(/\s+/).length : 0;
}

function characterCount(text) {
  return Array.from(String(text || "")).length;
}

function thresholdValue(id) {
  return Number(el(id).value) / 100;
}

function getPayloadPercentage() {
  return Number(el("payload-size").value || 0);
}

function getBitDepth() {
  return Number(el("bit-depth").value || 3);
}

function currentDimensionPixels(sim) {
  const dimensions = sim?.dimensions || [];
  if (!Array.isArray(dimensions) || dimensions.length < 2) {
    return 0;
  }
  return Number(dimensions[0]) * Number(dimensions[1]);
}

function updateThresholdLabels() {
  el("edge-low-value").textContent = thresholdValue("edge-threshold-low").toFixed(2);
  el("edge-high-value").textContent = thresholdValue("edge-threshold-high").toFixed(2);
}

function updateCapacityDisplay() {
  const bitLimitDisplay = el("capacity-summary");
  const messageCounter = el("secret-message-counter");
  const currentCharacters = characterCount(el("secret-message").value);
  const totalPixels = currentDimensionPixels(currentSimulation);
  const payloadPercentage = getPayloadPercentage();
  const bitLimit = totalPixels > 0 ? Math.floor((totalPixels * payloadPercentage) / 100) : 0;
  const wordLimit = bitLimit > 0 ? Math.floor(bitLimit / 8) : 0;

  if (wordLimit > 0) {
    messageCounter.textContent = `${currentCharacters}/${wordLimit}`;
  } else {
    messageCounter.textContent = `${currentCharacters}/-`;
  }

  bitLimitDisplay.textContent = `Bit limit: ${bitLimit.toLocaleString()} | Word limit: ${wordLimit.toLocaleString()}`;
}

function formatMetric(value, digits = 6) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return value.toFixed(digits).replace(/\.0+$/, "");
  }
  return String(value);
}

function resultFileFromPath(pathValue) {
  const raw = String(pathValue || "");
  if (!raw) {
    return "";
  }
  return raw.split(/[\\/]/).pop() || "";
}

function imageUrlFromPath(pathValue, baseRoute) {
  const file = resultFileFromPath(pathValue);
  if (!file || !/^[A-Za-z0-9_.-]+$/.test(file) || file.includes("..")) {
    return "";
  }
  return `${baseRoute}/${encodeURIComponent(file)}`;
}

function setPreviewImage(imgId, emptyId, url) {
  const image = el(imgId);
  const empty = el(emptyId);
  if (url) {
    image.src = `${url}?t=${Date.now()}`;
    image.classList.remove("d-none");
    empty.classList.add("d-none");
  } else {
    image.removeAttribute("src");
    image.classList.add("d-none");
    empty.classList.remove("d-none");
  }
}

function renderSimulation(sim) {
  currentSimulation = sim;
  setPreviewImage("original-image-preview", "original-image-empty", imageUrlFromPath(sim?.image_path, "/uploads"));
  setPreviewImage("edge-image-preview", "edge-image-empty", imageUrlFromPath(sim?.edge_map_path, "/results"));
  setPreviewImage("stego-image-preview", "stego-image-empty", imageUrlFromPath(sim?.stego_image_path, "/results"));
  setPreviewImage("difference-image-preview", "difference-image-empty", imageUrlFromPath(sim?.difference_image_path, "/results"));
  updateCapacityDisplay();

  el("metric-edge-pixels").textContent = formatMetric(sim?.edge_pixel_count, 0);
  el("metric-max-words").textContent = formatMetric(sim?.max_possible_word_count, 0);
  el("metric-embedded-words").textContent = formatMetric(sim?.actual_embedded_word_count ?? sim?.embedded_words, 0);
  el("metric-psnr").textContent = formatMetric(sim?.psnr);
  el("metric-ssim").textContent = formatMetric(sim?.ssim);
  el("metric-chi-square").textContent = formatMetric(sim?.chi_square);

  if (!sim?.extracted_message) {
    el("decoded-message").value = "";
  } else {
    el("decoded-message").value = sim.extracted_message;
  }
  setPreviewImage("restored-image-preview", "restored-image-empty", imageUrlFromPath(sim?.image_path, "/uploads"));
}

function renderMatrixReport(report) {
  el("matrix-summary").textContent = report?.summary || "Run matrix analysis to generate a recommendation.";

  const runs = Array.isArray(report?.runs) ? report.runs : [];
  const body = el("matrix-results-body");
  if (!runs.length) {
    body.innerHTML = '<tr><td colspan="6" class="text-muted">No matrix analysis runs yet.</td></tr>';
    return;
  }

  body.innerHTML = runs
    .map(
      (run) => `
        <tr>
          <td>${run.image ?? "-"}</td>
          <td>${run.payload_percentage ?? "-"}</td>
          <td>${run.bit_depth ?? "-"}</td>
          <td>${formatMetric(run.psnr)}</td>
          <td>${formatMetric(run.ssim)}</td>
          <td>${formatMetric(run.chi_square)}</td>
        </tr>`,
    )
    .join("");
}

async function loadSimulation() {
  const sim = await api(`/api/simulation/${SIMULATION_ID}`);
  renderSimulation(sim);
}

async function loadPayloadFile() {
  const fileInput = el("payload-file");
  if (!fileInput.files.length) {
    return;
  }
  const text = await fileInput.files[0].text();
  el("secret-message").value = text;
  updateCapacityDisplay();
}

function schedulePreprocess() {
  if (!currentSimulation || !currentSimulation.image_path) {
    return;
  }
  window.clearTimeout(preprocessTimer);
  preprocessTimer = window.setTimeout(() => {
    runPreprocess().catch((error) => setStatus(error.message, "danger"));
  }, 250);
}

async function runPreprocess() {
  if (!currentSimulation || !currentSimulation.image_path) {
    throw new Error("Upload a cover image first");
  }
  const response = await api("/api/preprocess", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      simulation_id: SIMULATION_ID,
      edge_threshold_low: thresholdValue("edge-threshold-low"),
      edge_threshold_high: thresholdValue("edge-threshold-high"),
      bit_depth: getBitDepth(),
    }),
  });
  renderSimulation(response.simulation);
  setStatus("Preprocessing completed", "success");
}

async function runSimulation() {
  const response = await api("/api/run-simulation", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      simulation_id: SIMULATION_ID,
      payload_percentage: getPayloadPercentage(),
      secret_message: el("secret-message").value,
      edge_threshold_low: thresholdValue("edge-threshold-low"),
      edge_threshold_high: thresholdValue("edge-threshold-high"),
      bit_depth: getBitDepth(),
    }),
  });
  renderSimulation(response.simulation);
  setStatus("Simulation completed", "success");
}

async function runDecode() {
  if (!currentSimulation || !currentSimulation.stego_image_path) {
    throw new Error("Run the simulation first");
  }

  const response = await api("/api/decode-simulation", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      simulation_id: SIMULATION_ID,
      edge_threshold_low: thresholdValue("edge-threshold-low"),
      edge_threshold_high: thresholdValue("edge-threshold-high"),
      bit_depth: getBitDepth(),
    }),
  });

  renderSimulation(response.simulation);
  el("decoded-message").value = response.extracted_message || "";
  setPreviewImage("restored-image-preview", "restored-image-empty", imageUrlFromPath(response.restored_image_path, "/uploads"));
  setStatus("Decoding completed", "success");
}

async function runMatrixAnalysis() {
  const benchmarkInput = el("benchmark-images");
  if (!benchmarkInput.files.length) {
    throw new Error("Upload one or more benchmark images");
  }

  const formData = new FormData();
  for (const file of benchmarkInput.files) {
    formData.append("benchmarks", file);
  }
  formData.append("payload_text", el("matrix-payload-text").value || el("secret-message").value);
  formData.append("payload_options", el("matrix-payload-options").value || "10,25,50,75,100");
  formData.append("edge_threshold_low", String(thresholdValue("edge-threshold-low")));
  formData.append("edge_threshold_high", String(thresholdValue("edge-threshold-high")));
  formData.append("bit_depth", String(getBitDepth()));

  const report = await api("/api/matrix-analysis", { method: "POST", body: formData });
  renderMatrixReport(report);
  setStatus("Matrix analysis completed", "success");
}

el("upload-btn").addEventListener("click", async () => {
  try {
    const fileInput = el("cover-image");
    if (!fileInput.files.length) {
      throw new Error("Choose an image first");
    }
    const formData = new FormData();
    formData.append("image", fileInput.files[0]);
    formData.append("simulation_id", SIMULATION_ID);
    formData.append("edge_threshold_low", String(thresholdValue("edge-threshold-low")));
    formData.append("edge_threshold_high", String(thresholdValue("edge-threshold-high")));
    formData.append("bit_depth", String(getBitDepth()));
    const response = await api("/api/upload-image", { method: "POST", body: formData });
    renderSimulation(response.simulation);
    setStatus("Image uploaded", "success");
  } catch (error) {
    setStatus(error.message, "danger");
  }
});

el("preprocess-btn").addEventListener("click", async () => {
  try {
    await runPreprocess();
  } catch (error) {
    setStatus(error.message, "danger");
  }
});

el("run-btn").addEventListener("click", async () => {
  try {
    await runSimulation();
  } catch (error) {
    setStatus(error.message, "danger");
  }
});

el("decode-btn").addEventListener("click", async () => {
  try {
    await runDecode();
  } catch (error) {
    setStatus(error.message, "danger");
  }
});

el("matrix-run-btn").addEventListener("click", async () => {
  try {
    await runMatrixAnalysis();
  } catch (error) {
    setStatus(error.message, "danger");
  }
});

el("payload-file").addEventListener("change", async () => {
  try {
    await loadPayloadFile();
    setStatus("Payload text loaded", "success");
  } catch (error) {
    setStatus(error.message, "danger");
  }
});

el("payload-size").addEventListener("change", updateCapacityDisplay);
el("secret-message").addEventListener("input", updateCapacityDisplay);
el("edge-threshold-low").addEventListener("input", () => {
  updateThresholdLabels();
  schedulePreprocess();
});
el("edge-threshold-high").addEventListener("input", () => {
  updateThresholdLabels();
  schedulePreprocess();
});
el("bit-depth").addEventListener("change", () => {
  updateCapacityDisplay();
  schedulePreprocess();
});

updateThresholdLabels();
updateCapacityDisplay();
loadSimulation().catch((error) => setStatus(error.message, "danger"));
