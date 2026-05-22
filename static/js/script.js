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

const imageDownloadMap = {
  "download-original-btn": { route: "/uploads", path: () => currentSimulation?.image_path, filename: "original_image" },
  "download-edge-btn": { route: "/results", path: () => currentSimulation?.edge_map_path, filename: "edge_map" },
  "download-stego-btn": { route: "/results", path: () => currentSimulation?.stego_image_path, filename: "stego_image" },
  "download-difference-btn": { route: "/results", path: () => currentSimulation?.difference_image_path, filename: "difference_image" },
};

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
  const adaptiveBytes = Number(currentSimulation?.capacity_bytes ?? currentSimulation?.adaptive_capacity_bytes ?? 0);
  const characterLimit = adaptiveBytes > 0 ? adaptiveBytes : 0;

  if (characterLimit > 0) {
    messageCounter.textContent = `${currentCharacters}/${characterLimit}`;
  } else {
    messageCounter.textContent = `${currentCharacters}/-`;
  }

  bitLimitDisplay.textContent = characterLimit > 0
    ? `Adaptive capacity: ${adaptiveBytes.toLocaleString()} bytes | Approx character limit: ${characterLimit.toLocaleString()}`
    : `Adaptive capacity: pending preprocess | Approx character limit: -`;
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

function triggerDownload(blob, filename) {
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

async function downloadImageByPath(pathValue, route, filename) {
  const url = imageUrlFromPath(pathValue, route);
  if (!url) {
    throw new Error("Image is not available for download");
  }
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error("Unable to download image");
  }
  const blob = await response.blob();
  triggerDownload(blob, `${filename}.png`);
}

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = reject;
    image.src = `${url}?t=${Date.now()}`;
  });
}

async function generateBinaryDataUrlFromUrl(url, threshold = 128) {
  // load image (supports data URLs too)
  const img = await new Promise((resolve, reject) => {
    const image = new Image();
    image.crossOrigin = "anonymous";
    image.onload = () => resolve(image);
    image.onerror = reject;
    image.src = url;
  });
  const canvas = document.createElement("canvas");
  canvas.width = img.naturalWidth;
  canvas.height = img.naturalHeight;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(img, 0, 0);
  const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const data = imageData.data;
  for (let i = 0; i < data.length; i += 4) {
    // luminance
    const lum = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
    const bit = lum >= threshold ? 255 : 0;
    data[i] = data[i + 1] = data[i + 2] = bit;
    // keep alpha
  }
  ctx.putImageData(imageData, 0, 0);
  return canvas.toDataURL("image/png");
}

async function downloadCollage() {
  const originals = [
    { path: currentSimulation?.image_path, route: "/uploads", label: "Original" },
    { path: currentSimulation?.edge_map_path, route: "/results", label: "Edge" },
    { path: currentSimulation?.stego_image_path, route: "/results", label: "Stego" },
    { path: currentSimulation?.difference_image_path, route: "/results", label: "Difference" },
  ];
  const resolved = originals
    .map((item) => ({ ...item, url: imageUrlFromPath(item.path, item.route) }))
    .filter((item) => item.url);
  if (!resolved.length) {
    throw new Error("No images available for collage download");
  }

  const loaded = await Promise.all(resolved.map(async (item) => ({ ...item, image: await loadImage(item.url) })));
  const tileWidth = Math.max(...loaded.map((item) => item.image.naturalWidth));
  const tileHeight = Math.max(...loaded.map((item) => item.image.naturalHeight));
  const canvas = document.createElement("canvas");
  canvas.width = tileWidth * 2;
  canvas.height = tileHeight * 2;
  const context = canvas.getContext("2d");

  loaded.forEach((item, index) => {
    const x = (index % 2) * tileWidth;
    const y = Math.floor(index / 2) * tileHeight;
    context.fillStyle = "#ffffff";
    context.fillRect(x, y, tileWidth, tileHeight);
    context.drawImage(item.image, x, y, tileWidth, tileHeight);
    context.fillStyle = "rgba(0,0,0,0.6)";
    context.fillRect(x, y + tileHeight - 28, tileWidth, 28);
    context.fillStyle = "#ffffff";
    context.font = "16px sans-serif";
    context.fillText(item.label, x + 10, y + tileHeight - 9);
  });

  const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
  if (!blob) {
    throw new Error("Unable to generate collage image");
  }
  triggerDownload(blob, "image_collage.png");
}

function toggleDecodeMode() {
  const uploadPanel = el("decode-upload-panel");
  if (!uploadPanel) {
    return;
  }
  uploadPanel.classList.toggle("d-none", el("decode-source").value !== "upload");
}

function renderSimulation(sim) {
  currentSimulation = sim;
  setPreviewImage("original-image-preview", "original-image-empty", imageUrlFromPath(sim?.image_path, "/uploads"));
  setPreviewImage("edge-image-preview", "edge-image-empty", imageUrlFromPath(sim?.edge_map_path, "/results"));
  setPreviewImage("stego-image-preview", "stego-image-empty", imageUrlFromPath(sim?.stego_image_path, "/results"));
  setPreviewImage("difference-image-preview", "difference-image-empty", imageUrlFromPath(sim?.difference_image_path, "/results"));
  updateBinaryPreview();
  updateCapacityDisplay();

  el("metric-edge-pixels").textContent = formatMetric(sim?.edge_pixel_count, 0);
  el("metric-max-words").textContent = formatMetric(sim?.max_possible_word_count, 0);
  el("metric-embedded-words").textContent = formatMetric(sim?.actual_embedded_word_count ?? sim?.embedded_words, 0);
  el("metric-psnr").textContent = formatMetric(sim?.psnr);
  el("metric-ssim").textContent = formatMetric(sim?.ssim);
  el("metric-qindex").textContent = formatMetric(sim?.q_index ?? sim?.qindex ?? sim?.qIndex);
  el("metric-mse").textContent = formatMetric(sim?.mse);
  el("metric-chi-square").textContent = formatMetric(sim?.chi_square);

  if (sim?.status !== "decoded" || !sim?.extracted_message) {
    el("decoded-message").value = "";
    setPreviewImage("restored-image-preview", "restored-image-empty", "");
  } else {
    el("decoded-message").value = sim.extracted_message;
    setPreviewImage("restored-image-preview", "restored-image-empty", imageUrlFromPath(sim?.image_path, "/uploads"));
  }
  // Explanations for interpretation (static guidance)
  const explainPSNR = "Higher PSNR (dB) indicates closer visual similarity; >40 dB is typically imperceptible.";
  const explainSSIM = "SSIM (−1..1): values near 1 indicate high perceived structural similarity.";
  const explainQ = "Q Index (−1..1): values near 1 denote strong overall image quality agreement.";
  const explainMSE = "MSE: mean squared error; lower is better (0 means identical images).";
  const explainChi = "Chi-Square (LSB): lower values imply less detectable LSB alterations; higher may indicate manipulation.";
  const setText = (id, text) => { const node = el(id); if (node) node.textContent = text; };
  setText("explain-psnr", explainPSNR);
  setText("explain-ssim", explainSSIM);
  setText("explain-qindex", explainQ);
  setText("explain-mse", explainMSE);
  setText("explain-chi-square", explainChi);
}

async function updateBinaryPreview() {
  const preview = el("stego-binary-image-preview");
  const empty = el("stego-binary-image-empty");
  const stegoPath = currentSimulation?.stego_image_path;
  if (!stegoPath) {
    if (preview) { preview.removeAttribute("src"); preview.classList.add("d-none"); }
    if (empty) { empty.classList.remove("d-none"); }
    return;
  }
  const url = imageUrlFromPath(stegoPath, "/results");
  if (!url) {
    if (preview) { preview.removeAttribute("src"); preview.classList.add("d-none"); }
    if (empty) { empty.classList.remove("d-none"); }
    return;
  }
  try {
    const dataUrl = await generateBinaryDataUrlFromUrl(url);
    if (preview) { preview.src = dataUrl; preview.classList.remove("d-none"); }
    if (empty) { empty.classList.add("d-none"); }
  } catch (err) {
    if (preview) { preview.removeAttribute("src"); preview.classList.add("d-none"); }
    if (empty) { empty.classList.remove("d-none"); }
  }
}

function renderDecodedResult(message, restoredPath) {
  el("decoded-message").value = message || "";
  setPreviewImage("restored-image-preview", "restored-image-empty", restoredPath ? imageUrlFromPath(restoredPath, "/uploads") : "");
}

function renderDecodeFailure(error) {
  const message = error instanceof Error ? error.message : String(error || "Decoding failed");
  renderDecodedResult(`Decoding failed: ${message}`, null);
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
  const originals = [
    { path: currentSimulation?.image_path, route: "/uploads", label: "Original" },
    { path: currentSimulation?.edge_map_path, route: "/results", label: "Edge" },
    { path: currentSimulation?.stego_image_path, route: "/results", label: "Stego" },
    // stego binary will be generated as a data URL
    { path: currentSimulation?.stego_image_path, route: "/results", label: "Stego Binary", binary: true },
    { path: currentSimulation?.difference_image_path, route: "/results", label: "Difference" },
  ];
  updateCapacityDisplay();
    .map((item) => ({ ...item, url: imageUrlFromPath(item.path, item.route) }))
    .filter((item) => item.url || item.binary);
function schedulePreprocess() {
  if (!currentSimulation || !currentSimulation.image_path) {
    return;
  const loaded = [];
  for (const item of resolved) {
    if (item.binary) {
      // generate binary data URL from stego
      try {
        const binaryUrl = await generateBinaryDataUrlFromUrl(item.url);
        const img = await loadImage(binaryUrl);
        loaded.push({ ...item, image: img });
      } catch (err) {
        // skip binary if generation fails
      }
    } else {
      try {
        const img = await loadImage(item.url);
        loaded.push({ ...item, image: img });
      } catch (err) {
        // skip failed images
      }
    }
  }
  preprocessTimer = window.setTimeout(() => {
    runPreprocess().catch((error) => setStatus(error.message, "danger"));
  // arrange in 3 columns x 2 rows to fit five images
  const cols = 3;
  const rows = 2;
  const canvas = document.createElement("canvas");
  canvas.width = tileWidth * cols;
  canvas.height = tileHeight * rows;
  const context = canvas.getContext("2d");

  loaded.forEach((item, index) => {
    const x = (index % cols) * tileWidth;
    const y = Math.floor(index / cols) * tileHeight;
    context.fillStyle = "#ffffff";
    context.fillRect(x, y, tileWidth, tileHeight);
    context.drawImage(item.image, x, y, tileWidth, tileHeight);
    context.fillStyle = "rgba(0,0,0,0.6)";
    context.fillRect(x, y + tileHeight - 28, tileWidth, 28);
    context.fillStyle = "#ffffff";
    context.font = "16px sans-serif";
    context.fillText(item.label, x + 10, y + tileHeight - 9);
  });
  renderSimulation(response.simulation);
  setStatus("Preprocessing completed", "success");
}

async function runSimulation() {
  renderDecodedResult("", null);
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
  try {
    await runDecode({ silent: true });
  } catch (error) {
    renderDecodeFailure(error);
  }
  setStatus("Simulation completed and decoded", "success");
}

async function runDecode(options = {}) {
  const { silent = false } = options;
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
  renderDecodedResult(response.extracted_message, response.restored_image_path);
  if (!silent) {
    setStatus("Decoding completed", "success");
  }
}

async function runUploadedDecode() {
  const stegoInput = el("decode-stego-file");
  if (!stegoInput.files.length) {
    throw new Error("Upload a stego image first");
  }

  const formData = new FormData();
  formData.append("stego_image", stegoInput.files[0]);
  const coverInput = el("decode-cover-file");
  if (coverInput.files.length) {
    formData.append("cover_image", coverInput.files[0]);
  }
  formData.append("edge_threshold_low", String(thresholdValue("edge-threshold-low")));
  formData.append("edge_threshold_high", String(thresholdValue("edge-threshold-high")));
  formData.append("bit_depth", String(getBitDepth()));

  try {
    const response = await api("/api/decode-uploaded-image", { method: "POST", body: formData });
    renderDecodedResult(response.extracted_message, response.restored_image_path);
    setStatus("Uploaded image decoded", "success");
  } catch (error) {
    renderDecodeFailure(error);
    setStatus("Uploaded image decode failed", "warning");
  }
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

const _uploadBtn = el("upload-btn");
if (_uploadBtn) _uploadBtn.addEventListener("click", async () => {
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

const _preprocessBtn = el("preprocess-btn");
if (_preprocessBtn) _preprocessBtn.addEventListener("click", async () => {
  try {
    await runPreprocess();
  } catch (error) {
    setStatus(error.message, "danger");
  }
});

const _runBtn = el("run-btn");
if (_runBtn) _runBtn.addEventListener("click", async () => {
  try {
    await runSimulation();
  } catch (error) {
    setStatus(error.message, "danger");
  }
});

const _decodeBtn = el("decode-btn");
if (_decodeBtn) _decodeBtn.addEventListener("click", async () => {
  try {
    await runDecode();
  } catch (error) {
    renderDecodeFailure(error);
    setStatus("Decoded output updated", "warning");
  }
});

const _decodeUploadBtn = el("decode-upload-btn");
if (_decodeUploadBtn) _decodeUploadBtn.addEventListener("click", async () => {
  try {
    await runUploadedDecode();
  } catch (error) {
    setStatus(error.message, "danger");
  }
});

const _decodeSource = el("decode-source");
if (_decodeSource) _decodeSource.addEventListener("change", toggleDecodeMode);

Object.entries(imageDownloadMap).forEach(([buttonId, config]) => {
  const button = el(buttonId);
  if (!button) {
    return;
  }
  button.addEventListener("click", async () => {
    try {
      await downloadImageByPath(config.path(), config.route, config.filename);
    } catch (error) {
      setStatus(error.message, "danger");
    }
  });
});

const _downloadCollageBtn = el("download-collage-btn");
if (_downloadCollageBtn) _downloadCollageBtn.addEventListener("click", async () => {
  try {
    await downloadCollage();
  } catch (error) {
    setStatus(error.message, "danger");
  }
});

// Generate or download stego binary via buttons
const _generateStegoBinaryBtn = el("generate-stego-binary-btn");
if (_generateStegoBinaryBtn) _generateStegoBinaryBtn.addEventListener("click", async () => {
  try {
    await updateBinaryPreview();
    setStatus("Stego binary generated", "success");
  } catch (err) {
    setStatus("Unable to generate stego binary", "danger");
  }
});

const _downloadStegoBinaryBtn = el("download-stego-binary-btn");
if (_downloadStegoBinaryBtn) _downloadStegoBinaryBtn.addEventListener("click", async () => {
  try {
    const stegoPath = currentSimulation?.stego_image_path;
    if (!stegoPath) throw new Error("No stego image available");
    const url = imageUrlFromPath(stegoPath, "/results");
    const dataUrl = await generateBinaryDataUrlFromUrl(url);
    const res = await fetch(dataUrl);
    const blob = await res.blob();
    triggerDownload(blob, "stego_binary.png");
  } catch (err) {
    setStatus(err.message || "Failed to download stego binary", "danger");
  }
});

const _matrixRunBtn = el("matrix-run-btn");
if (_matrixRunBtn) _matrixRunBtn.addEventListener("click", async () => {
  try {
    await runMatrixAnalysis();
  } catch (error) {
    setStatus(error.message, "danger");
  }
});

const _payloadFile = el("payload-file");
if (_payloadFile) _payloadFile.addEventListener("change", async () => {
  try {
    await loadPayloadFile();
    setStatus("Payload text loaded", "success");
  } catch (error) {
    setStatus(error.message, "danger");
  }
});

const _payloadSize = el("payload-size");
if (_payloadSize) _payloadSize.addEventListener("change", updateCapacityDisplay);
const _secretMessage = el("secret-message");
if (_secretMessage) _secretMessage.addEventListener("input", updateCapacityDisplay);
const _edgeLow = el("edge-threshold-low");
if (_edgeLow) _edgeLow.addEventListener("input", () => {
  updateThresholdLabels();
  schedulePreprocess();
});
const _edgeHigh = el("edge-threshold-high");
if (_edgeHigh) _edgeHigh.addEventListener("input", () => {
  updateThresholdLabels();
  schedulePreprocess();
});
const _bitDepth = el("bit-depth");
if (_bitDepth) _bitDepth.addEventListener("change", () => {
  updateCapacityDisplay();
  schedulePreprocess();
});

updateThresholdLabels();
updateCapacityDisplay();
toggleDecodeMode();
loadSimulation().catch((error) => setStatus(error.message, "danger"));
