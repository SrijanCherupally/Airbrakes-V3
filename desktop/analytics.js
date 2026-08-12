/* Full flight-data dashboard, embedded in the Electron renderer. */
(() => {
const STATE_COLORS = {
  STATE_IDLE: "#4b5761",
  STATE_PAD: "#ffb454",
  STATE_BOOST: "#ff5d73",
  STATE_CONTROL: "#4fd6c8",
  STATE_DESCENT: "#8f7bff",
  STATE_LANDED: "#59d97a",
  GROUND_TEST_RECORDING: "#556270",
  UNKNOWN: "#333d46",
};
const STATE_NAMES = [
  "STATE_IDLE",
  "STATE_PAD",
  "STATE_BOOST",
  "STATE_CONTROL",
  "STATE_DESCENT",
  "STATE_LANDED",
  "GROUND_TEST_ARMED",
  "GROUND_TEST_RECORDING",
];
const NUMERIC_COLUMNS = new Set([
  "time_ms",
  "altitude_m",
  "velocity_ms",
  "accel_bias_ms2",
  "raw_accel_ms2",
  "vertical_accel_ms2",
  "raw_baro_m",
  "motor_pos",
  "motor_vel",
  "motor_cmd_pos",
  "roll_rad",
  "pitch_rad",
  "yaw_rad",
  "Cd",
  "desired_Cd",
  "motor_current",
  "battery_voltage",
  "state",
  "axis_error",
]);
const STRING_COLUMNS = new Set(["state_name"]);
const $ = (id) => document.getElementById(id);
const colorForState = (name) => STATE_COLORS[name] || STATE_COLORS.UNKNOWN;
let currentRows = [],
  currentFileName = "",
  folderRuns = {},
  chartIds = [];
const pendingSync = new Set();

function cleanNumber(raw) {
  if (raw === null || raw === undefined) return NaN;
  if (typeof raw === "number") return raw;
  const value = String(raw)
    .trim()
    .replace(/[^0-9eE+\-.]/g, "");
  if (value === "" || value === "-" || value === ".") return NaN;
  const parsed = parseFloat(value);
  return Number.isFinite(parsed) ? parsed : NaN;
}
function parseCsvText(text) {
  const parsed = Papa.parse(text, {
    header: true,
    skipEmptyLines: true,
    dynamicTyping: false,
  });
  const rows = parsed.data
    .map((row) => {
      const out = {};
      for (const key in row) {
        if (!key) continue;
        const name = key.trim();
        out[name] = STRING_COLUMNS.has(name)
          ? String(row[key] || "").trim()
          : cleanNumber(row[key]);
      }
      return out;
    })
    .filter((row) => Number.isFinite(row.time_ms));
  rows.sort((a, b) => a.time_ms - b.time_ms);
  rows.forEach((row) => {
    row.time_s = row.time_ms / 1000;
    if (
      !row.state_name &&
      Number.isInteger(row.state) &&
      STATE_NAMES[row.state]
    )
      row.state_name = STATE_NAMES[row.state];
  });
  return rows;
}

// Session restoration is retained from the standalone viewer. The file-input
// fallback keeps this working in Electron versions without File System Access.
const FSA_SUPPORTED = "showDirectoryPicker" in window;
const DB_NAME = "airbrakes_dashboard_v1",
  STORE = "kv";
function idbOpen() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
async function idbSet(key, value) {
  const db = await idbOpen();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(STORE, "readwrite");
    transaction.objectStore(STORE).put(value, key);
    transaction.oncomplete = resolve;
    transaction.onerror = () => reject(transaction.error);
  });
}
async function idbGet(key) {
  const db = await idbOpen();
  return new Promise((resolve, reject) => {
    const request = db
      .transaction(STORE, "readonly")
      .objectStore(STORE)
      .get(key);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

const fileInputSingle = $("fileInputSingle"),
  dropzoneSingle = $("dropzoneSingle"),
  fileInputFolder = $("fileInputFolder"),
  btnFolder = $("btnFolder"),
  folderNote = $("folderNote");
function openSinglePicker() {
  fileInputSingle.click();
}
async function chooseSingleFile() {
  if (!FSA_SUPPORTED) return openSinglePicker();
  try {
    const [handle] = await window.showOpenFilePicker({
      types: [{ description: "CSV", accept: { "text/csv": [".csv"] } }],
    });
    await idbSet("lastMode", "file");
    await idbSet("fileHandle", handle);
    loadSingleFile(await handle.getFile(), handle.name);
  } catch (_) {
    /* Picker cancellation is expected. */
  }
}
dropzoneSingle.addEventListener("click", chooseSingleFile);
dropzoneSingle.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    chooseSingleFile();
  }
});
["dragenter", "dragover"].forEach((type) =>
  dropzoneSingle.addEventListener(type, (event) => {
    event.preventDefault();
    dropzoneSingle.classList.add("drag");
  }),
);
["dragleave", "drop"].forEach((type) =>
  dropzoneSingle.addEventListener(type, (event) => {
    event.preventDefault();
    dropzoneSingle.classList.remove("drag");
  }),
);
dropzoneSingle.addEventListener("drop", async (event) => {
  const item = event.dataTransfer.items && event.dataTransfer.items[0];
  if (item && item.kind === "file" && item.getAsFileSystemHandle) {
    try {
      const handle = await item.getAsFileSystemHandle();
      if (handle?.kind === "file") {
        await idbSet("lastMode", "file");
        await idbSet("fileHandle", handle);
        loadSingleFile(await handle.getFile(), handle.name);
        return;
      }
    } catch (_) {
      /* Plain File fallback below. */
    }
  }
  const file = event.dataTransfer.files[0];
  if (file) loadSingleFile(file);
});
fileInputSingle.addEventListener("change", (event) => {
  const file = event.target.files[0];
  if (file) loadSingleFile(file);
  event.target.value = "";
});

async function chooseFolder() {
  // Electron's native dialog has reliable access to folders outside the app
  // sandbox and reads every saved run without browser permission prompts.
  if (window.groundStation?.pickFlightFolder) {
    const selected = await window.groundStation.pickFlightFolder();
    if (!selected) return;
    folderRuns = Object.fromEntries(
      selected.runs.map((run) => [run.name, { kind: "path", path: run.path }]),
    );
    localStorage.setItem("airbrakes_last_folder_name", selected.folder);
    populateRunSelectAndLoad();
    return;
  }
  if (!FSA_SUPPORTED) {
    fileInputFolder.click();
    return;
  }
  try {
    const handle = await window.showDirectoryPicker();
    await idbSet("lastMode", "folder");
    await idbSet("folderHandle", handle);
    await loadFolderFromHandle(handle);
  } catch (_) {
    /* Picker cancellation is expected. */
  }
}
btnFolder.addEventListener("click", chooseFolder);
fileInputFolder.addEventListener("change", (event) => {
  const csvFiles = Array.from(event.target.files || []).filter(
    (file) => file.name.toLowerCase() === "data.csv",
  );
  if (!csvFiles.length) {
    folderNote.textContent =
      "No data.csv files found. Select the flight_data folder containing flight_* or ground_test_* folders.";
    return;
  }
  folderRuns = {};
  csvFiles.forEach((file) => {
    const parts = file.webkitRelativePath.split("/");
    folderRuns[parts.length > 1 ? parts.at(-2) : file.name] = file;
  });
  localStorage.setItem("airbrakes_last_folder_name", "flight_data");
  populateRunSelectAndLoad();
  event.target.value = "";
});
$("runSelect").addEventListener("change", (event) =>
  loadRun(event.target.value),
);
async function loadFolderFromHandle(directory) {
  folderRuns = {};
  for await (const [name, handle] of directory.entries()) {
    if (handle.kind === "directory") {
      try {
        folderRuns[name] = {
          kind: "handle",
          fileHandle: await handle.getFileHandle("data.csv"),
        };
      } catch (_) {
        /* Non-run directory. */
      }
    } else if (handle.kind === "file" && name.toLowerCase() === "data.csv")
      folderRuns[directory.name || name] = {
        kind: "handle",
        fileHandle: handle,
      };
  }
  localStorage.setItem(
    "airbrakes_last_folder_name",
    directory.name || "flight_data",
  );
  populateRunSelectAndLoad();
}
function populateRunSelectAndLoad() {
  const names = Object.keys(folderRuns).sort().reverse();
  if (!names.length) {
    folderNote.textContent =
      "No data.csv files were found in that folder or its run subfolders.";
    return;
  }
  const select = $("runSelect");
  select.replaceChildren(...names.map((name) => new Option(name, name)));
  $("runSection").hidden = false;
  folderNote.textContent = `Found ${names.length} run${names.length === 1 ? "" : "s"}.`;
  const last = localStorage.getItem("airbrakes_last_run"),
    load = last && names.includes(last) ? last : names[0];
  select.value = load;
  loadRun(load);
}
async function loadRun(name) {
  const entry = folderRuns[name];
  if (!entry) return;
  localStorage.setItem("airbrakes_last_run", name);
  $("runNote").textContent = name;
  try {
    if (entry instanceof File) loadSingleFile(entry, name);
    else if (entry?.kind === "handle")
      loadSingleFile(await entry.fileHandle.getFile(), name);
    else if (entry?.kind === "path") {
      const result = await window.groundStation.readCsv(entry.path);
      loadText(result.text, name);
    }
  } catch (_) {
    folderNote.textContent = `Couldn't read ${name}; the folder may have moved.`;
  }
}
function loadSingleFile(file, label) {
  const reader = new FileReader();
  reader.onload = (event) => loadText(event.target.result, label || file.name);
  reader.onerror = () => showLoadError("Could not read that file.");
  reader.readAsText(file);
}
function loadText(text, label) {
  const rows = parseCsvText(text);
  if (!rows.length) {
    showLoadError(
      "No valid rows found. Expected a CSV with a numeric time_ms column.",
    );
    return;
  }
  currentRows = rows;
  currentFileName = label;
  render();
}
function showLoadError(message) {
  folderNote.textContent = message;
  $("emptyState").hidden = false;
  $("chartsRoot").hidden = true;
  $("topActions").hidden = true;
}
function showRestoreBanner(handle, kind) {
  folderNote.replaceChildren(
    document.createTextNode("Resume where you left off:"),
    document.createElement("br"),
  );
  const button = document.createElement("button");
  button.className = "btn primary";
  button.textContent = `Resume "${handle.name}"`;
  button.addEventListener("click", async () => {
    try {
      if ((await handle.requestPermission({ mode: "read" })) === "granted") {
        if (kind === "folder") await loadFolderFromHandle(handle);
        else loadSingleFile(await handle.getFile(), handle.name);
      } else folderNote.append(" Permission not granted.");
    } catch (_) {
      folderNote.append(" Could not resume; choose it again.");
    }
  });
  folderNote.append(button);
}
async function tryRestoreSession() {
  if (!FSA_SUPPORTED) {
    const last = localStorage.getItem("airbrakes_last_run");
    if (last)
      folderNote.textContent = `Last session: ${last}. Re-select flight_data to jump back to it.`;
    return;
  }
  try {
    const mode = await idbGet("lastMode").catch(() => null);
    const key = mode === "folder" ? "folderHandle" : "fileHandle",
      handle = await idbGet(key).catch(() => null);
    if (!handle) return;
    if ((await handle.queryPermission({ mode: "read" })) === "granted") {
      if (mode === "folder") await loadFolderFromHandle(handle);
      else loadSingleFile(await handle.getFile(), handle.name);
    } else showRestoreBanner(handle, mode);
  } catch (_) {
    /* Stale handles simply leave the empty dashboard visible. */
  }
}

const PLOT_BG = "rgba(0,0,0,0)",
  FONT = { family: "'IBM Plex Mono',monospace", size: 11, color: "#7c8a96" },
  GRIDCOLOR = "#1c242b";
const AXIS_BASE = {
  gridcolor: GRIDCOLOR,
  zerolinecolor: "#293138",
  linecolor: "#293138",
  tickfont: FONT,
  showspikes: true,
  spikemode: "across",
  spikethickness: 1,
  spikecolor: "#4fd6c8",
  spikedash: "dot",
};
const plotConfig = {
  responsive: true,
  displaylogo: false,
  modeBarButtonsToRemove: ["lasso2d", "select2d"],
};
function baseLayout(overrides = {}) {
  return Object.assign(
    {
      paper_bgcolor: PLOT_BG,
      plot_bgcolor: PLOT_BG,
      font: FONT,
      margin: { l: 56, r: 20, t: 10, b: 36 },
      hovermode: "x unified",
      hoverlabel: {
        bgcolor: "#141a20",
        bordercolor: "#293138",
        font: { family: FONT.family, size: 11, color: "#dbe4ea" },
      },
      legend: { orientation: "h", y: 1.12, x: 0, font: FONT, bgcolor: PLOT_BG },
      xaxis: Object.assign({ title: "Time (s)" }, AXIS_BASE),
      yaxis: Object.assign({}, AXIS_BASE),
      shapes: [],
    },
    overrides,
  );
}
function stateShapes(rows, yref = "paper") {
  if (!rows.length || !("state_name" in rows[0])) return {};
  const shapes = [],
    annotations = [];
  let start = rows[0].time_s,
    state = rows[0].state_name;
  for (let i = 1; i <= rows.length; i++) {
    const row = rows[i],
      next = row ? row.state_name : null;
    if (next !== state) {
      const end = rows[i - 1].time_s;
      shapes.push({
        type: "rect",
        xref: "x",
        yref,
        x0: start,
        x1: end,
        y0: 0,
        y1: 1,
        fillcolor: colorForState(state),
        opacity: 0.07,
        line: { width: 0 },
      });
      if (end > start)
        annotations.push({
          x: (start + end) / 2,
          xref: "x",
          y: 1,
          yref,
          text: state.replace(/^STATE_/, "").replace(/^GROUND_TEST_/, "GND "),
          showarrow: false,
          yanchor: "bottom",
          font: { ...FONT, size: 9, color: colorForState(state) },
          bgcolor: "rgba(10,13,16,.72)",
          borderpad: 2,
          captureevents: false,
        });
      if (row) {
        start = row.time_s;
        state = next;
      }
    }
  }
  return { shapes, annotations };
}
function rangesEqual(a, b) {
  return (
    !!a && !!b && Math.abs(a[0] - b[0]) < 1e-9 && Math.abs(a[1] - b[1]) < 1e-9
  );
}
function makePlot(id, traces, layout) {
  Plotly.newPlot(id, traces, layout, plotConfig);
  chartIds.push(id);
  $(id).on("plotly_relayout", (event) => {
    if (pendingSync.has(id)) return;
    const reset = event["xaxis.autorange"] === true,
      hasRange = "xaxis.range[0]" in event && "xaxis.range[1]" in event;
    if (!reset && !hasRange) return;
    const range = hasRange
      ? [event["xaxis.range[0]"], event["xaxis.range[1]"]]
      : null;
    chartIds.forEach((otherId) => {
      if (otherId === id || pendingSync.has(otherId)) return;
      const gd = $(otherId);
      if (!gd?.layout?.xaxis) return;
      if (reset) {
        if (gd.layout.xaxis.autorange === true) return;
        pendingSync.add(otherId);
        Plotly.relayout(otherId, { "xaxis.autorange": true })
          .catch(() => {})
          .finally(() => pendingSync.delete(otherId));
      } else if (range && !rangesEqual(gd.layout.xaxis.range, range)) {
        pendingSync.add(otherId);
        Plotly.relayout(otherId, { "xaxis.range": range })
          .catch(() => {})
          .finally(() => pendingSync.delete(otherId));
      }
    });
  });
}
function panel(root, index, title, subtitle, id, height = "") {
  const wrap = document.createElement("section");
  wrap.className = "panel";
  wrap.innerHTML = `<div class="panel-head"><div class="panel-title"><span class="idx">${index}</span>${title}</div></div><div class="panel-sub">${subtitle || ""}</div><div class="chart ${height}" id="${id}"></div>`;
  root.append(wrap);
}
const fmt = (number, digits = 2) =>
  Number.isFinite(number) ? number.toFixed(digits) : "—";
const hasCol = (rows, column) =>
  rows.some((row) => Number.isFinite(row[column]));
function render() {
  const rows = currentRows.filter((row) => Number.isFinite(row.time_s));
  if (!rows.length)
    return showLoadError("No valid time-series data was found.");
  $("emptyState").hidden = true;
  $("chartsRoot").hidden = false;
  $("topActions").hidden = false;
  $("pageTitle").textContent = currentFileName.replace(/\.csv$/i, "");
  $("pageFile").textContent =
    `${rows.length.toLocaleString()} rows · ${fmt(rows.at(-1).time_s - rows[0].time_s, 1)} s duration`;
  buildSummary(rows);
  buildStateList(rows);
  buildCharts(rows);
}
function buildSummary(rows) {
  const values = (column) =>
      rows.map((row) => row[column]).filter(Number.isFinite),
    alt = values("altitude_m"),
    velocity = values("velocity_ms"),
    battery = values("battery_voltage"),
    cd = values("Cd"),
    duration = rows.at(-1).time_s - rows[0].time_s;
  const apogeeIndex = rows.reduce(
      (best, row, index) =>
        Number.isFinite(row.altitude_m) &&
        (!Number.isFinite(rows[best]?.altitude_m) ||
          row.altitude_m > rows[best].altitude_m)
          ? index
          : best,
      0,
    ),
    samples = rows
      .slice(1)
      .map((row, index) => row.time_ms - rows[index].time_ms),
    averageDt = samples.length
      ? samples.reduce((a, b) => a + b, 0) / samples.length
      : NaN,
    minBattery = battery.length ? Math.min(...battery) : NaN,
    maxBattery = battery.length ? Math.max(...battery) : NaN;
  const stats = [
    ["Duration", `${fmt(duration, 1)} s`],
    [
      "Sample rate",
      Number.isFinite(averageDt) ? `${fmt(1000 / averageDt, 0)} Hz` : "—",
    ],
    ["Max altitude", `${fmt(alt.length ? Math.max(...alt) : NaN, 2)} m`],
    ["Time to apogee", `${fmt(rows[apogeeIndex]?.time_s, 2)} s`],
    [
      "Max velocity",
      `${fmt(velocity.length ? Math.max(...velocity) : NaN, 2)} m/s`,
    ],
    [
      "Cd range",
      cd.length ? `${fmt(Math.min(...cd), 2)}–${fmt(Math.max(...cd), 2)}` : "—",
    ],
    [
      "Battery",
      battery.length ? `${fmt(minBattery, 2)}–${fmt(maxBattery, 2)} V` : "—",
      maxBattery - minBattery > 0.5 ? "warn" : "",
    ],
    ["Rows", rows.length.toLocaleString()],
  ];
  $("statGrid").replaceChildren(
    ...stats.map(([label, value, style]) => {
      const card = document.createElement("div");
      card.className = "stat";
      card.innerHTML = `<div class="k">${label}</div><div class="v ${style || ""}">${value}</div>`;
      return card;
    }),
  );
  $("statsSection").hidden = false;
}
function buildStateList(rows) {
  if (!("state_name" in rows[0])) {
    $("statesSection").hidden = true;
    return;
  }
  const durations = {};
  rows.forEach((row, index) => {
    durations[row.state_name] =
      (durations[row.state_name] || 0) +
      (index ? row.time_s - rows[index - 1].time_s : 0);
  });
  $("stateList").replaceChildren(
    ...Object.entries(durations)
      .sort((a, b) => b[1] - a[1])
      .map(([name, duration]) => {
        const row = document.createElement("div");
        row.className = "state-chip";
        row.innerHTML = `<span><span class="state-dot" style="background:${colorForState(name)}"></span>${name}</span><span>${fmt(duration, 1)}s</span>`;
        return row;
      }),
  );
  $("statesSection").hidden = false;
}
function buildCharts(rows) {
  chartIds = [];
  const root = $("chartsRoot");
  Plotly.purge?.(root);
  root.replaceChildren();
  const x = rows.map((row) => row.time_s),
    overlay = stateShapes(rows);
  let index = 1;
  const add = (condition, title, subtitle, id, height) => {
    if (condition) panel(root, index++, title, subtitle, id, height);
  };
  add(
    hasCol(rows, "altitude_m") || hasCol(rows, "raw_baro_m"),
    "Altitude",
    "Kalman-filtered altitude vs raw barometer reading",
    "c_alt",
    "tall",
  );
  add(
    hasCol(rows, "velocity_ms"),
    "Vertical velocity",
    "Estimated velocity from the fused Kalman filter",
    "c_vel",
  );
  add(
    hasCol(rows, "raw_accel_ms2") || hasCol(rows, "vertical_accel_ms2"),
    "Acceleration",
    "Raw accel, world-frame vertical accel, and estimated accel bias",
    "c_accel",
  );
  add(
    hasCol(rows, "motor_pos") || hasCol(rows, "motor_cmd_pos"),
    "Airbrake motor position",
    "Actual encoder position vs commanded setpoint",
    "c_motorpos",
    "tall",
  );
  add(
    hasCol(rows, "motor_vel"),
    "Airbrake motor velocity",
    "Actuator slew rate",
    "c_motorvel",
    "short",
  );
  add(
    hasCol(rows, "Cd") || hasCol(rows, "desired_Cd"),
    "Drag coefficient tracking",
    "Actual Cd vs the Cd the controller is solving for",
    "c_cd",
    "tall",
  );
  add(
    hasCol(rows, "roll_rad") ||
      hasCol(rows, "pitch_rad") ||
      hasCol(rows, "yaw_rad"),
    "Orientation",
    "Roll / pitch / yaw from the quaternion attitude filter",
    "c_orient",
  );
  add(
    hasCol(rows, "motor_current") || hasCol(rows, "battery_voltage"),
    "Power",
    "Motor current draw and battery voltage",
    "c_power",
  );
  add(
    (hasCol(rows, "motor_cmd_pos") && hasCol(rows, "motor_pos")) ||
      (hasCol(rows, "desired_Cd") && hasCol(rows, "Cd")),
    "Control loop error",
    "Commanded minus actual — how tightly each loop is tracking",
    "c_err",
    "tall",
  );
  add(
    "state_name" in rows[0],
    "Flight state timeline",
    "Which state machine phase was active over time",
    "c_state",
    "short",
  );
  add(
    hasCol(rows, "motor_pos") && hasCol(rows, "motor_vel"),
    "Actuator phase portrait",
    "Motor position vs velocity, colored by time — reveals actuation cycles",
    "c_phase",
  );
  const trace = (column, name, color, width = 1.4, extra = {}) => ({
    x,
    y: rows.map((row) => row[column]),
    name,
    mode: "lines",
    line: { color, width, ...extra },
  });
  if ($("c_alt")) {
    const traces = [];
    if (hasCol(rows, "raw_baro_m"))
      traces.push({
        ...trace("raw_baro_m", "Raw baro", "#ff5d73", 1),
        opacity: 0.55,
      });
    if (hasCol(rows, "altitude_m"))
      traces.push(trace("altitude_m", "Filtered altitude", "#4fd6c8", 2));
    makePlot(
      "c_alt",
      traces,
      baseLayout({
        ...overlay,
        yaxis: Object.assign({ title: "Altitude (m)" }, AXIS_BASE),
      }),
    );
  }
  if ($("c_vel"))
    makePlot(
      "c_vel",
      [trace("velocity_ms", "Velocity", "#4fd6c8", 1.6)],
      baseLayout({
        ...overlay,
        yaxis: Object.assign({ title: "Velocity (m/s)" }, AXIS_BASE),
      }),
    );
  if ($("c_accel")) {
    const traces = [];
    if (hasCol(rows, "raw_accel_ms2"))
      traces.push({
        ...trace("raw_accel_ms2", "Raw accel", "#4b5761", 1),
        opacity: 0.5,
      });
    if (hasCol(rows, "vertical_accel_ms2"))
      traces.push(trace("vertical_accel_ms2", "Vertical accel", "#4fd6c8"));
    if (hasCol(rows, "accel_bias_ms2"))
      traces.push(trace("accel_bias_ms2", "Accel bias", "#ff5d73", 1.8));
    makePlot(
      "c_accel",
      traces,
      baseLayout({
        ...overlay,
        yaxis: Object.assign({ title: "Accel (m/s²)" }, AXIS_BASE),
      }),
    );
  }
  if ($("c_motorpos")) {
    const traces = [];
    if (hasCol(rows, "motor_cmd_pos"))
      traces.push(
        trace("motor_cmd_pos", "Commanded", "#ffb454", 1.6, { dash: "dot" }),
      );
    if (hasCol(rows, "motor_pos"))
      traces.push(trace("motor_pos", "Actual", "#4fd6c8", 1.8));
    makePlot(
      "c_motorpos",
      traces,
      baseLayout({
        ...overlay,
        yaxis: Object.assign({ title: "Position" }, AXIS_BASE),
      }),
    );
  }
  if ($("c_motorvel"))
    makePlot(
      "c_motorvel",
      [trace("motor_vel", "Motor velocity", "#8f7bff", 1.2)],
      baseLayout({
        ...overlay,
        yaxis: Object.assign({ title: "Velocity" }, AXIS_BASE),
      }),
    );
  if ($("c_cd")) {
    const traces = [];
    if (hasCol(rows, "desired_Cd"))
      traces.push(
        trace("desired_Cd", "Desired Cd", "#ffb454", 1.8, { dash: "dot" }),
      );
    if (hasCol(rows, "Cd")) traces.push(trace("Cd", "Actual Cd", "#4fd6c8", 2));
    makePlot(
      "c_cd",
      traces,
      baseLayout({
        ...overlay,
        yaxis: Object.assign({ title: "Cd" }, AXIS_BASE),
      }),
    );
  }
  if ($("c_orient")) {
    const traces = [];
    if (hasCol(rows, "roll_rad"))
      traces.push(trace("roll_rad", "Roll", "#4fd6c8", 1.3));
    if (hasCol(rows, "pitch_rad"))
      traces.push(trace("pitch_rad", "Pitch", "#ffb454", 1.3));
    if (hasCol(rows, "yaw_rad"))
      traces.push(trace("yaw_rad", "Yaw", "#8f7bff", 1.3));
    makePlot(
      "c_orient",
      traces,
      baseLayout({
        ...overlay,
        yaxis: Object.assign({ title: "Angle (rad)" }, AXIS_BASE),
      }),
    );
  }
  if ($("c_power")) {
    const traces = [];
    if (hasCol(rows, "motor_current"))
      traces.push({
        ...trace("motor_current", "Motor current (A)", "#4fd6c8", 1.3),
        yaxis: "y",
      });
    if (hasCol(rows, "battery_voltage"))
      traces.push({
        ...trace("battery_voltage", "Battery voltage (V)", "#ffb454", 1.6),
        yaxis: "y2",
      });
    makePlot(
      "c_power",
      traces,
      baseLayout({
        ...overlay,
        yaxis: Object.assign({ title: "Current (A)" }, AXIS_BASE),
        yaxis2: Object.assign(
          { title: "Voltage (V)", overlaying: "y", side: "right" },
          AXIS_BASE,
          { gridcolor: PLOT_BG },
        ),
      }),
    );
  }
  if ($("c_err")) {
    const traces = [];
    if (hasCol(rows, "motor_cmd_pos") && hasCol(rows, "motor_pos"))
      traces.push({
        x,
        y: rows.map((row) => row.motor_cmd_pos - row.motor_pos),
        name: "Motor pos error",
        mode: "lines",
        line: { color: "#ff5d73", width: 1.3 },
        yaxis: "y",
      });
    if (hasCol(rows, "desired_Cd") && hasCol(rows, "Cd"))
      traces.push({
        x,
        y: rows.map((row) => row.desired_Cd - row.Cd),
        name: "Cd error",
        mode: "lines",
        line: { color: "#4fd6c8", width: 1.3 },
        yaxis: "y2",
      });
    makePlot(
      "c_err",
      traces,
      baseLayout({
        ...overlay,
        yaxis: Object.assign({ title: "Motor error" }, AXIS_BASE),
        yaxis2: Object.assign(
          { title: "Cd error", overlaying: "y", side: "right" },
          AXIS_BASE,
          { gridcolor: PLOT_BG },
        ),
      }),
    );
  }
  if ($("c_state")) {
    const segments = [];
    let start = rows[0].time_s,
      state = rows[0].state_name;
    for (let i = 1; i <= rows.length; i++) {
      const row = rows[i],
        next = row ? row.state_name : null;
      if (next !== state) {
        segments.push({ start, end: rows[i - 1].time_s, state });
        if (row) {
          start = row.time_s;
          state = next;
        }
      }
    }
    makePlot(
      "c_state",
      segments.map((segment) => ({
        x: [segment.end - segment.start],
        y: ["STATE"],
        base: [segment.start],
        type: "bar",
        orientation: "h",
        name: segment.state,
        marker: { color: colorForState(segment.state) },
        hovertemplate: `${segment.state}<br>%{base:.2f}s → %{x:.2f}s<extra></extra>`,
        showlegend: false,
        text: segment.state,
        textposition: "inside",
        insidetextanchor: "middle",
        textfont: { size: 10, color: "#0a0d10", family: FONT.family },
      })),
      baseLayout({
        barmode: "stack",
        yaxis: Object.assign({ title: "", showticklabels: false }, AXIS_BASE),
      }),
    );
  }
  if ($("c_phase"))
    Plotly.newPlot(
      "c_phase",
      [
        {
          x: rows.map((row) => row.motor_pos),
          y: rows.map((row) => row.motor_vel),
          mode: "markers",
          marker: {
            size: 4,
            color: x,
            colorscale: [
              [0, "#293138"],
              [0.5, "#4fd6c8"],
              [1, "#ffb454"],
            ],
            showscale: true,
            colorbar: {
              title: "time (s)",
              titlefont: FONT,
              tickfont: FONT,
              outlinewidth: 0,
            },
          },
          hovertemplate: "pos %{x:.2f}<br>vel %{y:.2f}<extra></extra>",
        },
      ],
      baseLayout({
        xaxis: Object.assign({ title: "Motor position" }, AXIS_BASE),
        yaxis: Object.assign({ title: "Motor velocity" }, AXIS_BASE),
      }),
      plotConfig,
    );
}
$("btnResetZoom").addEventListener("click", () =>
  chartIds.forEach((id) => {
    if (pendingSync.has(id)) return;
    pendingSync.add(id);
    Plotly.relayout(id, { "xaxis.autorange": true, "yaxis.autorange": true })
      .catch(() => {})
      .finally(() => pendingSync.delete(id));
  }),
);
window.airbrakesAnalytics = {
  parseCsvText,
  loadText: (text, name = "data.csv") => loadText(text, name),
  getChartIds: () => [...chartIds],
};
tryRestoreSession();
})();
