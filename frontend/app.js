(() => {
  const API_BASE = String(window.QUEST_API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
  const MODELS = [
    { id: "aifs-single", key: "aifs", name: "AIFS Single", color: "#258361" },
    { id: "ifs", key: "ifs", name: "IFS", color: "#d27851" },
  ];
  const LOG_MIN = 0.1;
  const COLORS = ["#ffffd9", "#c7e9b4", "#7fcdbb", "#41b6c4", "#1d91c0", "#225ea8", "#081d58"];
  const state = { health: null, fields: {}, selected: null, point: null, region: null, scaleMax: 1, busy: false };
  const $ = (id) => document.getElementById(id);
  const banner = $("service-banner");
  const mapCanvases = Object.fromEntries(MODELS.map((model) => [model.id, $(model.key === "aifs" ? "field-aifs" : "field-ifs")]));

  function apiUrl(path) { return `${API_BASE}${path}`; }

  async function apiGet(path) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch(apiUrl(path), { signal: controller.signal, headers: { Accept: "application/json" } });
      let payload;
      try { payload = await response.json(); } catch { payload = null; }
      if (!response.ok) {
        const error = payload?.error ?? {};
        const failure = new Error(error.message || `API request failed (${response.status})`);
        failure.status = response.status;
        failure.code = error.code || "http_error";
        failure.details = error.details || {};
        throw failure;
      }
      return payload;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("The back end did not respond within 12 seconds. Try again when the connection is available.");
      if (error instanceof TypeError) throw new Error("The back end could not be reached. Check that the API is running and its address is configured.");
      throw error;
    } finally { window.clearTimeout(timeout); }
  }

  function showBanner(message, kind = "error") {
    banner.textContent = message;
    banner.className = `service-banner ${kind}`;
    banner.hidden = false;
  }

  function hideBanner() { banner.hidden = true; banner.textContent = ""; }

  function formatRun(iso) {
    if (!iso) return "—";
    const date = new Date(iso);
    return `${date.toISOString().slice(0, 10)} ${String(date.getUTCHours()).padStart(2, "0")}Z`;
  }

  function formatAge(seconds) {
    if (!Number.isFinite(seconds)) return "—";
    const totalMinutes = Math.max(0, Math.floor(seconds / 60));
    const hours = Math.floor(totalMinutes / 60);
    const minutes = totalMinutes % 60;
    return hours ? `${hours}h ${minutes}m` : `${minutes}m`;
  }

  function updateFreshness(step = Number($("step-hours").value)) {
    if (!state.health?.models) return;
    const available = MODELS.map((model) => state.health.models[model.id]).filter((model) => model?.available);
    if (!available.length) return;
    const newest = available.reduce((a, b) => (a.ageSeconds <= b.ageSeconds ? a : b));
    const oldest = available.reduce((a, b) => (a.ageSeconds >= b.ageSeconds ? a : b));
    $("run-time").textContent = formatRun(oldest.sourceRunUtc);
    $("forecast-age").textContent = `${formatAge(oldest.ageSeconds)}${oldest.stale ? " · stale" : ""}`;
    const failed = available.filter((model) => model.lastIngestSucceeded === false);
    $("ingest-state").textContent = failed.length ? `${failed.length} latest attempt${failed.length > 1 ? "s" : ""} failed` : "Successful";
    const pill = $("freshness-state");
    if (available.some((model) => model.stale)) {
      pill.textContent = "STALE FORECAST"; pill.className = "state-pill stale";
    } else if (failed.length) {
      pill.textContent = "LAST GOOD DATA"; pill.className = "state-pill failed";
    } else {
      pill.textContent = "FRESH · ≤12 H"; pill.className = "state-pill";
    }
    const run = new Date(oldest.sourceRunUtc);
    const valid = new Date(run.getTime() + step * 3600000);
    $("valid-time").textContent = `Selected step ${step} h · valid ${formatRun(valid.toISOString())} UTC · initialized ${formatRun(oldest.sourceRunUtc)} UTC`;
    if (available.some((model) => model.stale)) showBanner(`This forecast is ${formatAge(oldest.ageSeconds)} old. It remains viewable, but is beyond the 12-hour freshness window.`, "error");
    else if (failed.length) showBanner("The latest ingest attempt failed. This view is using the previous verified forecast.", "error");
    else hideBanner();
  }

  function makeRegion(centerLat, centerLon) {
    const snap = (value) => Math.round(value * 4) / 4;
    const span = (center, width, minimum, maximum) => {
      let low = snap(center - width / 2);
      low = Math.max(minimum, Math.min(maximum - width, low));
      return [Number(low.toFixed(2)), Number((low + width).toFixed(2))];
    };
    const [south, north] = span(centerLat, 20, -90, 90);
    const [west, east] = span(centerLon, 30, -180, 180);
    return { south, north, west, east };
  }

  function setFieldMessage(modelId, message, show = true) {
    const key = modelId === "aifs-single" ? "aifs" : "ifs";
    const overlay = $(`field-${key}-message`);
    overlay.textContent = message;
    overlay.hidden = !show;
  }

  function loadingMessage(message) {
    for (const model of MODELS) setFieldMessage(model.id, message, true);
  }

  async function loadHealthAndRegion() {
    if (state.busy) return;
    state.busy = true;
    const button = $("load-region");
    button.disabled = true;
    button.querySelector("span:first-child").textContent = "Loading…";
    state.health = null;
    state.fields = {};
    $("scale-note").textContent = "Shared logarithmic colour scale · loading";
    for (const model of MODELS) {
      const canvas = mapCanvases[model.id];
      canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
      $(`${model.key}-cell-count`).textContent = "— CELLS";
      $(`${model.key}-quality`).textContent = "Field data quality: loading clipping metadata.";
    }
    loadingMessage("Loading bounded regional fields from the back end…");
    try {
      const health = await apiGet("/api/v1/health");
      state.health = health;
      updateFreshness();
      const centerLat = Number($("center-lat").value);
      const centerLon = Number($("center-lon").value);
      if (!Number.isFinite(centerLat) || centerLat < -90 || centerLat > 90 || !Number.isFinite(centerLon) || centerLon < -180 || centerLon >= 180) {
        throw new Error("Enter a latitude from −90 to 90 and a longitude from −180 up to (but not including) 180.");
      }
      const previousRegion = state.region;
      const region = makeRegion(centerLat, centerLon);
      state.region = { ...region, centerLat, centerLon };
      $("region-description").textContent = `Window ${region.west.toFixed(2)}° to ${region.east.toFixed(2)}° longitude · ${region.north.toFixed(2)}° to ${region.south.toFixed(2)}° latitude · centered near ${centerLat.toFixed(2)}°, ${centerLon.toFixed(2)}°.`;
      const step = Number($("step-hours").value);
      const kind = $("field-kind").value;
      updateFreshness(step);
      const bbox = `${region.west},${region.south},${region.east},${region.north}`;
      const requests = MODELS.map(async (model) => {
        try {
          const field = await apiGet(`/api/v1/field?model=${model.id}&stepHours=${encodeURIComponent(step)}&kind=${kind}&bbox=${encodeURIComponent(bbox)}&stride=1`);
          state.fields[model.id] = field;
          renderField(model.id);
          renderQuality(model.id, field, kind);
        } catch (error) {
          setFieldMessage(model.id, error.code === "step_unavailable" ? `Step ${step} h is not available. Available steps: ${(error.details.availableSteps || []).join(", ") || "none reported"} h.` : error.message, true);
          $(`${model.key}-quality`).textContent = "Field data quality: unavailable for this request.";
          $(`${model.key}-cell-count`).textContent = "— CELLS";
          throw error;
        }
      });
      const results = await Promise.allSettled(requests);
      const failed = results.find((result) => result.status === "rejected");
      if (failed) {
        if (failed.reason.code === "step_unavailable") showBanner(`Step ${step} h is unavailable. Available steps: ${(failed.reason.details.availableSteps || []).join(", ")} h.`, "error");
        else showBanner(failed.reason.message, "error");
      } else if (!MODELS.every((model) => state.fields[model.id])) {
        showBanner("One or more field requests returned no data. Check the model availability and try again.", "error");
      } else {
        const values = MODELS.flatMap((model) => state.fields[model.id].values.flat().filter((value) => Number.isFinite(value) && value >= LOG_MIN));
        state.scaleMax = Math.max(LOG_MIN * 1.01, ...values);
        $("scale-note").textContent = `Shared log scale · 0.1–${state.scaleMax.toFixed(state.scaleMax >= 10 ? 0 : 1)} mm · values below 0.1 mm masked`;
        for (const model of MODELS) renderField(model.id);
        if (!state.selected || previousRegion?.centerLat !== centerLat || previousRegion?.centerLon !== centerLon) {
          state.selected = { latitude: centerLat, longitude: centerLon };
          await loadPointFingerprint(state.selected);
        }
      }
    } catch (error) {
      if (!state.health && error.status === 503) {
        showBanner("The back end is running but has no verified forecast available. No field data was loaded.", "error");
        $("freshness-state").textContent = "NO VALID DATA";
        $("freshness-state").className = "state-pill failed";
        $("run-time").textContent = "Unavailable";
        $("forecast-age").textContent = "Unknown";
        $("ingest-state").textContent = "Unavailable";
      } else if (!state.health) {
        showBanner(`Freshness could not be checked. ${error.message} No forecast data was loaded.`, "error");
        $("freshness-state").textContent = "API UNAVAILABLE";
        $("freshness-state").className = "state-pill failed";
        $("run-time").textContent = "Unavailable";
        $("forecast-age").textContent = "Unknown";
        $("ingest-state").textContent = "Unknown";
      } else if (error.status === 503) {
        showBanner(`The back end has no verified forecast available. ${error.message}`, "error");
      } else if (error.code !== "step_unavailable") {
        showBanner(error.message, "error");
      }
    } finally {
      state.busy = false;
      button.disabled = false;
      button.querySelector("span:first-child").textContent = "Load region";
      if (!state.health) loadingMessage("Forecast unavailable. Use Load region to retry when the API is running.");
    }
  }

  function colorAt(value) {
    if (!Number.isFinite(value) || value < LOG_MIN) return "#eef1f4";
    const scale = Math.max(LOG_MIN * 1.001, state.scaleMax);
    const fraction = Math.max(0, Math.min(1, Math.log(value / LOG_MIN) / Math.log(scale / LOG_MIN)));
    const position = fraction * (COLORS.length - 1);
    const index = Math.min(COLORS.length - 2, Math.floor(position));
    const blend = position - index;
    const a = COLORS[index].match(/[\da-f]{2}/gi).map((part) => parseInt(part, 16));
    const b = COLORS[index + 1].match(/[\da-f]{2}/gi).map((part) => parseInt(part, 16));
    return `rgb(${a.map((channel, i) => Math.round(channel + (b[i] - channel) * blend)).join(",")})`;
  }

  function renderField(modelId) {
    const field = state.fields[modelId];
    if (!field) return;
    const canvas = mapCanvases[modelId];
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (!width || !height) return;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    const context = canvas.getContext("2d");
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, width, height);
    context.fillStyle = "#eef1f4";
    context.fillRect(0, 0, width, height);
    const plot = { x: 48, y: 12, width: Math.max(20, width - 61), height: Math.max(20, height - 44) };
    canvas.__plot = plot;
    const [rows, columns] = field.shape;
    const cellWidth = plot.width / columns;
    const cellHeight = plot.height / rows;
    for (let row = 0; row < rows; row += 1) {
      for (let column = 0; column < columns; column += 1) {
        const value = field.values[row][column];
        if (value === null || !Number.isFinite(value) || value < LOG_MIN) continue;
        context.fillStyle = colorAt(value);
        context.fillRect(plot.x + column * cellWidth, plot.y + row * cellHeight, cellWidth + 0.35, cellHeight + 0.35);
      }
    }
    context.strokeStyle = "rgba(74,91,81,.27)";
    context.lineWidth = 0.6;
    context.font = "9px 'DM Mono', monospace";
    context.fillStyle = "#617067";
    context.textAlign = "center";
    context.textBaseline = "top";
    for (let i = 0; i < 3; i += 1) {
      const x = plot.x + (plot.width * i) / 2;
      const y = plot.y + (plot.height * i) / 2;
      context.beginPath(); context.moveTo(x, plot.y); context.lineTo(x, plot.y + plot.height); context.stroke();
      context.fillText(`${Number(field.longitude[i === 0 ? 0 : i === 1 ? Math.floor((columns - 1) / 2) : columns - 1]).toFixed(1)}°`, x, plot.y + plot.height + 5);
      context.textAlign = "right"; context.textBaseline = "middle";
      context.beginPath(); context.moveTo(plot.x, y); context.lineTo(plot.x + plot.width, y); context.stroke();
      const lat = field.latitude[i === 0 ? 0 : i === 1 ? Math.floor((rows - 1) / 2) : rows - 1];
      context.fillText(`${Number(lat).toFixed(1)}°`, plot.x - 6, y);
      context.textAlign = "center"; context.textBaseline = "top";
    }
    const selected = state.selected;
    if (selected && selected.latitude >= Math.min(...field.latitude) && selected.latitude <= Math.max(...field.latitude) && selected.longitude >= Math.min(...field.longitude) && selected.longitude <= Math.max(...field.longitude)) {
      const row = field.latitude.reduce((best, value, index) => Math.abs(value - selected.latitude) < Math.abs(field.latitude[best] - selected.latitude) ? index : best, 0);
      const column = field.longitude.reduce((best, value, index) => Math.abs(value - selected.longitude) < Math.abs(field.longitude[best] - selected.longitude) ? index : best, 0);
      const cx = plot.x + (column + 0.5) * cellWidth;
      const cy = plot.y + (row + 0.5) * cellHeight;
      context.strokeStyle = "#162e26"; context.lineWidth = 1.6;
      context.beginPath(); context.arc(cx, cy, 5, 0, Math.PI * 2); context.stroke();
      context.fillStyle = "#fff"; context.beginPath(); context.arc(cx, cy, 2, 0, Math.PI * 2); context.fill();
    }
    $(`${modelId === "aifs-single" ? "aifs" : "ifs"}-cell-count`).textContent = `${rows * columns} CELLS`;
    setFieldMessage(modelId, "", false);
  }

  function renderQuality(modelId, field, kind) {
    const id = `${modelId === "aifs-single" ? "aifs" : "ifs"}-quality`;
    const note = $(id);
    if (kind === "interval") {
      const count = field.clippedCellCount;
      note.textContent = count ? `DATA QUALITY · ${count} cells adjusted below zero to 0 mm.` : "DATA QUALITY · No negative interval cells adjusted in this field.";
      note.className = count ? "quality-note adjusted" : "quality-note";
    } else {
      note.textContent = "Cumulative field · interval clipping does not apply.";
      note.className = "quality-note";
    }
  }

  function onMapClick(modelId, event) {
    const field = state.fields[modelId];
    const canvas = mapCanvases[modelId];
    const plot = canvas.__plot;
    if (!field || !plot) return;
    const bounds = canvas.getBoundingClientRect();
    const x = event.clientX - bounds.left;
    const y = event.clientY - bounds.top;
    if (x < plot.x || x > plot.x + plot.width || y < plot.y || y > plot.y + plot.height) return;
    const column = Math.max(0, Math.min(field.longitude.length - 1, Math.floor(((x - plot.x) / plot.width) * field.longitude.length)));
    const row = Math.max(0, Math.min(field.latitude.length - 1, Math.floor(((y - plot.y) / plot.height) * field.latitude.length)));
    state.selected = { latitude: Number(field.latitude[row]), longitude: Number(field.longitude[column]) };
    for (const model of MODELS) renderField(model.id);
    loadPointFingerprint(state.selected);
  }

  async function loadPointFingerprint(coordinates) {
    $("fingerprint-message").hidden = false;
    $("fingerprint-message").textContent = "Loading the selected cell’s full time series from both models…";
    $("chart-wrap").hidden = true;
    $("series-table-wrap").hidden = true;
    try {
      const point = await apiGet(`/api/v1/point?lat=${encodeURIComponent(coordinates.latitude)}&lon=${encodeURIComponent(coordinates.longitude)}&model=all`);
      state.point = point;
      state.selected = { latitude: Number(point.requested.latitude), longitude: Number(point.requested.longitude) };
      $("point-heading").textContent = "The rainfall fingerprint";
      const cells = MODELS.filter((model) => point.models[model.id]).map((model) => {
        const cell = point.models[model.id].nearestCell;
        return `${model.name} ${cell.latitude.toFixed(2)}°, ${cell.longitude.toFixed(2)}°`;
      });
      $("point-coordinates").textContent = cells.join(" · ");
      $("fingerprint-message").hidden = true;
      renderFingerprint(point);
      for (const model of MODELS) renderField(model.id);
      updateFreshness();
    } catch (error) {
      $("fingerprint-message").hidden = false;
      $("fingerprint-message").textContent = `Point forecast unavailable. ${error.message}`;
      showBanner(error.message, "error");
    }
  }

  function renderFingerprint(point) {
    const available = MODELS.filter((model) => point.models[model.id]);
    if (!available.length) return;
    const series = available.flatMap((model) => point.models[model.id].series);
    const max = Math.max(1, ...series.map((item) => Number(item.cumulativeMm) || 0));
    const width = 900; const height = 230; const left = 48; const right = 24; const top = 20; const bottom = 32;
    const plotWidth = width - left - right; const plotHeight = height - top - bottom;
    const steps = point.models[available[0].id].series.map((entry) => entry.stepHours);
    const xAt = (index) => left + (steps.length === 1 ? plotWidth / 2 : (index / (steps.length - 1)) * plotWidth);
    const yAt = (value) => top + plotHeight - (value / max) * plotHeight;
    let svg = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Cumulative rainfall at the selected point by forecast step, in millimetres">`;
    for (let i = 0; i <= 2; i += 1) {
      const value = max * (i / 2); const y = yAt(value);
      svg += `<line class="chart-grid" x1="${left}" y1="${y}" x2="${width - right}" y2="${y}"/><text class="chart-axis" x="${left - 8}" y="${y + 3}" text-anchor="end">${value.toFixed(value < 10 ? 1 : 0)}</text>`;
    }
    steps.forEach((step, index) => { svg += `<text class="chart-axis" x="${xAt(index)}" y="${height - 8}" text-anchor="middle">+${step}h</text>`; });
    for (const model of available) {
      const data = point.models[model.id].series;
      const points = data.map((entry, index) => `${xAt(index)},${yAt(Number(entry.cumulativeMm) || 0)}`).join(" ");
      svg += `<polyline class="${model.id === "ifs" ? "chart-ifs" : "chart-aifs"}" points="${points}"/>`;
      data.forEach((entry, index) => { svg += `<circle class="${model.id === "ifs" ? "point-ifs" : "point-aifs"}" cx="${xAt(index)}" cy="${yAt(Number(entry.cumulativeMm) || 0)}" r="4"/>`; });
    }
    svg += `<text class="chart-legend" x="${left}" y="13">Cumulative precipitation (mm)</text>`;
    svg += `<line x1="${width - 195}" y1="13" x2="${width - 175}" y2="13" class="chart-aifs"/><text class="chart-legend" x="${width - 169}" y="16">AIFS</text><line x1="${width - 110}" y1="13" x2="${width - 90}" y2="13" class="chart-ifs"/><text class="chart-legend" x="${width - 84}" y="16">IFS</text>`;
    svg += "</svg>";
    $("chart-wrap").innerHTML = svg;
    $("chart-wrap").hidden = false;
    const rows = available.map((model) => {
      const entries = point.models[model.id].series;
      const cells = entries.map((entry) => `<td>+${entry.stepHours} h<br><span class="table-sub">+${entry.intervalMm === null ? "—" : Number(entry.intervalMm).toFixed(2)} mm interval</span><br>${entry.cumulativeMm === null ? "—" : Number(entry.cumulativeMm).toFixed(2)} mm total${entry.intervalClipped ? "*" : ""}</td>`).join("");
      return `<tr class="${model.id === "ifs" ? "ifs-row" : "aifs-row"}"><td>${model.name}</td>${cells}</tr>`;
    }).join("");
    $("series-table-wrap").innerHTML = `<table class="series-table"><thead><tr><th>Model</th>${steps.map((step) => `<th>Step +${step} h</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table><p class="region-description">Each step shows its six-hour interval and cumulative total. *An interval was clipped to zero at the API boundary.</p>`;
    $("series-table-wrap").hidden = false;
  }

  $("load-region").addEventListener("click", loadHealthAndRegion);
  $("step-hours").addEventListener("change", () => updateFreshness());
  for (const model of MODELS) mapCanvases[model.id].addEventListener("click", (event) => onMapClick(model.id, event));
  window.addEventListener("resize", () => { for (const model of MODELS) renderField(model.id); });
  loadHealthAndRegion();
})();
