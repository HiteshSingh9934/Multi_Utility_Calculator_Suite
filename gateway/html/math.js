/* Calculator Suite: maths, graphs and 3D.
 *
 *   /api/math/*    -> math-service    scientific calculator, function plotter, 3D graphs,
 *                                     calculus, statistics and 3D shapes
 *   /api/matrix/*  -> matrix-service  matrices and 3D vectors
 *
 * Charts are drawn with Plotly (vendor/plotly.min.js), loaded the first time one is needed.
 * Shared helpers come from app.js (window.Suite); each tool registers itself on window.SuiteTools.
 */
(() => {
  "use strict";

  const S = window.Suite;
  const { $, $$, submit, render, esc, num, numHTML, cleanNumber, answeredBy } = S;

  // ------------------------------------------------------------------
  // Chart style, one set per theme. Series colours are a validated categorical
  // palette stepped for each theme's chart surface (same hues, fixed order);
  // 3D heights use one blue ramp, dark-to-light on Slate and light-to-dark on Paper.
  // ------------------------------------------------------------------

  const THEMES = {
    dark: {
      series: ["#3987e5", "#d95926", "#199e70", "#c98500"],
      ink: { text: "#eceef2", secondary: "#a8afbc", muted: "#868e9c", grid: "#2a303a", axis: "#3a414d",
        surface: "#0f1115", raised: "#232833", edge: "#9ec5f4", plane: "#5b6270",
        fill: "rgba(57, 135, 229, 0.16)", fillKey: "rgba(57, 135, 229, 0.45)" },
      ramp: [[0, "#184f95"], [0.2, "#256abf"], [0.4, "#3987e5"], [0.6, "#6da7ec"], [0.8, "#9ec5f4"], [1, "#cde2fb"]],
      shade: [[0, "#123764"], [0.55, "#3987e5"], [1, "#b6d4f7"]],
    },
    light: {
      series: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"],
      ink: { text: "#161a21", secondary: "#4a5262", muted: "#5f6878", grid: "#e4e7ec", axis: "#c6ccd5",
        surface: "#fafbfc", raised: "#ffffff", edge: "#0d366b", plane: "#98a1b0",
        fill: "rgba(42, 120, 214, 0.13)", fillKey: "rgba(42, 120, 214, 0.4)" },
      ramp: [[0, "#b7d3f6"], [0.2, "#86b6ef"], [0.4, "#5598e7"], [0.6, "#2a78d6"], [0.8, "#1c5cab"], [1, "#0d366b"]],
      shade: [[0, "#1c4f8f"], [0.55, "#4d93e8"], [1, "#dbe9fb"]],
    },
  };

  // Filled in by useTheme(); everything below reads these, so a theme switch only has to redraw
  const SERIES = [];
  const INK = {};
  const RAMP = [];
  const SHADE = [];

  function useTheme(name) {
    const theme = THEMES[name] || THEMES.dark;
    SERIES.splice(0, SERIES.length, ...theme.series);
    Object.assign(INK, theme.ink);
    RAMP.splice(0, RAMP.length, ...theme.ramp);
    SHADE.splice(0, SHADE.length, ...theme.shade);
  }
  useTheme(document.documentElement.dataset.theme === "light" ? "light" : "dark");
  const FONT = '"IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif';
  const CONFIG = {
    displaylogo: false,
    responsive: true,
    modeBarButtonsToRemove: ["select2d", "lasso2d", "autoScale2d", "toggleSpikelines",
      "hoverClosestCartesian", "hoverCompareCartesian"],
    toImageButtonOptions: { format: "png", filename: "calculator-suite", scale: 2 },
  };
  const hover = () => ({ bgcolor: INK.raised, bordercolor: INK.axis, font: { family: FONT, color: INK.text, size: 13 } });

  function axis2d(title, extra = {}) {
    return {
      title: { text: title, font: { color: INK.muted, size: 13 }, standoff: 8 },
      color: INK.muted, gridcolor: INK.grid, gridwidth: 1, zerolinecolor: INK.axis, zerolinewidth: 1.5,
      linecolor: INK.axis, tickfont: { color: INK.muted, size: 12 }, automargin: true, ...extra,
    };
  }

  function layout2d(extra = {}) {
    return {
      paper_bgcolor: INK.surface, plot_bgcolor: INK.surface,
      font: { family: FONT, color: INK.secondary, size: 13 },
      margin: { l: 56, r: 24, t: 20, b: 48 },
      hovermode: "closest", hoverlabel: hover(), showlegend: false,
      modebar: { bgcolor: "rgba(0,0,0,0)", color: INK.muted, activecolor: INK.text },
      ...extra,
    };
  }

  function axis3d(title, extra = {}) {
    return {
      title: { text: title, font: { color: INK.secondary, size: 13 } },
      backgroundcolor: INK.surface, showbackground: true, gridcolor: INK.grid, zerolinecolor: INK.axis,
      linecolor: INK.axis, color: INK.muted, tickfont: { color: INK.muted, size: 11 }, ...extra,
    };
  }

  function layout3d(scene = {}, extra = {}) {
    return {
      paper_bgcolor: INK.surface,
      font: { family: FONT, color: INK.secondary, size: 13 },
      margin: { l: 0, r: 0, t: 0, b: 0 },
      hoverlabel: hover(), showlegend: false,
      modebar: { bgcolor: "rgba(0,0,0,0)", color: INK.muted, activecolor: INK.text },
      scene: {
        xaxis: axis3d("x"), yaxis: axis3d("y"), zaxis: axis3d("z"),
        aspectmode: "cube", camera: { eye: { x: 1.5, y: 1.5, z: 0.95 } }, ...scene,
      },
      ...extra,
    };
  }

  const singleColour = (colour) => [[0, colour], [1, colour]];
  const LIGHTING = { ambient: 0.55, diffuse: 0.75, specular: 0.2, roughness: 0.55, fresnel: 0.15 };
  const LIGHT_FROM = { x: -6000, y: 10000, z: 10000 };
  const VIEW = [0.7, 0.59, 0.4];   // the direction the camera looks from (a unit vector)

  // Scene proportions that match the model (within limits, so a thin model stays visible), and a
  // camera distance that fits the model's outline into the chart, whatever the chart's shape.
  function fitScene(traces, minRatio, el) {
    const lo = [Infinity, Infinity, Infinity];
    const hi = [-Infinity, -Infinity, -Infinity];
    traces.forEach((trace) => ["x", "y", "z"].forEach((axis, i) => {
      const values = trace[axis];
      if (!values) return;
      (Array.isArray(values[0]) ? values.flat() : values).forEach((v) => {
        if (typeof v === "number" && Number.isFinite(v)) {
          if (v < lo[i]) lo[i] = v;
          if (v > hi[i]) hi[i] = v;
        }
      });
    }));
    const size = lo.map((low, i) => (Number.isFinite(low) ? hi[i] - low : 0));
    const largest = Math.max(...size) || 1;
    const ratio = size.map((s) => Math.max(minRatio, s / largest));
    // How big the box looks from VIEW: its width across, and its height (the view is 24° above level)
    const across = Math.hypot(ratio[0], ratio[1]);
    const high = ratio[2] * 0.92 + across * 0.4;
    const chartShape = el && el.clientHeight ? el.clientWidth / el.clientHeight : 1.8;
    const distance = Math.max(1.8, high / 0.56, across / (0.6 * chartShape));
    return {
      aspectmode: "manual", aspectratio: { x: ratio[0], y: ratio[1], z: ratio[2] },
      camera: { eye: { x: VIEW[0] * distance, y: VIEW[1] * distance, z: VIEW[2] * distance } },
    };
  }

  // z = f(x, y): x and y in proportion, heights scaled to a readable box
  function surfaceScene(data) {
    const xr = Math.abs(data.x[data.x.length - 1] - data.x[0]) || 1;
    const yr = Math.abs(data.y[data.y.length - 1] - data.y[0]) || 1;
    return {
      aspectmode: "manual", aspectratio: { x: 1, y: Math.min(2, Math.max(0.5, yr / xr)), z: 0.6 },
      camera: { eye: { x: 1.45, y: 1.3, z: 1.0 } },
    };
  }

  // ------------------------------------------------------------------
  // Plotly: loaded on demand (it's 1.5 MB), and cleaned up before results are replaced
  // ------------------------------------------------------------------

  let plotlyLoading = null;

  function loadPlotly() {
    if (window.Plotly) return Promise.resolve(window.Plotly);
    if (!plotlyLoading) {
      plotlyLoading = new Promise((resolve, reject) => {
        const script = document.createElement("script");
        script.src = "vendor/plotly.min.js";
        script.onload = () => resolve(window.Plotly);
        script.onerror = () => { plotlyLoading = null; reject(new Error("Plotly didn't load")); };
        document.head.appendChild(script);
      });
    }
    return plotlyLoading;
  }

  const resultBox = (tool) => $(`#result-${tool}`);

  function purge(tool) {
    if (!window.Plotly) return;
    $$(".js-plotly-plot", resultBox(tool)).forEach((el) => window.Plotly.purge(el));   // frees WebGL contexts
  }

  function show(tool, html) {
    if (tool === "graph3d") stopSpin();
    purge(tool);
    render(tool, html);
  }

  async function draw(el, traces, layout) {
    if (!el) return null;
    el.classList.add("loading");
    el.textContent = "Loading the graph…";
    let Plotly;
    try {
      Plotly = await loadPlotly();
    } catch (err) {
      el.classList.remove("loading");
      el.innerHTML = '<p class="chart-error">The chart library didn’t load, so the graph can’t be drawn. Refresh the page to try again.</p>';
      return null;
    }
    if (!el.isConnected) return null;     // a newer result replaced this one while Plotly loaded
    el.classList.remove("loading");
    el.textContent = "";
    await Plotly.newPlot(el, traces, layout, CONFIG);
    return el;
  }

  // How to draw each tool's latest result again (with the current theme's colours)
  const redraw = {};
  const stale = new Set();

  // Redraw a tool's chart if the theme changed since it was drawn; returns true if it did
  function refresh(tool) {
    if (!stale.has(tool)) return false;
    stale.delete(tool);
    if (!redraw[tool] || !$(".js-plotly-plot", resultBox(tool))) return false;
    redraw[tool]();
    return true;
  }

  function shown(tool) {
    if (!refresh(tool)) resizeCharts(tool);
  }

  function resizeCharts(tool) {
    if (!window.Plotly) return;
    $$(".js-plotly-plot", resultBox(tool)).forEach((el) => window.Plotly.Plots.resize(el));
  }

  // ------------------------------------------------------------------
  // Small helpers
  // ------------------------------------------------------------------

  const sig = new Intl.NumberFormat("en-IN", { maximumSignificantDigits: 10 });

  function full(n) {   // up to 10 significant digits, as a calculator shows
    if (n === null || n === undefined || !Number.isFinite(n)) return "–";
    if (n !== 0 && (Math.abs(n) >= 1e15 || Math.abs(n) < 1e-7)) {
      const [mantissa, exponent] = n.toExponential(8).split("e");
      return `${S.useMinus(String(parseFloat(mantissa)))} × 10^${S.useMinus(String(parseInt(exponent, 10)))}`;
    }
    return S.useMinus(sig.format(n));
  }

  function fullHTML(n) {
    const text = esc(full(n));
    return text.replace(/10\^([−\d]+)$/, "10<sup>$1</sup>");
  }

  const vecText = (v) => `(${v.map((c) => num(c)).join(", ")})`;
  const pointText = (x, y) => `(${num(x)}, ${num(y)})`;
  const errorBox = (message) => `<div class="error-box"><strong>Check the input</strong>${esc(message)}</div>`;

  // "3x^2 − e^(−x)" -> 3x<sup>2</sup> − e<sup>−x</sup>: powers written the way a textbook does
  function mathHTML(text) {
    text = String(text ?? "");
    let out = "";
    let i = 0;
    while (i < text.length) {
      if (text[i] === "^" && text[i + 1] === "(") {
        let depth = 0;
        let j = i + 1;
        for (; j < text.length; j += 1) {
          if (text[j] === "(") depth += 1;
          if (text[j] === ")" && --depth === 0) break;
        }
        if (j < text.length) {
          out += `<sup>${mathHTML(text.slice(i + 2, j))}</sup>`;
          i = j + 1;
          continue;
        }
      } else if (text[i] === "^") {
        const power = /^[−-]?(\d+(\.\d+)?|[A-Za-zπλ])/.exec(text.slice(i + 1));
        if (power) {
          out += `<sup>${esc(power[0])}</sup>`;
          i += 1 + power[0].length;
          continue;
        }
      }
      out += esc(text[i]);
      i += 1;
    }
    return out;
  }

  function tile(label, value, sub = "", wide = false) {
    return `<div class="tile${wide ? " wide" : ""}"><p class="tile-label">${label}</p><p class="tile-value">${value}</p>${sub ? `<p class="tile-sub">${sub}</p>` : ""}</div>`;
  }

  // "2pi", "-pi/2" or "1.5π" -> a number; anything else is sent as typed, so the service can explain the problem
  function bound(text) {
    const raw = cleanNumber(text).toLowerCase().replace(/π/g, "pi");
    if (raw === "") return "";
    const match = raw.match(/^(-?)(\d*\.?\d*)\*?pi(?:\/(\d*\.?\d+))?$/);
    if (match) {
      const coefficient = match[2] === "" ? 1 : Number(match[2]);
      const divisor = match[3] ? Number(match[3]) : 1;
      if (Number.isFinite(coefficient) && divisor) return (match[1] ? -1 : 1) * coefficient * Math.PI / divisor;
    }
    return Number.isFinite(Number(raw)) ? Number(raw) : text;
  }

  function presetsHTML(items) {
    return items.map((item, i) => `<button class="preset" type="button" data-preset="${i}">${esc(item.label || item)}</button>`).join("");
  }

  const setRadio = (form, name, value) => {
    const radio = $(`input[name="${name}"][value="${value}"]`, form);
    if (radio) radio.checked = true;
  };

  const finePointer = window.matchMedia("(pointer: fine)").matches;
  // Graphs loaded back from the history panel are redrawn (straight from the Redis cache) without saving them again
  const fromHistory = { plotter: false, graph3d: false };

  // ==================================================================
  // Scientific calculator
  // ==================================================================

  const sciForm = $("#form-scientific");
  const sciInput = $("#sci-expression");
  let lastAnswer = null;

  $("#sci-keypad").addEventListener("click", (event) => {
    const key = event.target.closest("button.key");
    if (!key || key.type === "submit") return;
    const start = sciInput.selectionStart ?? sciInput.value.length;
    const end = sciInput.selectionEnd ?? start;
    if (key.dataset.action === "clear") {
      sciInput.value = "";
      show("scientific", "");
    } else if (key.dataset.action === "back") {
      if (start !== end) sciInput.setRangeText("", start, end, "end");
      else if (start > 0) sciInput.setRangeText("", start - 1, start, "end");
    } else {
      sciInput.setRangeText(key.dataset.insert, start, end, "end");
    }
    if (finePointer) sciInput.focus();
  });

  sciForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = { expression: sciInput.value, angle: sciForm.angle.value };
    if (lastAnswer !== null) body.ans = lastAnswer;
    const data = await submit("scientific", sciForm, "/api/math/evaluate", body, { beforeError: () => purge("scientific") });
    if (!data) return;
    lastAnswer = data.result;
    const note = data.uses_angles ? `Angles in ${data.angle === "deg" ? "degrees" : "radians"}. ` : "";
    show("scientific", `
      <div class="readout fresh">
        <p class="readout-label">${mathHTML(data.interpreted)} =</p>
        <p class="readout-value">${fullHTML(data.result)}</p>
        <p class="readout-sub">${note}Ans now holds this answer.</p>
        ${answeredBy("math", data)}
      </div>`);
  });

  // ==================================================================
  // Function plotter
  // ==================================================================

  const plotForm = $("#form-plotter");
  const fnRowsEl = $("#fn-rows");
  const MAX_FUNCTIONS = 4;
  // Each function keeps its slot (and so its colour) even when others are removed
  let fnRows = [{ slot: 0, value: "sin(x)" }, { slot: 1, value: "x^2/8 - 2" }];
  const PLOT_PRESETS = ["sin(x)", "cos(x)", "tan(x)", "x^2 - 4", "x^3 - 3x", "e^x", "ln(x)", "1/x", "sqrt(x)",
    "abs(x)", "sin(x)/x", "floor(x)"];

  function readFunctions() {
    $$(".fn-row", fnRowsEl).forEach((row) => {
      const entry = fnRows.find((f) => f.slot === Number(row.dataset.slot));
      if (entry) entry.value = $("input", row).value;
    });
  }

  function drawFunctionRows(focusSlot) {
    fnRowsEl.innerHTML = fnRows.map((f) => `
      <div class="fn-row" data-slot="${f.slot}">
        <span class="series-key" style="--series: ${SERIES[f.slot]}"></span>
        <label class="fn-label" for="fn-${f.slot}">f<sub>${f.slot + 1}</sub>(x) =</label>
        <input id="fn-${f.slot}" type="text" autocomplete="off" spellcheck="false" autocapitalize="off" value="${esc(f.value)}">
        <button class="button-icon remove" type="button" aria-label="Remove f${f.slot + 1}" title="Remove">
          <svg class="icon"><use href="#i-close"/></svg>
        </button>
      </div>`).join("");
    $("#fn-add").disabled = fnRows.length >= MAX_FUNCTIONS;
    if (focusSlot !== undefined) {
      const input = $(`#fn-${focusSlot}`);
      if (input) input.focus();
    }
  }

  function addFunction(value = "") {
    readFunctions();
    if (fnRows.length >= MAX_FUNCTIONS) return;
    const used = new Set(fnRows.map((f) => f.slot));
    const slot = [0, 1, 2, 3].find((s) => !used.has(s));
    fnRows.push({ slot, value });
    fnRows.sort((a, b) => a.slot - b.slot);
    drawFunctionRows(slot);
  }

  $("#fn-add").addEventListener("click", () => addFunction(""));

  fnRowsEl.addEventListener("click", (event) => {
    const button = event.target.closest(".remove");
    if (!button) return;
    readFunctions();
    const slot = Number(button.closest(".fn-row").dataset.slot);
    fnRows = fnRows.filter((f) => f.slot !== slot);
    if (!fnRows.length) fnRows = [{ slot: 0, value: "" }];
    drawFunctionRows();
  });

  $("#plotter-presets").innerHTML = presetsHTML(PLOT_PRESETS);
  $("#plotter-presets").addEventListener("click", (event) => {
    const button = event.target.closest("[data-preset]");
    if (!button) return;
    const value = PLOT_PRESETS[Number(button.dataset.preset)];
    readFunctions();
    const empty = fnRows.find((f) => !f.value.trim());
    if (empty) {
      empty.value = value;
      drawFunctionRows();
    } else if (fnRows.length < MAX_FUNCTIONS) {
      addFunction(value);
    } else {
      fnRows[fnRows.length - 1].value = value;
      drawFunctionRows();
    }
  });

  function keyPointsRow(series, slot) {
    const roots = series.roots.length
      ? series.roots.map((r) => num(r)).join(", ") + (series.more_roots ? " and more" : "")
      : "None in this range";
    const turning = series.extrema.length
      ? series.extrema.map((e) => `${e.kind === "max" ? "Max" : "Min"} ${pointText(e.x, e.y)}`).join(", ") + (series.more_extrema ? " and more" : "")
      : "None in this range";
    const intercept = series.y_intercept === null ? "–" : num(series.y_intercept);
    return `<tr>
      <td><span class="chart-caption"><span><i class="series-key" style="--series:${SERIES[slot]}"></i>f<sub>${slot + 1}</sub></span></span></td>
      <td class="text">${esc(roots)}</td><td class="text">${esc(turning)}</td><td>${esc(intercept)}</td></tr>`;
  }

  function plotTraces(data, slots) {
    const traces = [];
    data.series.forEach((s, i) => {
      const slot = slots[i];
      const colour = SERIES[slot];
      const name = `f${slot + 1}(x)`;
      const ring = { color: INK.surface, width: 2 };
      traces.push({ type: "scatter", mode: "lines", x: data.x, y: s.y, name, connectgaps: false,
        line: { color: colour, width: 2 }, hovertemplate: `${name} = %{y:.6g}<extra></extra>` });
      const markers = (points, symbol, label, size = 10) => {
        if (!points.length) return;
        traces.push({ type: "scatter", mode: "markers", x: points.map((p) => p[0]), y: points.map((p) => p[1]),
          name: `${name} ${label}`, marker: { symbol, size, color: colour, line: ring },
          hovertemplate: `${label} of ${name}<br>(%{x:.6g}, %{y:.6g})<extra></extra>` });
      };
      markers(s.roots.map((r) => [r, 0]), "circle", "Root", 9);
      markers(s.extrema.filter((e) => e.kind === "max").map((e) => [e.x, e.y]), "triangle-up", "Maximum", 11);
      markers(s.extrema.filter((e) => e.kind === "min").map((e) => [e.x, e.y]), "triangle-down", "Minimum", 11);
      if (s.y_intercept !== null) markers([[0, s.y_intercept]], "square", "y-intercept", 9);
    });
    return traces;
  }

  async function renderPlot(data, slots) {
    redraw.plotter = () => renderPlot(data, slots);
    const caption = data.series.map((s, i) => `<span><i class="series-key" style="--series:${SERIES[slots[i]]}"></i>f<sub>${slots[i] + 1}</sub>(x) = ${mathHTML(s.interpreted)}</span>`).join("");
    const label = data.series.map((s, i) => `f${slots[i] + 1}(x) = ${s.expression}`).join("; ");
    show("plotter", `
      <div class="chart-head"><div class="chart-caption">${caption}</div></div>
      <div class="chart" id="plot-chart" role="img" aria-label="Graph of ${esc(label)}"></div>
      <p class="chart-note">● root &nbsp; ▲ maximum &nbsp; ▼ minimum &nbsp; ■ crosses the y-axis. Drag to zoom in, double-click to zoom out.</p>
      ${answeredBy("math", data)}
      <h3 class="section-title">Key points</h3>
      <div class="table-wrap"><table class="data-table">
        <thead><tr><th>Function</th><th class="text">Roots (y = 0)</th><th class="text">Turning points</th><th>Crosses the y-axis at</th></tr></thead>
        <tbody>${data.series.map((s, i) => keyPointsRow(s, slots[i])).join("")}</tbody>
      </table></div>`);
    await draw($("#plot-chart"), plotTraces(data, slots), layout2d({
      hovermode: "x unified",
      xaxis: axis2d("x", { range: [data.x_min, data.x_max] }),
      yaxis: axis2d("y", data.y_range ? { range: data.y_range } : {}),
    }));
  }

  plotForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    readFunctions();
    const used = fnRows.filter((f) => f.value.trim());
    if (!used.length) {
      show("plotter", errorBox("Enter at least one function, for example sin(x)."));
      return;
    }
    const body = {
      functions: used.map((f) => f.value),
      x_min: bound(plotForm.x_min.value),
      x_max: bound(plotForm.x_max.value),
      angle: plotForm.angle.value,
    };
    if (fromHistory.plotter) body.history = false;
    fromHistory.plotter = false;
    const data = await submit("plotter", plotForm, "/api/math/plot2d", body, {
      beforeError: () => purge("plotter"),
      mapField: (field) => {
        const match = /^f(\d)$/.exec(field || "");
        return match && used[Number(match[1])] ? $(`#fn-${used[Number(match[1])].slot}`) : null;
      },
    });
    if (data) renderPlot(data, used.map((f) => f.slot));
  });

  drawFunctionRows();

  // ==================================================================
  // 3D graph
  // ==================================================================

  const g3Form = $("#form-graph3d");
  const G3_PRESETS = {
    surface: [
      { label: "Sombrero", expression: "sin(sqrt(x^2 + y^2)) / sqrt(x^2 + y^2)", range: ["-10", "10", "-10", "10"] },
      { label: "Saddle", expression: "x^2 - y^2", range: ["-3", "3", "-3", "3"] },
      { label: "Egg crate", expression: "sin(x)cos(y)", range: ["-6", "6", "-6", "6"] },
      { label: "Peaks", expression: "3(1-x)^2 e^(-x^2-(y+1)^2) - 10(x/5 - x^3 - y^5) e^(-x^2-y^2) - e^(-(x+1)^2-y^2)/3", range: ["-3", "3", "-3", "3"] },
      { label: "Paraboloid", expression: "x^2 + y^2", range: ["-4", "4", "-4", "4"] },
      { label: "Bell curve", expression: "4e^(-(x^2 + y^2)/4)", range: ["-5", "5", "-5", "5"] },
    ],
    curve: [
      { label: "Helix", x: "cos(t)", y: "sin(t)", z: "t/5", t: ["0", "25"] },
      { label: "Trefoil knot", x: "sin(t) + 2sin(2t)", y: "cos(t) - 2cos(2t)", z: "-sin(3t)", t: ["0", "2pi"] },
      { label: "Conical spiral", x: "t cos(t)", y: "t sin(t)", z: "t", t: ["0", "30"] },
      { label: "Lissajous", x: "sin(3t)", y: "sin(4t)", z: "cos(5t)", t: ["0", "2pi"] },
    ],
    parametric: [
      { label: "Torus", x: "(3 + cos(v))cos(u)", y: "(3 + cos(v))sin(u)", z: "sin(v)", u: ["0", "2pi"], v: ["0", "2pi"] },
      { label: "Sphere", x: "cos(u)sin(v)", y: "sin(u)sin(v)", z: "cos(v)", u: ["0", "2pi"], v: ["0", "pi"] },
      { label: "Möbius strip", x: "(1 + v/2 cos(u/2))cos(u)", y: "(1 + v/2 cos(u/2))sin(u)", z: "v/2 sin(u/2)", u: ["0", "2pi"], v: ["-1", "1"] },
      { label: "Helicoid", x: "u cos(v)", y: "u sin(v)", z: "v/2", u: ["-2", "2"], v: ["0", "4pi"] },
    ],
  };

  function g3Mode() {
    return g3Form.mode.value;
  }

  function updateG3Mode() {
    const mode = g3Mode();
    $$(".mode-fields", g3Form).forEach((block) => { block.hidden = block.dataset.mode !== mode; });
    $("#g3-detail-field").hidden = mode === "curve";
    $("#graph3d-presets").innerHTML = presetsHTML(G3_PRESETS[mode]);
  }

  function applyG3Preset(mode, preset) {
    if (mode === "surface") {
      g3Form.expression.value = preset.expression;
      [g3Form.x_min.value, g3Form.x_max.value, g3Form.y_min.value, g3Form.y_max.value] = preset.range;
    } else if (mode === "curve") {
      g3Form.curve_x.value = preset.x;
      g3Form.curve_y.value = preset.y;
      g3Form.curve_z.value = preset.z;
      [g3Form.t_min.value, g3Form.t_max.value] = preset.t;
    } else {
      g3Form.param_x.value = preset.x;
      g3Form.param_y.value = preset.y;
      g3Form.param_z.value = preset.z;
      [g3Form.u_min.value, g3Form.u_max.value] = preset.u;
      [g3Form.v_min.value, g3Form.v_max.value] = preset.v;
    }
  }

  g3Form.addEventListener("change", (event) => {
    if (event.target.name === "mode") updateG3Mode();
  });

  $("#graph3d-presets").addEventListener("click", (event) => {
    const button = event.target.closest("[data-preset]");
    if (!button) return;
    const mode = g3Mode();
    applyG3Preset(mode, G3_PRESETS[mode][Number(button.dataset.preset)]);
    g3Form.requestSubmit();
  });

  // Turning the 3D view slowly, until the user grabs it
  let spinFrame = null;

  function stopSpin() {
    if (spinFrame) cancelAnimationFrame(spinFrame);
    spinFrame = null;
    const button = $('[data-g3="rotate"]');
    if (button) button.setAttribute("aria-pressed", "false");
  }

  function startSpin(el) {
    const eye = (el._fullLayout && el._fullLayout.scene && el._fullLayout.scene.camera.eye) || { x: 1.5, y: 1.5, z: 0.95 };
    const radius = Math.hypot(eye.x, eye.y) || 2;
    let angle = Math.atan2(eye.y, eye.x);
    let last = 0;
    const step = (now) => {
      if (!el.isConnected || S.currentTool() !== "graph3d") { stopSpin(); return; }
      if (now - last > 40) {
        angle += 0.015;
        last = now;
        window.Plotly.relayout(el, { "scene.camera.eye": { x: radius * Math.cos(angle), y: radius * Math.sin(angle), z: eye.z } });
      }
      spinFrame = requestAnimationFrame(step);
    };
    spinFrame = requestAnimationFrame(step);
  }

  function g3Traces(data) {
    if (data.mode === "surface") {
      return [{
        type: "surface", x: data.x, y: data.y, z: data.z, colorscale: RAMP, lighting: LIGHTING, lightposition: LIGHT_FROM,
        colorbar: { title: { text: "z", font: { color: INK.secondary } }, thickness: 12, len: 0.6, outlinewidth: 0, tickfont: { color: INK.muted } },
        contours: { z: { show: true, usecolormap: true, width: 2, project: { z: true } } },
        hovertemplate: "x = %{x:.4g}<br>y = %{y:.4g}<br>z = %{z:.4g}<extra></extra>",
      }];
    }
    if (data.mode === "curve") {
      return [{
        type: "scatter3d", mode: "lines", x: data.x, y: data.y, z: data.z, customdata: data.t,
        line: { width: 6, color: data.t, colorscale: RAMP, showscale: true,
          colorbar: { title: { text: "t", font: { color: INK.secondary } }, thickness: 12, len: 0.6, outlinewidth: 0, tickfont: { color: INK.muted } } },
        hovertemplate: "t = %{customdata:.4g}<br>(%{x:.4g}, %{y:.4g}, %{z:.4g})<extra></extra>",
      }];
    }
    return [{
      type: "surface", x: data.x, y: data.y, z: data.z, surfacecolor: data.z, colorscale: RAMP, showscale: false,
      lighting: LIGHTING, lightposition: LIGHT_FROM, hovertemplate: "(%{x:.3g}, %{y:.3g}, %{z:.3g})<extra></extra>",
    }];
  }

  let g3Camera = null;   // the starting view, for "Reset view"

  async function renderGraph3d(data, camera = null) {
    redraw.graph3d = () => {
      const current = $("#g3-chart");
      const view = current && current._fullLayout && current._fullLayout.scene ? current._fullLayout.scene.camera : null;
      return renderGraph3d(data, view);
    };
    const surface = data.mode === "surface";
    const notes = [];
    if (data.clipped) notes.push("Very large values were cut off so the rest of the surface stays readable.");
    if (data.undefined_points) notes.push(`z isn't a real number at ${num(data.undefined_points)} of the points, so the surface has gaps there.`);
    show("graph3d", `
      <div class="chart-head">
        <div class="chart-caption"><span>${mathHTML(data.summary)}</span>${surface && data.z_min !== null ? `<span>z from ${num(data.z_min)} to ${num(data.z_max)}</span>` : ""}</div>
        <div class="chart-actions">
          <button class="button-secondary" type="button" data-g3="rotate" aria-pressed="false">Rotate</button>
          ${surface ? '<button class="button-secondary" type="button" data-g3="contours" aria-pressed="true">Contour lines</button>' : ""}
          <button class="button-secondary" type="button" data-g3="reset">Reset view</button>
        </div>
      </div>
      <div class="chart tall" id="g3-chart" role="img" aria-label="${esc(data.summary)}"></div>
      <p class="chart-note">Drag to rotate, scroll to zoom, right-drag to move. ${esc(notes.join(" "))}</p>
      ${answeredBy("math", data)}`);
    const traces = g3Traces(data);
    const scene = surface ? surfaceScene(data) : fitScene(traces, 0.3, $("#g3-chart"));
    g3Camera = scene.camera;              // where "Reset view" goes back to
    if (camera) scene.camera = camera;
    const el = await draw($("#g3-chart"), traces, layout3d(scene));
    if (el) el.on("plotly_relayouting", stopSpin);
  }

  resultBox("graph3d").addEventListener("click", (event) => {
    const button = event.target.closest("[data-g3]");
    const el = $("#g3-chart");
    if (!button || !el || !window.Plotly || !g3Camera) return;
    const action = button.dataset.g3;
    if (action === "rotate") {
      if (spinFrame) {
        stopSpin();
      } else {
        button.setAttribute("aria-pressed", "true");
        startSpin(el);
      }
    } else if (action === "reset") {
      stopSpin();
      window.Plotly.relayout(el, { "scene.camera": { eye: g3Camera.eye, up: { x: 0, y: 0, z: 1 }, center: { x: 0, y: 0, z: 0 } } });
    } else if (action === "contours") {
      const on = button.getAttribute("aria-pressed") !== "true";
      button.setAttribute("aria-pressed", String(on));
      window.Plotly.restyle(el, { "contours.z.show": on, "contours.z.project.z": on });
    }
  });

  g3Form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const mode = g3Mode();
    let body;
    if (mode === "surface") {
      body = { mode, expression: g3Form.expression.value, x_min: bound(g3Form.x_min.value), x_max: bound(g3Form.x_max.value),
        y_min: bound(g3Form.y_min.value), y_max: bound(g3Form.y_max.value), resolution: Number(g3Form.resolution.value) };
    } else if (mode === "curve") {
      body = { mode, expr_x: g3Form.curve_x.value, expr_y: g3Form.curve_y.value, expr_z: g3Form.curve_z.value,
        t_min: bound(g3Form.t_min.value), t_max: bound(g3Form.t_max.value), points: 800 };
    } else {
      body = { mode, expr_x: g3Form.param_x.value, expr_y: g3Form.param_y.value, expr_z: g3Form.param_z.value,
        u_min: bound(g3Form.u_min.value), u_max: bound(g3Form.u_max.value), v_min: bound(g3Form.v_min.value),
        v_max: bound(g3Form.v_max.value), resolution: Number(g3Form.resolution.value) };
    }
    if (fromHistory.graph3d) body.history = false;
    fromHistory.graph3d = false;
    const data = await submit("graph3d", g3Form, "/api/math/plot3d", body, {
      beforeError: () => { stopSpin(); purge("graph3d"); },
      mapField: (field) => {
        const axis = /^expr_([xyz])$/.exec(field || "");
        if (!axis) return null;
        return g3Form.elements[`${mode === "curve" ? "curve" : "param"}_${axis[1]}`];
      },
    });
    if (data) renderGraph3d(data);
  });

  // ==================================================================
  // 3D shapes
  // ==================================================================

  const solidForm = $("#form-solids");
  let solidCatalogue = null;
  const solidValues = {
    cube: { a: "5" }, cuboid: { l: "8", w: "5", h: "4" }, cylinder: { r: "3", h: "10" }, cone: { r: "3", h: "7" },
    sphere: { r: "5" }, hemisphere: { r: "5" }, frustum: { R: "6", r: "3", h: "8" }, pyramid: { a: "6", h: "8" },
    torus: { R: "5", r: "1.5" },
  };
  let solidUnit = "cm";

  function currentShape() {
    const checked = $('input[name="shape"]:checked', solidForm);
    return checked ? checked.value : "cylinder";
  }

  let shownShape = "cylinder";   // the shape whose fields are on screen

  function saveSolidValues() {   // remember what was typed, so switching shapes and back keeps it
    const values = (solidValues[shownShape] = solidValues[shownShape] || {});
    $$("#solid-dims input", solidForm).forEach((input) => { values[input.name] = input.value; });
    const unit = $("#solid-unit");
    if (unit) solidUnit = unit.value;
  }

  function drawSolidFields(shape) {
    shownShape = shape;
    const spec = solidCatalogue.shapes.find((s) => s.id === shape);
    const values = solidValues[shape] || {};
    $("#solid-dims").innerHTML = spec.dims.map((d) => `
      <div class="field">
        <label for="solid-${d.key}">${esc(d.label)}</label>
        <input id="solid-${d.key}" name="${d.key}" type="text" inputmode="decimal" autocomplete="off" value="${esc(values[d.key] ?? "")}">
      </div>`).join("") + `
      <div class="field">
        <label for="solid-unit">Unit</label>
        <select id="solid-unit" name="unit">${solidCatalogue.units.map((u) => `<option value="${u}"${u === solidUnit ? " selected" : ""}>${u}</option>`).join("")}</select>
      </div>`;
  }

  async function loadSolids() {
    const state = $("#solids-state");
    state.innerHTML = '<p class="hint">Loading shapes from math-service…</p>';
    solidForm.hidden = true;
    const response = await S.api("/api/math/solids");
    if (!response.ok) {
      state.innerHTML = S.catalogueError("math", response, loadSolids);
      return;
    }
    solidCatalogue = response.data;
    const chips = $("#solid-shapes");
    $$("label", chips).forEach((label) => label.remove());
    chips.insertAdjacentHTML("beforeend", solidCatalogue.shapes.map((s) =>
      `<label><input type="radio" name="shape" value="${esc(s.id)}"${s.id === "cylinder" ? " checked" : ""}><span>${esc(s.name)}</span></label>`).join(""));
    drawSolidFields("cylinder");
    state.innerHTML = "";
    solidForm.hidden = false;
  }

  solidForm.addEventListener("change", (event) => {
    if (event.target.name !== "shape") return;
    saveSolidValues();
    drawSolidFields(event.target.value);
  });

  // --- building the 3D model of a shape (pure geometry, drawn in the browser).
  // Each face is coloured by how directly it faces a light above the model (Lambert shading),
  // worked out here rather than by the graphics card, so the model looks solid everywhere.

  const range = (n, from, to) => Array.from({ length: n }, (_, i) => from + (to - from) * i / (n - 1));
  const AROUND = range(73, 0, 2 * Math.PI);
  const SUN = (() => { const v = [0.35, 0.3, 0.89]; const length = Math.hypot(...v); return v.map((c) => c / length); })();
  const NO_LIGHTING = { ambient: 1, diffuse: 0, specular: 0, roughness: 1, fresnel: 0 };

  function brightness(nx, ny, nz) {
    const length = Math.hypot(nx, ny, nz) || 1;
    return 0.12 + 0.88 * Math.max(0, (nx * SUN[0] + ny * SUN[1] + nz * SUN[2]) / length);
  }

  function shadeColour(value) {   // the SHADE scale at 0..1, as an rgb() colour
    const stops = SHADE.map(([at, hex]) => [at, [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16))]);
    let k = 1;
    while (k < stops.length - 1 && value > stops[k][0]) k += 1;
    const [from, low] = stops[k - 1];
    const [to, high] = stops[k];
    const f = Math.min(1, Math.max(0, (value - from) / (to - from)));
    return `rgb(${low.map((c, i) => Math.round(c + (high[i] - c) * f)).join(", ")})`;
  }

  // A curved face over a us × vs grid. fn(u, v) -> [x, y, z, nx, ny, nz], n pointing outwards.
  function shadedSurface(us, vs, fn) {
    const x = [], y = [], z = [], shade = [];
    vs.forEach((v) => {
      const row = us.map((u) => fn(u, v));
      x.push(row.map((p) => p[0]));
      y.push(row.map((p) => p[1]));
      z.push(row.map((p) => p[2]));
      shade.push(row.map((p) => brightness(p[3], p[4], p[5])));
    });
    return { type: "surface", x, y, z, surfacecolor: shade, cmin: 0, cmax: 1, colorscale: SHADE,
      showscale: false, lighting: NO_LIGHTING, hoverinfo: "skip" };
  }

  const outline = (x, y, z) => ({ type: "scatter3d", mode: "lines", x, y, z, line: { color: INK.edge, width: 4 }, hoverinfo: "skip" });
  const rim = (radius, z) => outline(AROUND.map((t) => radius * Math.cos(t)), AROUND.map((t) => radius * Math.sin(t)), AROUND.map(() => z));
  const disc = (radius, z, up) => shadedSurface(AROUND, [0, radius], (t, r) => [r * Math.cos(t), r * Math.sin(t), z, 0, 0, up ? 1 : -1]);

  // The side of a cylinder, cone or frustum: the radius goes from r0 at the bottom to r1 at height h
  function side(r0, r1, h) {
    const lean = (r0 - r1) / h;   // a narrowing side faces a little upwards
    return shadedSurface(AROUND, [0, h], (t, z) => {
      const r = r0 + (r1 - r0) * z / h;
      return [r * Math.cos(t), r * Math.sin(t), z, Math.cos(t), Math.sin(t), lean];
    });
  }

  function ball(r, top) {   // top: π for a sphere, π/2 for a hemisphere
    return shadedSurface(AROUND, range(37, 0, top), (t, p) => {
      const n = [Math.sin(p) * Math.cos(t), Math.sin(p) * Math.sin(t), Math.cos(p)];
      return [r * n[0], r * n[1], r * n[2], ...n];
    });
  }

  function polyhedron(vertices, faces, edges) {
    const middle = [0, 1, 2].map((i) => vertices.reduce((sum, v) => sum + v[i], 0) / vertices.length);
    const facecolor = faces.map(([a, b, c]) => {
      const [p, q, r] = [vertices[a], vertices[b], vertices[c]];
      const u = [0, 1, 2].map((i) => q[i] - p[i]);
      const w = [0, 1, 2].map((i) => r[i] - p[i]);
      let n = [u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0]];
      const outwards = [0, 1, 2].reduce((sum, i) => sum + n[i] * ((p[i] + q[i] + r[i]) / 3 - middle[i]), 0);
      if (outwards < 0) n = n.map((c) => -c);
      return shadeColour(brightness(...n));
    });
    const mesh = {
      type: "mesh3d", x: vertices.map((v) => v[0]), y: vertices.map((v) => v[1]), z: vertices.map((v) => v[2]),
      i: faces.map((f) => f[0]), j: faces.map((f) => f[1]), k: faces.map((f) => f[2]),
      facecolor, flatshading: true, lighting: NO_LIGHTING, hoverinfo: "skip",
    };
    const ex = [], ey = [], ez = [];
    edges.forEach(([a, b]) => {
      ex.push(vertices[a][0], vertices[b][0], null);
      ey.push(vertices[a][1], vertices[b][1], null);
      ez.push(vertices[a][2], vertices[b][2], null);
    });
    return [mesh, outline(ex, ey, ez)];
  }

  function boxModel(l, w, h) {
    const v = [[-l / 2, -w / 2, 0], [l / 2, -w / 2, 0], [l / 2, w / 2, 0], [-l / 2, w / 2, 0],
      [-l / 2, -w / 2, h], [l / 2, -w / 2, h], [l / 2, w / 2, h], [-l / 2, w / 2, h]];
    const faces = [[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5],
      [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]];
    const edges = [[0, 1], [1, 2], [2, 3], [3, 0], [4, 5], [5, 6], [6, 7], [7, 4], [0, 4], [1, 5], [2, 6], [3, 7]];
    return polyhedron(v, faces, edges);
  }

  function solidModel(shape, d) {
    const n = (key) => Number(d[key]);
    if (shape === "cube") return boxModel(n("a"), n("a"), n("a"));
    if (shape === "cuboid") return boxModel(n("l"), n("w"), n("h"));
    if (shape === "pyramid") {
      const a = n("a") / 2;
      const v = [[-a, -a, 0], [a, -a, 0], [a, a, 0], [-a, a, 0], [0, 0, n("h")]];
      return polyhedron(v, [[0, 1, 2], [0, 2, 3], [0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4]],
        [[0, 1], [1, 2], [2, 3], [3, 0], [0, 4], [1, 4], [2, 4], [3, 4]]);
    }
    if (shape === "cylinder") {
      const r = n("r"), h = n("h");
      return [side(r, r, h), disc(r, 0, false), disc(r, h, true), rim(r, 0), rim(r, h)];
    }
    if (shape === "cone") {
      const r = n("r"), h = n("h");
      return [side(r, 0, h), disc(r, 0, false), rim(r, 0)];
    }
    if (shape === "frustum") {
      const big = n("R"), small = n("r"), h = n("h");
      return [side(big, small, h), disc(big, 0, false), disc(small, h, true), rim(big, 0), rim(small, h)];
    }
    if (shape === "sphere") return [ball(n("r"), Math.PI)];
    if (shape === "hemisphere") return [ball(n("r"), Math.PI / 2), disc(n("r"), 0, false), rim(n("r"), 0)];
    const big = n("R"), small = n("r");   // torus
    return [shadedSurface(AROUND, range(41, 0, 2 * Math.PI), (u, v) => {
      const ring = big + small * Math.cos(v);
      return [ring * Math.cos(u), ring * Math.sin(u), small * Math.sin(v), Math.cos(v) * Math.cos(u), Math.cos(v) * Math.sin(u), Math.sin(v)];
    })];
  }

  function litresText(litres) {
    if (litres === null) return "";
    if (litres < 0.001) return `${num(litres * 1e6)} mm³ is ${num(litres * 1000)} millilitres`;
    if (litres < 1) return `${num(litres * 1000)} millilitres`;
    return `${num(litres)} litres`;
  }

  solidForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const shape = currentShape();
    const dims = {};
    $$("#solid-dims input", solidForm).forEach((input) => { dims[input.name] = cleanNumber(input.value); });
    const unit = $("#solid-unit").value;
    const data = await submit("solids", solidForm, "/api/math/solid", { shape, dims, unit }, { beforeError: () => purge("solids") });
    if (data) renderSolid(data, shape, unit);
  });

  async function renderSolid(data, shape, unit) {
    redraw.solids = () => renderSolid(data, shape, unit);
    const volume = data.results.find((r) => r.kind === "volume");
    const rows = data.results.map((r) => `<tr><td>${esc(r.label)}</td><td class="text">${esc(r.formula)}</td><td>${esc(num(r.value))} ${esc(r.unit)}</td></tr>`).join("");
    show("solids", `
      <div class="readout fresh">
        <p class="readout-label">Volume of the ${esc(data.name.toLowerCase())}</p>
        <p class="readout-value">${numHTML(volume.value)}<span class="readout-unit">${esc(volume.unit)}</span></p>
        <p class="readout-sub">${esc(litresText(data.litres))}</p>
        ${answeredBy("math", data)}
      </div>
      <div class="table-wrap" style="margin-top:16px"><table class="data-table">
        <thead><tr><th>Measurement</th><th class="text">Formula</th><th>Value</th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div>
      <div class="chart-head"><h3 class="section-title">3D model</h3><p class="chart-note">Drag to turn it around, scroll to zoom.</p></div>
      <div class="chart tall" id="solid-chart" role="img" aria-label="3D model of the ${esc(data.name.toLowerCase())}"></div>`);
    const model = solidModel(shape, data.dims);
    await draw($("#solid-chart"), model, layout3d({
      ...fitScene(model, 0.08, $("#solid-chart")),
      xaxis: axis3d(`x (${unit})`), yaxis: axis3d(`y (${unit})`), zaxis: axis3d(`z (${unit})`),
    }));
  }

  // ==================================================================
  // 3D vectors
  // ==================================================================

  const vecForm = $("#form-vectors");
  const cRow = $('.vector-row[data-vector="c"]');
  const cToggle = $("#vector-toggle-c");

  function setThirdVector(on) {
    cRow.hidden = !on;
    cToggle.innerHTML = on
      ? '<svg class="icon"><use href="#i-close"/></svg>Remove vector c'
      : '<svg class="icon"><use href="#i-plus"/></svg>Add vector c';
    if (on && !vecForm.cx.value && !vecForm.cy.value && !vecForm.cz.value) {
      [vecForm.cx.value, vecForm.cy.value, vecForm.cz.value] = ["0", "1", "3"];
    }
  }
  cToggle.addEventListener("click", () => setThirdVector(cRow.hidden));

  const vectorOf = (name) => ["x", "y", "z"].map((axis) => cleanNumber(vecForm.elements[`${name}${axis}`].value));

  function arrow(v, colour, name, head) {
    const length = Math.hypot(...v);
    const traces = [{ type: "scatter3d", mode: "lines", x: [0, v[0]], y: [0, v[1]], z: [0, v[2]], name,
      line: { color: colour, width: 7 }, hovertemplate: `${name} = ${esc(vecText(v))}<extra></extra>` }];
    if (length > 0) {
      traces.push({ type: "cone", x: [v[0]], y: [v[1]], z: [v[2]], u: [v[0] / length], v: [v[1] / length], w: [v[2] / length],
        anchor: "tip", sizemode: "absolute", sizeref: Math.min(head, length * 0.45), colorscale: singleColour(colour),
        showscale: false, hoverinfo: "skip", lighting: { ambient: 0.85, diffuse: 0.4 } });
    }
    return traces;
  }

  vecForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = { a: vectorOf("a"), b: vectorOf("b") };
    if (!cRow.hidden) body.c = vectorOf("c");
    const data = await submit("vectors", vecForm, "/api/matrix/vector3d", body, {
      beforeError: () => purge("vectors"),
      mapField: (field) => (["a", "b", "c"].includes(field) ? vecForm.elements[`${field}x`] : null),
    });
    if (data) renderVectors(data);
  });

  async function renderVectors(data) {
    redraw.vectors = () => renderVectors(data);
    const yes = (flag, label) => `<span class="badge${flag ? " yes" : ""}">${label}: ${flag ? "yes" : "no"}</span>`;
    const tiles = [
      tile("|a|, the length of a", esc(num(data.magnitude_a))),
      tile("|b|, the length of b", esc(num(data.magnitude_b))),
      tile("a × b (cross product)", esc(vecText(data.cross)), "Perpendicular to both a and b"),
      tile("|a × b|", esc(num(data.cross_magnitude)), "Area of the parallelogram on a and b"),
      tile("Triangle area", esc(num(data.triangle_area)), "Half of |a × b|"),
      tile("Angle between a and b", data.angle_degrees === null ? "Undefined" : `${esc(num(data.angle_degrees))}°`,
        data.angle_radians === null ? "One of the vectors has length 0" : `${esc(num(data.angle_radians))} radians`),
      tile("a + b", esc(vecText(data.sum))),
      tile("a − b", esc(vecText(data.difference))),
      tile("Unit vector â", data.unit_a ? esc(vecText(data.unit_a)) : "Undefined"),
      tile("Unit vector b̂", data.unit_b ? esc(vecText(data.unit_b)) : "Undefined"),
      tile("Projection of a on b", data.projection_scalar === null ? "Undefined" : esc(num(data.projection_scalar)),
        data.projection_vector ? `As a vector: ${esc(vecText(data.projection_vector))}` : ""),
    ];
    if (data.c) tiles.push(tile("a · (b × c)", esc(num(data.triple_product)), "Volume of the box on a, b and c (the sign shows orientation)"));
    const legend = [["a", SERIES[0]], ["b", SERIES[1]], ["a × b", SERIES[2]]].concat(data.c ? [["c", SERIES[3]]] : [])
      .map(([label, colour]) => `<span><i class="series-key" style="--series:${colour}"></i>${label}</span>`).join("")
      + `<span><i class="series-key" style="--series:${INK.plane};height:10px"></i>Parallelogram on a and b</span>`;
    show("vectors", `
      <div class="readout fresh">
        <p class="readout-label">a · b, the dot product</p>
        <p class="readout-value">${numHTML(data.dot)}</p>
        <p class="readout-sub">a = ${esc(vecText(data.a))}, b = ${esc(vecText(data.b))}</p>
        ${answeredBy("matrix", data)}
      </div>
      <div class="badges">${yes(data.perpendicular, "Perpendicular")}${yes(data.parallel, "Parallel")}${data.c ? yes(data.coplanar, "a, b and c in one plane") : ""}</div>
      <div class="tiles">${tiles.join("")}</div>
      <div class="chart-head"><div class="chart-caption">${legend}</div></div>
      <div class="chart tall" id="vec-chart" role="img" aria-label="The vectors drawn from the origin"></div>
      <p class="chart-note">Drag to rotate, scroll to zoom.</p>`);

    const named = [["a", data.a, SERIES[0]], ["b", data.b, SERIES[1]], ["a × b", data.cross, SERIES[2]]]
      .concat(data.c ? [["c", data.c, SERIES[3]]] : []);
    const extent = Math.max(1, ...named.map(([, v]) => Math.max(...v.map(Math.abs)))) * 1.12;
    const a = data.a, b = data.b;
    const tips = named.filter(([, v]) => Math.hypot(...v) > 0);
    const traces = [{
      type: "mesh3d", x: [0, a[0], a[0] + b[0], b[0]], y: [0, a[1], a[1] + b[1], b[1]], z: [0, a[2], a[2] + b[2], b[2]],
      i: [0, 0], j: [1, 2], k: [2, 3], color: INK.plane, opacity: 0.35, hoverinfo: "skip", flatshading: true,
    }];
    named.forEach(([name, v, colour]) => traces.push(...arrow(v, colour, name, extent * 0.09)));
    traces.push({   // names at the arrow tips, so colour isn't the only way to tell them apart
      type: "scatter3d", mode: "text", x: tips.map(([, v]) => v[0] * 1.1), y: tips.map(([, v]) => v[1] * 1.1),
      z: tips.map(([, v]) => v[2] * 1.1), text: tips.map(([name]) => name), hoverinfo: "skip",
      textfont: { color: INK.text, size: 15, family: FONT },
    });
    const axis = { zeroline: true, zerolinecolor: INK.muted, zerolinewidth: 2 };   // the x, y and z axes through 0
    await draw($("#vec-chart"), traces, layout3d({
      ...fitScene(traces, 0.35, $("#vec-chart")),
      xaxis: axis3d("x", axis), yaxis: axis3d("y", axis), zaxis: axis3d("z", axis),
    }));
  }

  // ==================================================================
  // Matrices
  // ==================================================================

  const mxForm = $("#form-matrices");
  const MX_MAX = 6;
  const TWO_MATRIX = new Set(["add", "subtract", "multiply", "solve"]);
  const mx = {
    a: { rows: 3, cols: 3, cells: [["2", "-1", "0"], ["-1", "2", "-1"], ["0", "-1", "2"]] },
    b: { rows: 3, cols: 1, cells: [["1"], ["0"], ["1"]] },
  };
  let lastMatrix = null;

  const editor = (name) => $(`.matrix-editor[data-matrix="${name}"]`, mxForm);
  const gridOf = (name) => $(`[data-grid="${name}"]`, mxForm);

  function readGrid(name) {
    $$("input", gridOf(name)).forEach((input) => {
      mx[name].cells[Number(input.dataset.r)][Number(input.dataset.c)] = input.value;
    });
  }

  function drawGrid(name) {
    const m = mx[name];
    const label = name.toUpperCase();
    const el = gridOf(name);
    el.style.setProperty("--cols", m.cols);
    el.removeAttribute("aria-invalid");
    let html = "";
    for (let r = 0; r < m.rows; r += 1) {
      for (let c = 0; c < m.cols; c += 1) {
        html += `<input type="text" inputmode="decimal" autocomplete="off" data-r="${r}" data-c="${c}" aria-label="${label} row ${r + 1}, column ${c + 1}" value="${esc(m.cells[r][c] ?? "")}">`;
      }
    }
    el.innerHTML = html;
    $$("select.size-select", editor(name)).forEach((select) => { select.value = String(m[select.dataset.dim]); });
  }

  function resize(name, rows, cols) {
    readGrid(name);
    const old = mx[name].cells;
    mx[name] = { rows, cols, cells: Array.from({ length: rows }, (_, r) => Array.from({ length: cols }, (_, c) => (old[r] && old[r][c] !== undefined ? old[r][c] : ""))) };
    drawGrid(name);
  }

  ["a", "b"].forEach((name) => {
    $$("select.size-select", editor(name)).forEach((select) => {
      select.innerHTML = Array.from({ length: MX_MAX }, (_, i) => `<option value="${i + 1}">${i + 1}</option>`).join("");
      select.addEventListener("change", () => {
        const rows = Number($('select[data-dim="rows"]', editor(name)).value);
        const cols = Number($('select[data-dim="cols"]', editor(name)).value);
        resize(name, rows, cols);
      });
    });
    editor(name).addEventListener("click", (event) => {
      const button = event.target.closest("[data-fill]");
      if (!button) return;
      const m = mx[name];
      m.cells = m.cells.map((row, r) => row.map((_, c) => (button.dataset.fill === "identity" ? String(Number(r === c)) : "")));
      drawGrid(name);
      const first = $("input", gridOf(name));
      if (first && button.dataset.fill === "clear") first.focus();
    });
    drawGrid(name);
  });

  function updateMatrixOperation() {
    const op = mxForm.operation.value;
    const two = TWO_MATRIX.has(op);
    editor("b").hidden = !two;
    $("#mx-scalar-field").hidden = op !== "scalar";
    $("#mx-power-field").hidden = op !== "power";
    $("#mx-extra").hidden = op !== "scalar" && op !== "power";
    if (!two) return;
    readGrid("a");
    const a = mx.a, b = mx.b;
    if ((op === "add" || op === "subtract") && (b.rows !== a.rows || b.cols !== a.cols)) resize("b", a.rows, a.cols);
    if (op === "multiply" && b.rows !== a.cols) resize("b", a.cols, b.cols);
    if (op === "solve" && b.rows !== a.rows) resize("b", a.rows, 1);
  }
  mxForm.operation.addEventListener("change", updateMatrixOperation);

  function matrixHTML(matrix, split) {
    const cols = matrix[0] ? matrix[0].length : 1;
    const cells = matrix.map((row) => row.map((cell, c) =>
      `<span class="${split !== undefined && c === split ? "split-left" : ""}">${esc(cell.text)}</span>`).join("")).join("");
    return `<div class="matrix-out" style="--cols:${cols}">${cells}</div>`;
  }

  const RESULT_NAMES = { add: "A + B", subtract: "A − B", multiply: "AB", transpose: "Aᵀ", inverse: "A⁻¹", rref: "RREF(A)" };

  function renderMatrixResult(data) {
    let body = "";
    let actions = "";
    lastMatrix = null;
    if (data.result_type === "matrix") {
      const name = data.operation === "scalar" ? `${esc(mxForm.scalar.value.trim())}A`
        : data.operation === "power" ? `A<sup>${esc(String(data.power))}</sup>` : esc(RESULT_NAMES[data.operation] || data.name);
      body = `<div class="matrix-equation"><span class="name">${name}</span><span>=</span>${matrixHTML(data.matrix)}</div>`;
      if (data.determinant) body += `<p class="readout-sub">det(A) = ${esc(data.determinant.text)}</p>`;
      if (data.pivots) body += `<p class="readout-sub">Rank ${data.rank}; pivots in column${data.pivots.length === 1 ? "" : "s"} ${data.pivots.join(", ")}</p>`;
      if (data.matrix.length <= MX_MAX && data.matrix[0].length <= MX_MAX) {
        lastMatrix = data.matrix;
        actions = '<div class="result-actions"><button class="button-secondary" type="button" id="mx-use">Use this as A</button></div>';
      }
    } else if (data.result_type === "scalar") {
      body = `<p class="readout-label">${esc(data.name)}</p><p class="readout-value">${esc(data.value.text)}</p>`;
    } else if (data.result_type === "solve") {
      const solution = data.solution
        ? (data.solution[0].length === 1
          ? `<p class="readout-value formula-value">${data.solution.map((row, i) => `x<sub>${i + 1}</sub> = ${esc(row[0].text)}`).join(", &nbsp;")}</p>`
          : `<div class="matrix-equation"><span class="name">X</span><span>=</span>${matrixHTML(data.solution)}</div>`)
        : "";
      body = `<p class="readout-label">${esc(data.message)}</p>${solution}
        <h3 class="section-title">Row-reduced [A | B]</h3>${matrixHTML(data.rref, data.split)}`;
    } else {
      const rows = data.pairs.map((p) => `<tr><td>${esc(p.value.text)}</td><td class="text">(${p.vector.map(esc).join(", ")})</td></tr>`).join("");
      body = `<p class="readout-label">Characteristic polynomial, det(λI − A)</p>
        <p class="readout-value formula-value">${mathHTML(data.polynomial)}</p>
        <p class="readout-sub">det(A) = ${esc(data.determinant.text)}, trace = ${esc(data.trace.text)}${data.symmetric ? ". A is symmetric, so its eigenvalues are real and its eigenvectors are perpendicular." : ""}</p>
        <div class="table-wrap" style="margin-top:14px"><table class="data-table">
          <thead><tr><th>Eigenvalue λ</th><th class="text">Eigenvector (scaled so the largest part is 1)</th></tr></thead>
          <tbody>${rows}</tbody></table></div>`;
    }
    show("matrices", `<div class="readout fresh">${body}${answeredBy("matrix", data)}</div>${actions}`);
  }

  resultBox("matrices").addEventListener("click", (event) => {
    if (!event.target.closest("#mx-use") || !lastMatrix) return;
    mx.a = { rows: lastMatrix.length, cols: lastMatrix[0].length, cells: lastMatrix.map((row) => row.map((cell) => cell.text.replace(/−/g, "-"))) };
    drawGrid("a");
    updateMatrixOperation();
    editor("a").scrollIntoView({ behavior: "smooth", block: "center" });
  });

  mxForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    readGrid("a");
    readGrid("b");
    const op = mxForm.operation.value;
    const body = { operation: op, a: mx.a.cells.map((row) => row.map(cleanNumber)) };
    if (TWO_MATRIX.has(op)) body.b = mx.b.cells.map((row) => row.map(cleanNumber));
    if (op === "scalar") body.scalar = cleanNumber(mxForm.scalar.value);
    if (op === "power") body.power = cleanNumber(mxForm.power.value);
    const data = await submit("matrices", mxForm, "/api/matrix/matrix", body, {
      mapField: (field, message) => {
        const cell = /\b([AB]) row (\d+), column (\d+)/.exec(message || "");
        if (cell) return $(`input[data-r="${Number(cell[2]) - 1}"][data-c="${Number(cell[3]) - 1}"]`, gridOf(cell[1].toLowerCase()));
        return field === "a" || field === "b" ? gridOf(field) : null;
      },
    });
    if (data) renderMatrixResult(data);
  });

  updateMatrixOperation();

  // ==================================================================
  // Calculus
  // ==================================================================

  const calcForm = $("#form-calculus");
  const CALC_PRESETS = [
    { label: "x^3 - 3x", f: "x^3 - 3x", x0: "2", a: "-2", b: "2" },
    { label: "sin(x)", f: "sin(x)", x0: "pi/4", a: "0", b: "pi" },
    { label: "x·e^(−x)", f: "x*e^(-x)", x0: "1", a: "0", b: "4" },
    { label: "ln(x)", f: "ln(x)", x0: "1", a: "1", b: "5" },
    { label: "1/(1 + x^2)", f: "1/(1 + x^2)", x0: "1", a: "-1", b: "1" },
    { label: "√x", f: "sqrt(x)", x0: "4", a: "0", b: "9" },
  ];
  $("#calculus-presets").innerHTML = presetsHTML(CALC_PRESETS);
  $("#calculus-presets").addEventListener("click", (event) => {
    const button = event.target.closest("[data-preset]");
    if (!button) return;
    const preset = CALC_PRESETS[Number(button.dataset.preset)];
    calcForm.expression.value = preset.f;
    calcForm.x0.value = preset.x0;
    calcForm.a.value = preset.a;
    calcForm.b.value = preset.b;
    calcForm.requestSubmit();
  });

  async function renderCalculus(data) {
    redraw.calculus = () => renderCalculus(data);
    const d = data.derivative;
    const integral = data.integral;
    const listOr = (items, empty) => (items.length ? items.join(", ") : empty);
    const roots = listOr(data.roots.map((r) => num(r)), "None between a and b") + (data.more_roots ? " and more" : "");
    const turning = listOr(data.extrema.map((e) => `${e.kind === "max" ? "Max" : "Min"} ${pointText(e.x, e.y)}`), "None between a and b");
    const a = num(integral.a), b = num(integral.b);
    const headline = d.text
      ? `<p class="readout-label">f′(x), the derivative of ${mathHTML(data.interpreted)}</p>
         <p class="readout-value formula-value">${mathHTML(d.text)}</p>
         ${d.second_text ? `<p class="readout-sub">f″(x) = ${mathHTML(d.second_text)}</p>` : ""}`
      : `<p class="readout-label">Slope of ${mathHTML(data.interpreted)} at x = ${esc(num(data.x0))}</p>
         <p class="readout-value">${numHTML(d.value)}</p>
         <p class="readout-sub">An exact formula for f′(x) isn't available for this function, so the slope was worked out numerically.</p>`;
    show("calculus", `
      <div class="readout fresh">${headline}${answeredBy("math", data)}</div>
      <div class="tiles">
        ${tile(`Slope at x = ${esc(num(data.x0))}`, `f′(${esc(num(data.x0))}) = ${esc(num(d.value))}`, `f(${esc(num(data.x0))}) = ${esc(num(data.f_x0))}`)}
        ${tile("Tangent line there", esc(data.tangent.text))}
        ${tile(`Integral from ${esc(a)} to ${esc(b)}`, integral.defined ? `${esc(num(integral.value))}` : "Not defined",
          integral.defined ? `Area between the curve and the x-axis: ${esc(num(integral.area))}` : esc(integral.message))}
        ${tile("Roots between a and b", esc(roots), "", true)}
        ${tile("Turning points between a and b", esc(turning), "", true)}
      </div>
      <div class="chart-head"><div class="chart-caption">
        <span><i class="series-key" style="--series:${SERIES[0]}"></i>f(x)</span>
        <span><i class="series-key" style="--series:${SERIES[1]}"></i>f′(x)</span>
        <span><i class="series-key" style="--series:${SERIES[2]}"></i>Tangent at x = ${esc(num(data.x0))}</span>
        <span><i class="series-key" style="--series:${INK.fillKey};height:10px"></i>Area from ${esc(a)} to ${esc(b)}</span>
      </div></div>
      <div class="chart" id="calc-chart" role="img" aria-label="Graph of f, its derivative, the tangent and the area under the curve"></div>`);
    const plot = data.plot;
    const traces = [];
    if (integral.defined) {
      traces.push({ type: "scatter", mode: "lines", x: plot.area.x, y: plot.area.y, fill: "tozeroy",
        fillcolor: INK.fill, line: { width: 0 }, hoverinfo: "skip", name: "Area" });
    }
    traces.push(
      { type: "scatter", mode: "lines", x: plot.x, y: plot.f, name: "f(x)", line: { color: SERIES[0], width: 2 },
        connectgaps: false, hovertemplate: "f(x) = %{y:.6g}<extra></extra>" },
      { type: "scatter", mode: "lines", x: plot.x, y: plot.df, name: "f′(x)", line: { color: SERIES[1], width: 2 },
        connectgaps: false, hovertemplate: "f′(x) = %{y:.6g}<extra></extra>" },
      { type: "scatter", mode: "lines", x: plot.tangent.x, y: plot.tangent.y, name: "Tangent", line: { color: SERIES[2], width: 2 },
        hovertemplate: "Tangent: %{y:.6g}<extra></extra>" },
      { type: "scatter", mode: "markers", x: [data.x0], y: [data.f_x0], name: "Point", hovertemplate: `(${esc(num(data.x0))}, ${esc(num(data.f_x0))})<extra></extra>`,
        marker: { size: 10, color: SERIES[2], line: { color: INK.surface, width: 2 } } },
    );
    await draw($("#calc-chart"), traces, layout2d({
      hovermode: "x unified",
      xaxis: axis2d("x"),
      yaxis: axis2d("y", plot.y_range ? { range: plot.y_range } : {}),
    }));
  }

  calcForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = { expression: calcForm.expression.value, x0: bound(calcForm.x0.value), a: bound(calcForm.a.value), b: bound(calcForm.b.value) };
    const data = await submit("calculus", calcForm, "/api/math/calculus", body, { beforeError: () => purge("calculus") });
    if (data) renderCalculus(data);
  });

  // ==================================================================
  // Statistics
  // ==================================================================

  const statsForm = $("#form-statistics");
  $("#stats-example").addEventListener("click", () => {
    statsForm.x.value = "1, 2, 2.5, 3, 3.5, 4, 4.5, 5, 5.5, 6, 6.5, 7, 8, 9, 10";
    statsForm.y.value = "35, 42, 45, 48, 52, 55, 58, 62, 63, 68, 70, 74, 80, 85, 91";
    $("#stats-paired").open = true;
    statsForm.requestSubmit();
  });

  async function renderStatistics(data) {
    redraw.statistics = () => renderStatistics(data);
    const reg = data.regression;
    const modes = data.modes.length
      ? data.modes.map((m) => num(m)).join(", ") + (data.more_modes ? " and more" : "")
      : "No mode";
    const modeSub = data.modes.length ? `Appears ${data.mode_count} times` : "Every value appears once";
    const outliers = data.outlier_count
      ? data.outliers.map((o) => num(o)).join(", ") + (data.outlier_count > data.outliers.length ? " and more" : "")
      : "None";
    const tiles = [
      tile("Count", esc(num(data.count))),
      tile("Sum", esc(num(data.sum))),
      tile("Mode", esc(modes), modeSub),
      tile("Smallest and largest", `${esc(num(data.min))} to ${esc(num(data.max))}`, `Range ${esc(num(data.range))}`),
      tile("Quartiles", `Q1 ${esc(num(data.q1))}, Q3 ${esc(num(data.q3))}`, `Interquartile range ${esc(num(data.iqr))}`),
      tile("Variance", esc(num(data.variance)), data.used_sample_formula ? "Sample formula, divides by n − 1" : "Population formula, divides by n"),
      tile("Standard error of the mean", esc(num(data.standard_error))),
      tile("Coefficient of variation", data.cv === null ? "–" : esc(S.pct(data.cv)), "Standard deviation as a % of the mean"),
      tile("Skewness", data.skewness === null ? "–" : esc(num(data.skewness)),
        data.skewness === null ? "" : Math.abs(data.skewness) < 0.5 ? "Roughly symmetric" : data.skewness > 0 ? "Tail to the right" : "Tail to the left"),
      tile("Outliers", esc(outliers), `Outside ${esc(num(data.lower_fence))} to ${esc(num(data.upper_fence))} (1.5 × IQR rule)`),
    ];
    const edges = data.histogram.edges;
    const bins = data.histogram.counts.map((count, i) => ({ from: edges[i], to: edges[i + 1], count }));
    const freqRows = bins.map((b) => `<tr><td>${esc(num(b.from))} to ${esc(num(b.to))}</td><td>${b.count}</td></tr>`).join("");
    const regression = reg ? `
      <h3 class="section-title">Line of best fit</h3>
      <div class="tiles">
        ${tile("Equation", esc(reg.equation), "Least-squares regression line", true)}
        ${tile("Correlation r", reg.r === null ? "–" : esc(num(reg.r)), esc(reg.strength))}
        ${tile("r²", reg.r2 === null ? "–" : esc(num(reg.r2)), reg.r2 === null ? "" : `${esc(S.pct(reg.r2 * 100))} of the change in y is explained by x`)}
      </div>
      <div class="chart-head"><div class="chart-caption">
        <span><i class="series-key" style="--series:${SERIES[0]};width:8px;height:8px;border-radius:50%"></i>Data points</span>
        <span><i class="series-key" style="--series:${SERIES[1]}"></i>Line of best fit</span>
      </div></div>
      <div class="chart" id="stats-scatter" role="img" aria-label="Scatter plot with the line of best fit"></div>` : "";
    show("statistics", `
      <div class="readout fresh">
        <p class="readout-label">Mean of ${esc(num(data.count))} value${data.count === 1 ? "" : "s"}</p>
        <p class="readout-value">${numHTML(data.mean)}</p>
        <p class="readout-sub">Median ${esc(num(data.median))}, standard deviation ${esc(num(data.std))}</p>
        ${answeredBy("math", data)}
      </div>
      <div class="tiles">${tiles.join("")}</div>
      <div class="chart-head"><h3 class="section-title">Histogram</h3></div>
      <div class="chart short" id="stats-hist" role="img" aria-label="Histogram of the values"></div>
      <div class="chart-head"><h3 class="section-title">Box plot</h3><p class="chart-note">The box spans Q1 to Q3, the line is the median, dots are outliers.</p></div>
      <div class="chart tiny" id="stats-box" role="img" aria-label="Box plot of the values"></div>
      ${regression}
      <h3 class="section-title">Frequency table</h3>
      <div class="table-wrap"><table class="data-table"><thead><tr><th>Values</th><th>Count</th></tr></thead><tbody>${freqRows}</tbody></table></div>`);

    const width = bins.length ? bins[0].to - bins[0].from : 1;
    await draw($("#stats-hist"), [{
      type: "bar", x: bins.map((b) => (b.from + b.to) / 2), y: bins.map((b) => b.count), width: width || 1,
      customdata: bins.map((b) => `${num(b.from)} to ${num(b.to)}`),
      marker: { color: SERIES[0], line: { color: INK.surface, width: 2 } },
      hovertemplate: "%{customdata}<br>%{y} value(s)<extra></extra>",
    }], layout2d({ barcornerradius: 4, bargap: 0, xaxis: axis2d("Value"), yaxis: axis2d("Count", { rangemode: "tozero" }) }));
    await draw($("#stats-box"), [{
      type: "box", x: data.x, name: "", orientation: "h", boxpoints: "outliers", quartilemethod: "linear",
      marker: { color: SERIES[0], size: 8, line: { color: INK.surface, width: 2 } },
      line: { color: SERIES[0], width: 2 }, fillcolor: INK.fill, hoverinfo: "x",
    }], layout2d({ margin: { l: 24, r: 24, t: 10, b: 40 }, xaxis: axis2d(""), yaxis: { visible: false } }));
    if (reg) {
      await draw($("#stats-scatter"), [
        { type: "scatter", mode: "markers", x: data.x, y: data.y, name: "Data",
          marker: { size: 9, color: SERIES[0], line: { color: INK.surface, width: 2 } },
          hovertemplate: "(%{x:.6g}, %{y:.6g})<extra></extra>" },
        { type: "scatter", mode: "lines", x: reg.line.x, y: reg.line.y, name: "Best fit", line: { color: SERIES[1], width: 2 },
          hovertemplate: `${esc(reg.equation)}<extra></extra>` },
      ], layout2d({ xaxis: axis2d("x"), yaxis: axis2d("y") }));
    }
  }

  statsForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = { x: statsForm.x.value, mode: statsForm.mode.value };
    if (statsForm.y.value.trim()) body.y = statsForm.y.value;
    const data = await submit("statistics", statsForm, "/api/math/statistics", body, { beforeError: () => purge("statistics") });
    if (data) renderStatistics(data);
  });

  // ==================================================================
  // Registration: restoring inputs from history, and showing a tool
  // ==================================================================

  const joinNumbers = (value) => (Array.isArray(value) ? value.join(", ") : String(value ?? ""));

  window.SuiteTools = {
    scientific: {
      restore(input) {
        sciInput.value = input.expression || "";
        setRadio(sciForm, "angle", input.angle || "deg");
      },
    },
    plotter: {
      onShow: () => shown("plotter"),
      restore(input) {
        const list = (input.functions || []).slice(0, MAX_FUNCTIONS);
        fnRows = (list.length ? list : [""]).map((value, slot) => ({ slot, value }));
        drawFunctionRows();
        plotForm.x_min.value = input.x_min ?? -10;
        plotForm.x_max.value = input.x_max ?? 10;
        setRadio(plotForm, "angle", input.angle || "rad");
        fromHistory.plotter = true;
        plotForm.requestSubmit();          // graphs come straight back from the Redis cache
      },
    },
    graph3d: {
      onShow() {
        if (!g3Form.expression.value) applyG3Preset("surface", G3_PRESETS.surface[0]);
        if (!g3Form.curve_x.value) applyG3Preset("curve", G3_PRESETS.curve[0]);
        if (!g3Form.param_x.value) applyG3Preset("parametric", G3_PRESETS.parametric[0]);
        shown("graph3d");
      },
      restore(input) {
        setRadio(g3Form, "mode", input.mode || "surface");
        updateG3Mode();
        if (input.mode === "curve") {
          applyG3Preset("curve", { x: input.expressions.x, y: input.expressions.y, z: input.expressions.z, t: input.t.map(String) });
        } else if (input.mode === "parametric") {
          applyG3Preset("parametric", { x: input.expressions.x, y: input.expressions.y, z: input.expressions.z, u: input.u.map(String), v: input.v.map(String) });
        } else {
          applyG3Preset("surface", { expression: input.expression, range: [...input.x, ...input.y].map(String) });
        }
        if (input.resolution) {
          const options = [...g3Form.resolution.options].map((o) => Number(o.value));
          const nearest = options.reduce((best, v) => (Math.abs(v - input.resolution) < Math.abs(best - input.resolution) ? v : best), options[0]);
          g3Form.resolution.value = String(nearest);
        }
        fromHistory.graph3d = true;
        g3Form.requestSubmit();
      },
    },
    solids: {
      onShow() {
        if (!solidCatalogue) loadSolids();
        shown("solids");
      },
      serviceUp(key) {
        if (key === "math" && !solidCatalogue) loadSolids();
      },
      async restore(input) {
        for (let i = 0; i < 30 && !solidCatalogue; i += 1) await new Promise((resolve) => setTimeout(resolve, 100));
        if (!solidCatalogue) return;
        solidValues[input.shape] = Object.fromEntries(Object.entries(input.dims || {}).map(([k, v]) => [k, String(v)]));
        solidUnit = input.unit || "cm";
        setRadio(solidForm, "shape", input.shape);
        drawSolidFields(input.shape);
      },
    },
    vectors: {
      onShow: () => shown("vectors"),
      restore(input) {
        ["a", "b"].forEach((name) => (input[name] || []).forEach((value, i) => { vecForm.elements[`${name}${"xyz"[i]}`].value = value; }));
        if (input.c) {
          input.c.forEach((value, i) => { vecForm.elements[`c${"xyz"[i]}`].value = value; });
          setThirdVector(true);
        } else {
          setThirdVector(false);
        }
      },
    },
    matrices: {
      restore(input) {
        mxForm.operation.value = input.operation || "determinant";
        if (input.a) mx.a = { rows: input.a.length, cols: input.a[0].length, cells: input.a.map((row) => row.map(String)) };
        if (input.b) mx.b = { rows: input.b.length, cols: input.b[0].length, cells: input.b.map((row) => row.map(String)) };
        drawGrid("a");
        drawGrid("b");
        if (input.scalar !== undefined) mxForm.scalar.value = input.scalar;
        if (input.power !== undefined) mxForm.power.value = input.power;
        updateMatrixOperation();
      },
    },
    calculus: {
      onShow: () => shown("calculus"),
      restore(input) {
        calcForm.expression.value = input.expression || "";
        calcForm.x0.value = input.x0 ?? 1;
        calcForm.a.value = input.a ?? 0;
        calcForm.b.value = input.b ?? 1;
      },
    },
    statistics: {
      onShow: () => shown("statistics"),
      restore(input) {
        statsForm.x.value = joinNumbers(input.x);
        statsForm.y.value = joinNumbers(input.y);
        $("#stats-paired").open = Boolean(statsForm.y.value.trim());
        setRadio(statsForm, "mode", input.mode || "sample");
      },
    },
  };

  // A theme switch: new colours for the function keys, and every chart drawn again in the new colours.
  // The visible tool redraws now; hidden ones when they're next opened (Plotly can't size a hidden chart).
  document.addEventListener("suite:theme", (event) => {
    useTheme(event.detail.theme);
    readFunctions();
    drawFunctionRows();
    Object.keys(redraw).forEach((tool) => stale.add(tool));
    refresh(S.currentTool());
  });

  updateG3Mode();
})();
