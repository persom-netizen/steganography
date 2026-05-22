async function api(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error || `Request failed (${response.status})`);
  }
  const ct = response.headers.get("content-type") || "";
  if (ct.includes("application/json")) return response.json();
  return response.blob();
}

const SIMULATION_ID = 1;
let currentSimulation = null;
let preprocessTimer = null;

function el(id) { return document.getElementById(id); }

function setStatus(message, kind = "info") {
  const box = el("status-box");
  if (!box) return;
  box.className = `alert alert-${kind}`;
  box.textContent = message;
}

function characterCount(text) { return Array.from(String(text || "")).length; }
function thresholdValue(id) { return Number(el(id).value) / 100; }
function getPayloadPercentage() { return Number(el("payload-size").value || 0); }
function getBitDepth() { return Number(el("bit-depth").value || 3); }

function updateThresholdLabels() {
  const low = el("edge-low-value");
  const high = el("edge-high-value");
  if (low) low.textContent = thresholdValue("edge-threshold-low").toFixed(2);
  if (high) high.textContent = thresholdValue("edge-threshold-high").toFixed(2);
}

function updateCapacityDisplay() {
  const counter = el("secret-message-counter");
  const summary = el("capacity-summary");
  const msg = el("secret-message");
  if (!counter || !summary || !msg) return;
  const adaptiveBytes = Number(currentSimulation?.adaptive_capacity_bytes ?? currentSimulation?.capacity_bytes ?? 0);
  const characterLimit = adaptiveBytes > 0 ? adaptiveBytes : 0;
  counter.textContent = characterLimit > 0 ? `${characterCount(msg.value)}/${characterLimit}` : `${characterCount(msg.value)}/-`;
  summary.textContent = characterLimit > 0
    ? `Adaptive capacity: ${adaptiveBytes.toLocaleString()} bytes | Approx character limit: ${characterLimit.toLocaleString()}`
    : `Adaptive capacity: pending preprocess | Approx character limit: -`;
}

function formatMetric(value, digits = 6) {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "number" && Number.isFinite(value)) return value.toFixed(digits).replace(/\.0+$/, "");
  return String(value);
}

function resultFileFromPath(pathValue) {
  const raw = String(pathValue || "");
  return raw ? raw.split(/[\\/]/).pop() || "" : "";
}
function imageUrlFromPath(pathValue, baseRoute) {
  const file = resultFileFromPath(pathValue);
  if (!file || !/^[A-Za-z0-9_.-]+$/.test(file) || file.includes("..")) return "";
  return `${baseRoute}/${encodeURIComponent(file)}`;
}

function setPreviewImage(imgId, emptyId, url) {
  const image = el(imgId); const empty = el(emptyId);
  if (!image || !empty) return;
  if (url) { image.src = `${url}?t=${Date.now()}`; image.classList.remove("d-none"); empty.classList.add("d-none"); }
  else { image.removeAttribute("src"); image.classList.add("d-none"); empty.classList.remove("d-none"); }
}

function triggerDownload(blob, filename) {
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement("a"); a.href = objectUrl; a.download = filename; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

async function downloadImageByPath(pathValue, route, filename) {
  const url = imageUrlFromPath(pathValue, route);
  if (!url) throw new Error("Image is not available for download");
  const resp = await fetch(url);
  if (!resp.ok) throw new Error("Unable to download image");
  triggerDownload(await resp.blob(), `${filename}.png`);
}

async function downloadBinaryExport(target) {
  if (!currentSimulation?.id && !currentSimulation?.simulation_id) {
    throw new Error("Simulation is not loaded yet");
  }
  const simulationId = Number(currentSimulation.id || currentSimulation.simulation_id || 1);
  const blob = await api(`/api/simulation/${simulationId}/binary-export?target=${encodeURIComponent(target)}`);
  triggerDownload(blob, `${target}_binary_sim_${simulationId}.txt`);
}

function loadImage(url) { return new Promise((resolve, reject) => { const img = new Image(); img.onload = () => resolve(img); img.onerror = reject; img.src = `${url}?t=${Date.now()}`; }); }

async function downloadCollage() {
  const originals = [
    { path: currentSimulation?.image_path, route: "/uploads", label: "Original" },
    { path: currentSimulation?.edge_map_path, route: "/results", label: "Edge" },
    { path: currentSimulation?.stego_image_path, route: "/results", label: "Stego" },
    { path: currentSimulation?.difference_image_path, route: "/results", label: "Difference" },
  ];
  const resolved = originals.map((it) => ({ ...it, url: imageUrlFromPath(it.path, it.route) })).filter((it) => it.url);
  if (!resolved.length) throw new Error("No images available for collage download");
  const loaded = await Promise.all(resolved.map(async (it) => ({ ...it, image: await loadImage(it.url) })));
  const tileW = Math.max(...loaded.map((i) => i.image.naturalWidth));
  const tileH = Math.max(...loaded.map((i) => i.image.naturalHeight));
  const canvas = document.createElement("canvas"); canvas.width = tileW * 2; canvas.height = tileH * 2; const ctx = canvas.getContext("2d");
  loaded.forEach((item, idx) => { const x = (idx % 2) * tileW; const y = Math.floor(idx / 2) * tileH; ctx.fillStyle = "#fff"; ctx.fillRect(x, y, tileW, tileH); ctx.drawImage(item.image, x, y, tileW, tileH); ctx.fillStyle = "rgba(0,0,0,0.6)"; ctx.fillRect(x, y + tileH - 28, tileW, 28); ctx.fillStyle = "#fff"; ctx.font = "16px sans-serif"; ctx.fillText(item.label, x + 10, y + tileH - 9); });
  const blob = await new Promise((res) => canvas.toBlob(res, "image/png"));
  if (!blob) throw new Error("Unable to generate collage image");
  triggerDownload(blob, "image_collage.png");
}

function toggleDecodeMode() { const panel = el("decode-upload-panel"); const src = el("decode-source"); if (!panel || !src) return; panel.classList.toggle("d-none", src.value !== "upload"); }

function renderSimulation(sim) {
  currentSimulation = sim;
  setPreviewImage("original-image-preview", "original-image-empty", imageUrlFromPath(sim?.image_path, "/uploads"));
  setPreviewImage("edge-image-preview", "edge-image-empty", imageUrlFromPath(sim?.edge_map_path, "/results"));
  setPreviewImage("stego-image-preview", "stego-image-empty", imageUrlFromPath(sim?.stego_image_path, "/results"));
  setPreviewImage("difference-image-preview", "difference-image-empty", imageUrlFromPath(sim?.difference_image_path, "/results"));
  updateCapacityDisplay();

  const setText = (id, txt) => { const n = el(id); if (n) n.textContent = txt; };
  setText("metric-edge-pixels", formatMetric(sim?.edge_pixel_count, 0));
  setText("metric-max-words", formatMetric(sim?.max_possible_word_count, 0));
  setText("metric-embedded-words", formatMetric(sim?.actual_embedded_word_count ?? sim?.embedded_words, 0));
  setText("metric-psnr", formatMetric(sim?.psnr));
  setText("metric-ssim", formatMetric(sim?.ssim));
  setText("metric-qindex", formatMetric(sim?.q_index ?? sim?.qindex ?? sim?.qIndex));
  setText("metric-mse", formatMetric(sim?.mse));
  setText("metric-chi-square", formatMetric(sim?.chi_square));

  if (sim?.status === "decoded" && sim?.extracted_message) {
    const dec = el("decoded-message"); if (dec) dec.value = sim.extracted_message;
    setPreviewImage("restored-image-preview", "restored-image-empty", imageUrlFromPath(sim?.image_path, "/uploads"));
  } else {
    const dec = el("decoded-message"); if (dec) dec.value = "";
    setPreviewImage("restored-image-preview", "restored-image-empty", "");
  }
}

function renderDecodedResult(message, restoredPath) { const d = el("decoded-message"); if (d) d.value = message || ""; setPreviewImage("restored-image-preview", "restored-image-empty", restoredPath ? imageUrlFromPath(restoredPath, "/uploads") : ""); }
function renderDecodeFailure(error) { const m = error instanceof Error ? error.message : String(error || "Decoding failed"); renderDecodedResult(`Decoding failed: ${m}`, null); }

function renderMatrixReport(report) {
  const sum = el("matrix-summary"); if (sum) sum.textContent = report?.summary || "Run matrix analysis to generate a recommendation.";
  const body = el("matrix-results-body"); if (!body) return; const runs = Array.isArray(report?.runs) ? report.runs : [];
  if (!runs.length) { body.innerHTML = '<tr><td colspan="6" class="text-muted">No matrix analysis runs yet.</td></tr>'; return; }
  body.innerHTML = runs.map((run) => `\n    <tr>\n      <td>${run.image ?? "-"}</td>\n      <td>${run.payload_percentage ?? "-"}</td>\n      <td>${run.bit_depth ?? "-"}</td>\n      <td>${formatMetric(run.psnr)}</td>\n      <td>${formatMetric(run.ssim)}</td>\n      <td>${formatMetric(run.chi_square)}</td>\n    </tr>`).join("");
}

async function loadSimulation() { const sim = await api(`/api/simulation/${SIMULATION_ID}`); renderSimulation(sim); }

async function loadPayloadFile() { const input = el("payload-file"); if (!input || !input.files.length) throw new Error("Choose a .txt payload first"); const txt = await input.files[0].text(); const msg = el("secret-message"); if (msg) msg.value = txt; updateCapacityDisplay(); }

function schedulePreprocess() { if (preprocessTimer) clearTimeout(preprocessTimer); if (!currentSimulation?.image_path) return; preprocessTimer = setTimeout(() => runPreprocess().catch((e) => setStatus(e.message, "danger")), 250); }

async function runPreprocess() {
  if (!currentSimulation?.image_path) throw new Error("Upload an image first");
  const resp = await api("/api/preprocess", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ simulation_id: SIMULATION_ID, edge_threshold_low: thresholdValue("edge-threshold-low"), edge_threshold_high: thresholdValue("edge-threshold-high"), bit_depth: getBitDepth(), }), });
  renderSimulation(resp.simulation); setStatus("Preprocessing completed", "success");
}

async function runSimulation() {
  renderDecodedResult("", null);
  const response = await api("/api/run-simulation", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ simulation_id: SIMULATION_ID, payload_percentage: getPayloadPercentage(), secret_message: el("secret-message").value, edge_threshold_low: thresholdValue("edge-threshold-low"), edge_threshold_high: thresholdValue("edge-threshold-high"), bit_depth: getBitDepth(), }), });
  renderSimulation(response.simulation);
  try { await runDecode({ silent: true }); } catch (e) { renderDecodeFailure(e); }
  setStatus("Simulation completed and decoded", "success");
}

async function runDecode(options = {}) {
  const { silent = false } = options;
  if (!currentSimulation?.stego_image_path) throw new Error("Run the simulation first");
  const resp = await api("/api/decode-simulation", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ simulation_id: SIMULATION_ID, edge_threshold_low: thresholdValue("edge-threshold-low"), edge_threshold_high: thresholdValue("edge-threshold-high"), bit_depth: getBitDepth(), }), });
  renderSimulation(resp.simulation); renderDecodedResult(resp.extracted_message, resp.restored_image_path); if (!silent) setStatus("Decoding completed", "success");
}

async function runUploadedDecode() {
  const stegoInput = el("decode-stego-file"); if (!stegoInput || !stegoInput.files.length) throw new Error("Upload a stego image first"); const form = new FormData(); form.append("stego_image", stegoInput.files[0]); const cover = el("decode-cover-file"); if (cover && cover.files.length) form.append("cover_image", cover.files[0]); form.append("edge_threshold_low", String(thresholdValue("edge-threshold-low"))); form.append("edge_threshold_high", String(thresholdValue("edge-threshold-high"))); form.append("bit_depth", String(getBitDepth()));
  try { const resp = await api("/api/decode-uploaded-image", { method: "POST", body: form }); renderDecodedResult(resp.extracted_message, resp.restored_image_path); setStatus("Uploaded image decoded", "success"); } catch (e) { renderDecodeFailure(e); setStatus("Uploaded image decode failed", "warning"); }
}

async function runMatrixAnalysis() {
  const benchmarkInput = el("benchmark-images"); if (!benchmarkInput || !benchmarkInput.files.length) throw new Error("Upload one or more benchmark images"); const form = new FormData(); for (const f of benchmarkInput.files) form.append("benchmarks", f); form.append("payload_text", el("matrix-payload-text").value || el("secret-message").value); form.append("payload_options", el("matrix-payload-options").value || "10,25,50,75,100"); form.append("edge_threshold_low", String(thresholdValue("edge-threshold-low"))); form.append("edge_threshold_high", String(thresholdValue("edge-threshold-high"))); form.append("bit_depth", String(getBitDepth())); const report = await api("/api/matrix-analysis", { method: "POST", body: form }); renderMatrixReport(report); setStatus("Matrix analysis completed", "success"); }

// UI wiring
(function init() {
  const uploadBtn = el("upload-btn"); if (uploadBtn) uploadBtn.addEventListener("click", async () => { try { const fi = el("cover-image"); if (!fi || !fi.files.length) throw new Error("Choose an image first"); const form = new FormData(); form.append("image", fi.files[0]); form.append("simulation_id", SIMULATION_ID); form.append("edge_threshold_low", String(thresholdValue("edge-threshold-low"))); form.append("edge_threshold_high", String(thresholdValue("edge-threshold-high"))); form.append("bit_depth", String(getBitDepth())); const res = await api("/api/upload-image", { method: "POST", body: form }); renderSimulation(res.simulation); setStatus("Image uploaded", "success"); } catch (e) { setStatus(e.message, "danger"); } });

  const preprocessBtn = el("preprocess-btn"); if (preprocessBtn) preprocessBtn.addEventListener("click", async () => { try { await runPreprocess(); } catch (e) { setStatus(e.message, "danger"); } });
  const runBtn = el("run-btn"); if (runBtn) runBtn.addEventListener("click", async () => { try { await runSimulation(); } catch (e) { setStatus(e.message, "danger"); } });
  const decodeBtn = el("decode-btn"); if (decodeBtn) decodeBtn.addEventListener("click", async () => { try { await runDecode(); } catch (e) { renderDecodeFailure(e); setStatus("Decoded output updated", "warning"); } });
  const decodeUploadBtn = el("decode-upload-btn"); if (decodeUploadBtn) decodeUploadBtn.addEventListener("click", async () => { try { await runUploadedDecode(); } catch (e) { setStatus(e.message, "danger"); } });
  const decodeSource = el("decode-source"); if (decodeSource) decodeSource.addEventListener("change", toggleDecodeMode);

  Object.entries({ "download-original-btn": {route: "/uploads", path: () => currentSimulation?.image_path, filename: "original_image"}, "download-edge-btn": {route: "/results", path: () => currentSimulation?.edge_map_path, filename: "edge_map"}, "download-stego-btn": {route: "/results", path: () => currentSimulation?.stego_image_path, filename: "stego_image"}, "download-difference-btn": {route: "/results", path: () => currentSimulation?.difference_image_path, filename: "difference_image"} }).forEach(([buttonId, cfg]) => { const b = el(buttonId); if (!b) return; b.addEventListener("click", async () => { try { await downloadImageByPath(cfg.path(), cfg.route, cfg.filename); } catch (e) { setStatus(e.message, "danger"); } }); });

  const binaryOriginalBtn = el("binary-original-btn");
  if (binaryOriginalBtn) {
    binaryOriginalBtn.addEventListener("click", async () => {
      try { await downloadBinaryExport("original"); }
      catch (e) { setStatus(e.message, "danger"); }
    });
  }

  const binaryStegoBtn = el("binary-stego-btn");
  if (binaryStegoBtn) {
    binaryStegoBtn.addEventListener("click", async () => {
      try { await downloadBinaryExport("stego"); }
      catch (e) { setStatus(e.message, "danger"); }
    });
  }

  const downloadCollageBtn = el("download-collage-btn"); if (downloadCollageBtn) downloadCollageBtn.addEventListener("click", async () => { try { await downloadCollage(); } catch (e) { setStatus(e.message, "danger"); } });

  const matrixRunBtn = el("matrix-run-btn"); if (matrixRunBtn) matrixRunBtn.addEventListener("click", async () => { try { await runMatrixAnalysis(); } catch (e) { setStatus(e.message, "danger"); } });

  const payloadFile = el("payload-file"); if (payloadFile) payloadFile.addEventListener("change", async () => { try { await loadPayloadFile(); setStatus("Payload text loaded", "success"); } catch (e) { setStatus(e.message, "danger"); } });

  const payloadSize = el("payload-size"); if (payloadSize) payloadSize.addEventListener("change", updateCapacityDisplay);
  const secretMessage = el("secret-message"); if (secretMessage) secretMessage.addEventListener("input", updateCapacityDisplay);
  const edgeLow = el("edge-threshold-low"); if (edgeLow) edgeLow.addEventListener("input", () => { updateThresholdLabels(); schedulePreprocess(); });
  const edgeHigh = el("edge-threshold-high"); if (edgeHigh) edgeHigh.addEventListener("input", () => { updateThresholdLabels(); schedulePreprocess(); });
  const bitDepth = el("bit-depth"); if (bitDepth) bitDepth.addEventListener("change", () => { updateCapacityDisplay(); schedulePreprocess(); });

  updateThresholdLabels(); updateCapacityDisplay(); toggleDecodeMode(); loadSimulation().catch((e) => setStatus(e.message, "danger"));
})();
