/* Calculator Suite front end.
 *
 * The page only ever talks to the gateway it was served from:
 *   /api/calc/*       -> calc-service
 *   /api/converter/*  -> converter-service
 *   /api/finance/*    -> finance-service
 *   /api/student/*    -> student-service
 *   /api/math/*       -> math-service    (scientific calculator, graphs, calculus, statistics, 3D shapes)
 *   /api/matrix/*     -> matrix-service  (matrices and 3D vectors)
 *   /api/solver/*     -> solver-service  (worked solutions and the Ask box; solver.js)
 *   /api/history/*    -> history-service (which owns PostgreSQL)
 *
 * The maths tools live in math.js, which registers itself on window.SuiteTools.
 */
(() => {
  "use strict";

  const TOOLS = ["home", "calculator", "scientific", "converter", "plotter", "graph3d", "solids", "vectors",
    "matrices", "calculus", "statistics", "gst", "emi", "cgpa", "grades", "attendance", "chaos"];
  const TOOL_TITLES = {
    home: "Overview", calculator: "Calculator", scientific: "Scientific calculator", converter: "Unit converter",
    plotter: "Function plotter", graph3d: "3D graph", solids: "3D shapes", vectors: "3D vectors",
    matrices: "Matrices", calculus: "Calculus", statistics: "Statistics", gst: "GST calculator",
    emi: "EMI calculator", cgpa: "CGPA and percentage", grades: "Marks and grades", attendance: "Attendance",
    chaos: "Chaos lab",
  };
  // Tools with big charts or matrices use the full width; Recent and Services move below them
  const WIDE_TOOLS = new Set(["plotter", "graph3d", "solids", "vectors", "matrices", "calculus", "statistics", "chaos"]);
  const SERVICES = [
    { key: "calc", name: "calc-service", label: "Calculator", path: "/api/calc/health" },
    { key: "converter", name: "converter-service", label: "Unit converter", path: "/api/converter/health" },
    { key: "finance", name: "finance-service", label: "GST and EMI", path: "/api/finance/health" },
    { key: "student", name: "student-service", label: "Student tools", path: "/api/student/health" },
    { key: "math", name: "math-service", label: "Maths, graphs and 3D", path: "/api/math/ready" },
    { key: "matrix", name: "matrix-service", label: "Matrices and vectors", path: "/api/matrix/health" },
    { key: "solver", name: "solver-service", label: "Worked solutions", path: "/api/solver/health" },
    { key: "history", name: "history-service", label: "History", path: "/api/history/ready" },
  ];
  const SERVICE_NAMES = Object.fromEntries(SERVICES.map((s) => [s.key, s.name]));
  const RECORD_TOOLS = {  // history "tool" value -> page tool and label
    calculator: ["calculator", "Calculator"], "unit-converter": ["converter", "Unit converter"],
    gst: ["gst", "GST"], emi: ["emi", "EMI"], cgpa: ["cgpa", "CGPA"],
    grades: ["grades", "Grades"], attendance: ["attendance", "Attendance"],
    scientific: ["scientific", "Scientific"], plot2d: ["plotter", "Graph"], graph3d: ["graph3d", "3D graph"],
    calculus: ["calculus", "Calculus"], statistics: ["statistics", "Statistics"], solid: ["solids", "3D shape"],
    matrix: ["matrices", "Matrix"], vector3d: ["vectors", "Vectors"],
    solver: ["home", "Worked solution"],
  };

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

  // ------------------------------------------------------------------
  // Formatting
  // ------------------------------------------------------------------

  const numberFormat = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 6 });
  const percentFormat = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });
  const rupeeFormat = new Intl.NumberFormat("en-IN", {
    style: "currency", currency: "INR", minimumFractionDigits: 2, maximumFractionDigits: 2,
  });

  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const useMinus = (text) => text.replace(/^-/, "−");

  function needsScientific(n) {
    const abs = Math.abs(n);
    return abs !== 0 && (abs >= 1e15 || abs < 1e-6);
  }

  function scientificParts(n) {
    const [mantissa, exponent] = n.toExponential(5).split("e");
    return [useMinus(String(parseFloat(mantissa))), useMinus(String(parseInt(exponent, 10)))];
  }

  function num(n) {  // plain text
    if (typeof n !== "number" || !Number.isFinite(n)) return "–";
    if (needsScientific(n)) {
      const [m, e] = scientificParts(n);
      return `${m}e${e}`;
    }
    return useMinus(numberFormat.format(n));
  }

  function numHTML(n) {  // for the big readout: 1.2 × 10^15 with a real superscript
    if (typeof n === "number" && Number.isFinite(n) && needsScientific(n)) {
      const [m, e] = scientificParts(n);
      return `${m} × 10<sup>${e}</sup>`;
    }
    return esc(num(n));
  }

  const rupees = (n) => useMinus(rupeeFormat.format(n));
  const pct = (n) => `${percentFormat.format(n)}%`;

  // Accept "1,00,000", "₹ 500" or "−4" as typed by people
  const cleanNumber = (text) => String(text).replace(/[\s,₹]/g, "").replace(/−/g, "-");

  function ago(iso) {
    const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
    if (seconds < 45) return "just now";
    if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
    if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
    if (seconds < 7 * 86400) return `${Math.round(seconds / 86400)} d ago`;
    return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  }

  // ------------------------------------------------------------------
  // Talking to the gateway
  // ------------------------------------------------------------------

  async function api(path, { method = "GET", body } = {}) {
    let response;
    try {
      response = await fetch(path, {
        method,
        cache: "no-store",
        headers: body ? { "Content-Type": "application/json" } : undefined,
        body: body ? JSON.stringify(body) : undefined,
      });
    } catch (err) {
      return { ok: false, status: 0, data: { error: "The gateway isn't responding. Check that its container is running." } };
    }
    let data = {};
    try { data = (await response.json()) || {}; } catch (err) { data = {}; }
    return { ok: response.ok, status: response.status, data, servedBy: response.headers.get("X-Served-By") };
  }

  // ------------------------------------------------------------------
  // Showing results and errors
  // ------------------------------------------------------------------

  const resultBox = (tool) => $(`#result-${tool}`);

  function answeredBy(serviceKey, data) {
    const host = (data.served_by ? ` (${esc(data.served_by)})` : "") + (data.cached ? ", from the Redis cache" : "");
    const saved = data.saved === false
      ? `<span class="warn">Not saved to history: history-service is unavailable</span>`
      : "";
    return `<div class="readout-foot"><span>Answered by ${esc(SERVICE_NAMES[serviceKey])}${host}</span>${saved}</div>`;
  }

  function errorHTML(serviceKey, response) {
    const data = response.data || {};
    if (response.status === 0) {
      return `<div class="error-box"><strong>Can't reach the gateway</strong>${esc(data.error)}</div>`;
    }
    if (data.code === "service_unavailable") {
      return `<div class="error-box"><strong>${esc(SERVICE_NAMES[serviceKey])} isn't responding</strong>` +
        "Its container may be stopped. Start it again, then retry.</div>";
    }
    if (response.status === 400) {
      return `<div class="error-box"><strong>Check the input</strong>${esc(data.error)}</div>`;
    }
    return `<div class="error-box"><strong>Something went wrong</strong>${esc(data.error || `Error ${response.status}`)}</div>`;
  }

  function clearInvalid(form) {
    $$("[aria-invalid]", form).forEach((el) => el.removeAttribute("aria-invalid"));
  }

  function markInvalid(form, field) {
    if (!field) return;
    // "rate" errors belong to the "Other rate" box when that is the visible one
    const candidates = [form.elements[field], form.elements[`custom_${field}`]];
    const element = candidates.find((el) => el instanceof HTMLElement && el.offsetParent !== null);
    if (element) {
      element.setAttribute("aria-invalid", "true");
      element.focus();
    }
  }

  async function submit(tool, form, path, body, options = {}) {
    const serviceKey = form.closest(".tool").dataset.service;
    const button = $("button[type=submit]", form);
    clearInvalid(form);
    button.disabled = true;
    const response = await api(path, { method: "POST", body });
    button.disabled = false;
    if (!response.ok) {
      if (options.beforeError) options.beforeError();
      resultBox(tool).innerHTML = errorHTML(serviceKey, response);
      // options.mapField finds the input for an error field when the form's names differ from the API's
      const target = options.mapField ? options.mapField(response.data.field, response.data.error) : null;
      if (target) {
        target.setAttribute("aria-invalid", "true");
        if (typeof target.focus === "function") target.focus();
      } else {
        markInvalid(form, response.data.field);
      }
      if (response.data.code === "service_unavailable" || response.status === 0) checkServices();
      return null;
    }
    loadHistory();
    return response.data;
  }

  function render(tool, html) {
    resultBox(tool).innerHTML = html;
  }

  // ------------------------------------------------------------------
  // Navigation between tools (#calculator, #converter, ...)
  // ------------------------------------------------------------------

  let currentTool = null;

  function showTool(tool) {
    currentTool = tool;
    $$(".tool").forEach((section) => { section.hidden = section.dataset.tool !== tool; });
    $$(".tool-nav a").forEach((link) => {
      if (link.dataset.tool === tool) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    document.title = tool === "home" ? "Calculator Suite" : `${TOOL_TITLES[tool]} | Calculator Suite`;
    document.body.classList.toggle("wide", WIDE_TOOLS.has(tool));
    document.body.classList.toggle("is-home", tool === "home");
    const active = $(`.tool-nav a[data-tool="${tool}"]`);
    const nav = $(".tool-nav");
    if (active && nav.scrollWidth > nav.clientWidth) {
      nav.scrollTo({ left: active.offsetLeft - 16, behavior: "smooth" });
    } else if (active && nav.scrollHeight > nav.clientHeight) {
      active.scrollIntoView({ block: "nearest" });
    }
    ensureCatalogue(tool);
    const extra = window.SuiteTools && window.SuiteTools[tool];
    if (extra && extra.onShow) extra.onShow();
  }

  function route() {
    const tool = location.hash.slice(1);
    const next = TOOLS.includes(tool) ? tool : currentTool || "home";
    if (next === currentTool) return;
    showTool(next);
    window.scrollTo(0, 0);        // a newly opened tool starts at the top, also on a phone
  }

  // ------------------------------------------------------------------
  // Calculator (calc-service)
  // ------------------------------------------------------------------

  $("#form-calculator").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = await submit("calculator", form, "/api/calc/calculate", {
      num1: cleanNumber(form.num1.value),
      num2: cleanNumber(form.num2.value),
      operation: form.operation.value,
    });
    if (!data) return;
    const question = data.operation === "percent_of"
      ? `${num(data.num1)}% of ${num(data.num2)} =`
      : `${num(data.num1)} ${data.symbol} ${num(data.num2)} =`;
    render("calculator", `
      <div class="readout fresh">
        <p class="readout-label">${esc(question)}</p>
        <p class="readout-value">${numHTML(data.result)}</p>
        ${answeredBy("calc", data)}
      </div>`);
  });

  // ------------------------------------------------------------------
  // Unit converter (converter-service)
  // ------------------------------------------------------------------

  const converterForm = $("#form-converter");
  let unitCategories = null;

  function categoryById(id) {
    return unitCategories.find((c) => c.id === id);
  }

  function fillUnitSelects(category, fromId, toId) {
    const options = category.units
      .map((u) => `<option value="${esc(u.id)}">${esc(u.name)} (${esc(u.symbol)})</option>`)
      .join("");
    converterForm.from_unit.innerHTML = options;
    converterForm.to_unit.innerHTML = options;
    converterForm.from_unit.value = fromId || category.default_from;
    converterForm.to_unit.value = toId || category.default_to;
  }

  function selectCategory(id, fromId, toId) {
    const radio = $(`input[name="category"][value="${id}"]`, converterForm);
    if (radio) radio.checked = true;
    fillUnitSelects(categoryById(id), fromId, toId);
  }

  async function loadConverterUnits() {
    const state = $("#converter-state");
    state.innerHTML = `<p class="hint">Loading units from converter-service…</p>`;
    converterForm.hidden = true;
    const response = await api("/api/converter/units");
    if (!response.ok) {
      state.innerHTML = catalogueError("converter", response, loadConverterUnits);
      return;
    }
    unitCategories = response.data.categories;
    const chips = $("#converter-categories");
    $$("label", chips).forEach((label) => label.remove());
    chips.insertAdjacentHTML("beforeend", unitCategories.map((c) =>
      `<label><input type="radio" name="category" value="${esc(c.id)}"><span>${esc(c.name)}</span></label>`).join(""));
    selectCategory(unitCategories[0].id);
    state.innerHTML = "";
    converterForm.hidden = false;
  }

  converterForm.addEventListener("change", (event) => {
    if (event.target.name === "category") fillUnitSelects(categoryById(event.target.value));
  });

  $("#conv-swap").addEventListener("click", () => {
    const from = converterForm.from_unit.value;
    converterForm.from_unit.value = converterForm.to_unit.value;
    converterForm.to_unit.value = from;
  });

  converterForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const category = $('input[name="category"]:checked', form).value;
    const data = await submit("converter", form, "/api/converter/convert", {
      category,
      value: cleanNumber(form.value.value),
      from_unit: form.from_unit.value,
      to_unit: form.to_unit.value,
      include_all: true,
    });
    if (!data) return;
    const others = data.all.map((u) => `
      <div class="${u.unit === data.to_unit ? "current" : ""}"><dt>${esc(u.name)}</dt><dd>${esc(num(u.value))} ${esc(u.symbol)}</dd></div>`).join("");
    render("converter", `
      <div class="readout fresh">
        <p class="readout-label">${esc(num(data.value))} ${esc(data.from_symbol)} =</p>
        <p class="readout-value">${numHTML(data.result)}<span class="readout-unit">${esc(data.to_symbol)}</span></p>
        ${answeredBy("converter", data)}
      </div>
      <h3 class="section-title">${esc(num(data.value))} ${esc(data.from_symbol)} in every ${esc(data.category_name.toLowerCase())} unit</h3>
      <dl class="unit-grid">${others}</dl>`);
  });

  // ------------------------------------------------------------------
  // GST (finance-service)
  // ------------------------------------------------------------------

  const gstForm = $("#form-gst");
  let gstSlabs = null;
  let gstNote = "";

  function gstSelectedRate() {
    const chip = $('input[name="rate"]:checked', gstForm);
    return chip ? chip.value : "18";
  }

  function updateGstHint() {
    const value = gstSelectedRate();
    const custom = value === "custom";
    $("#gst-custom-field").hidden = !custom;
    const slab = gstSlabs && gstSlabs.find((s) => String(s.rate) === value);
    const about = slab ? `${slab.label}: ${slab.description}. ` : "Enter any rate from 0 to 100%. ";
    $("#gst-rates-note").textContent = about + gstNote;
  }

  async function loadGstRates() {
    const state = $("#gst-state");
    state.innerHTML = `<p class="hint">Loading GST rates from finance-service…</p>`;
    gstForm.hidden = true;
    const response = await api("/api/finance/gst/rates");
    if (!response.ok) {
      state.innerHTML = catalogueError("finance", response, loadGstRates);
      return;
    }
    gstSlabs = response.data.slabs;
    const chips = $("#gst-rates");
    $$("label", chips).forEach((label) => label.remove());
    chips.insertAdjacentHTML("beforeend",
      gstSlabs.map((s) => `<label><input type="radio" name="rate" value="${esc(s.rate)}"><span>${esc(s.label)}</span></label>`).join("") +
      `<label><input type="radio" name="rate" value="custom"><span>Other</span></label>`);
    $('input[name="rate"][value="18"]', chips).checked = true;
    gstNote = `${response.data.note}.`;
    updateGstHint();
    state.innerHTML = "";
    gstForm.hidden = false;
  }

  gstForm.addEventListener("change", (event) => {
    if (event.target.name === "rate") {
      updateGstHint();
      if (event.target.value === "custom") gstForm.custom_rate.focus();
    }
  });

  gstForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const chosen = gstSelectedRate();
    const data = await submit("gst", form, "/api/finance/gst", {
      amount: cleanNumber(form.amount.value),
      rate: chosen === "custom" ? cleanNumber(form.custom_rate.value) : chosen,
      mode: form.mode.value,
      supply: form.supply.value,
    });
    if (!data) return;
    const adding = data.mode === "exclusive";
    const taxRows = data.breakdown.map((t) =>
      `<tr><td>${esc(t.label)} (${esc(pct(t.rate))})</td><td>${rupees(t.amount)}</td></tr>`).join("");
    render("gst", `
      <div class="readout fresh">
        <p class="readout-label">${adding ? "Total price including GST" : "Price before GST"}</p>
        <p class="readout-value">${rupees(adding ? data.gross_amount : data.net_amount)}</p>
        <p class="readout-sub">${adding
          ? `${rupees(data.net_amount)} + ${rupees(data.gst_amount)} GST at ${esc(pct(data.rate))}`
          : `${rupees(data.gross_amount)} includes ${rupees(data.gst_amount)} GST at ${esc(pct(data.rate))}`}</p>
        ${answeredBy("finance", data)}
      </div>
      <h3 class="section-title">Breakdown</h3>
      <div class="table-wrap"><table class="data-table">
        <tbody>
          <tr><td>Price before GST</td><td>${rupees(data.net_amount)}</td></tr>
          ${taxRows}
          ${data.breakdown.length > 1 ? `<tr><td>Total GST (${esc(pct(data.rate))})</td><td>${rupees(data.gst_amount)}</td></tr>` : ""}
        </tbody>
        <tfoot><tr><td>Total price</td><td>${rupees(data.gross_amount)}</td></tr></tfoot>
      </table></div>`);
  });

  // ------------------------------------------------------------------
  // EMI (finance-service)
  // ------------------------------------------------------------------

  $("#form-emi").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = await submit("emi", form, "/api/finance/emi", {
      principal: cleanNumber(form.principal.value),
      annual_rate: cleanNumber(form.annual_rate.value),
      tenure: cleanNumber(form.tenure.value),
      tenure_unit: form.tenure_unit.value,
    });
    if (!data) return;
    const principalShare = 100 - data.interest_share;
    const rows = data.yearly.map((y) => `
      <tr><td>Year ${y.year}</td><td>${rupees(y.principal)}</td><td>${rupees(y.interest)}</td><td>${rupees(y.balance)}</td></tr>`).join("");
    render("emi", `
      <div class="readout fresh">
        <p class="readout-label">Monthly EMI</p>
        <p class="readout-value">${rupees(data.emi)}</p>
        <p class="readout-sub">for ${esc(data.tenure_text)} (${data.months} payments) at ${esc(pct(data.annual_rate))} a year</p>
        ${answeredBy("finance", data)}
      </div>
      <div class="stats">
        <div class="stat"><p class="stat-label">Loan amount</p><p class="stat-value">${rupees(data.principal)}</p></div>
        <div class="stat"><p class="stat-label">Total interest</p><p class="stat-value">${rupees(data.total_interest)}</p></div>
        <div class="stat"><p class="stat-label">Total you pay</p><p class="stat-value">${rupees(data.total_payment)}</p></div>
      </div>
      <div class="split-bar" role="img" aria-label="Principal ${esc(pct(principalShare))}, interest ${esc(pct(data.interest_share))} of the total paid">
        <span class="principal" style="width:${principalShare}%"></span>
        <span class="interest" style="width:${data.interest_share}%"></span>
      </div>
      <div class="legend">
        <span><i class="swatch principal"></i>Principal ${esc(pct(principalShare))}</span>
        <span><i class="swatch interest"></i>Interest ${esc(pct(data.interest_share))}</span>
      </div>
      <h3 class="section-title">Year by year</h3>
      <div class="table-wrap"><table class="data-table">
        <thead><tr><th>Year</th><th>Principal paid</th><th>Interest paid</th><th>Balance left</th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div>`);
  });

  // ------------------------------------------------------------------
  // CGPA and percentage (student-service)
  // ------------------------------------------------------------------

  const cgpaForm = $("#form-cgpa");
  let studentCatalogue = null;

  function updateCgpaForm() {
    const toPercentage = cgpaForm.direction.value === "to_percentage";
    $("#cgpa-value-label").textContent = toPercentage ? "CGPA (out of 10)" : "Percentage";
    cgpaForm.value.placeholder = toPercentage ? "For example 8.2" : "For example 78";
    $("#cgpa-custom").hidden = cgpaForm.formula.value !== "custom";
  }

  async function loadStudentFormulas() {
    const state = $("#cgpa-state");
    state.innerHTML = `<p class="hint">Loading formulas from student-service…</p>`;
    cgpaForm.hidden = true;
    const response = await api("/api/student/formulas");
    if (!response.ok) {
      state.innerHTML = catalogueError("student", response, loadStudentFormulas);
      return;
    }
    studentCatalogue = response.data;
    cgpaForm.formula.innerHTML = studentCatalogue.cgpa_formulas.map((f) => f.id === "custom"
      ? `<option value="custom">Custom formula</option>`
      : `<option value="${esc(f.id)}">${esc(f.name)} (${esc(f.formula)})</option>`).join("");
    updateCgpaForm();
    state.innerHTML = "";
    cgpaForm.hidden = false;
  }

  cgpaForm.addEventListener("change", updateCgpaForm);

  cgpaForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const body = {
      direction: form.direction.value,
      value: cleanNumber(form.value.value),
      formula: form.formula.value,
    };
    if (body.formula === "custom") {
      body.multiplier = cleanNumber(form.multiplier.value);
      body.offset = cleanNumber(form.offset.value);
    }
    const data = await submit("cgpa", form, "/api/student/cgpa", body);
    if (!data) return;
    const toPercentage = data.direction === "to_percentage";
    const label = toPercentage ? `CGPA ${num(data.value)} =` : `${pct(data.value)} =`;
    const value = toPercentage
      ? esc(pct(data.result))
      : `${esc(num(data.result))}<span class="readout-unit">CGPA</span>`;
    const clamped = data.clamped ? " The result was limited to the valid range." : "";
    render("cgpa", `
      <div class="readout fresh">
        <p class="readout-label">${esc(label)}</p>
        <p class="readout-value">${value}</p>
        <p class="readout-sub">Using ${esc(data.formula_name)}: percentage = ${esc(data.formula_text)}.${esc(clamped)}</p>
        ${answeredBy("student", data)}
      </div>`);
  });

  // ------------------------------------------------------------------
  // Marks and grades (student-service)
  // ------------------------------------------------------------------

  const gradesForm = $("#form-grades");
  const subjectRows = $("#subject-rows");
  const MAX_SUBJECTS = 20;

  function addSubjectRow(subject = {}) {
    if (subjectRows.children.length >= MAX_SUBJECTS) return;
    const row = $("#subject-row").content.firstElementChild.cloneNode(true);
    $(".subject-name", row).value = subject.name ?? "";
    $(".subject-marks", row).value = subject.marks ?? "";
    $(".subject-max", row).value = subject.max_marks ?? 100;
    $(".subject-credits", row).value = subject.credits ?? "";
    subjectRows.appendChild(row);
    $("#add-subject").disabled = subjectRows.children.length >= MAX_SUBJECTS;
    return row;
  }

  function setSubjects(subjects) {
    subjectRows.innerHTML = "";
    subjects.forEach((s) => addSubjectRow(s));
    while (subjectRows.children.length < 3) addSubjectRow();
  }

  $("#add-subject").addEventListener("click", () => {
    const row = addSubjectRow();
    if (row) $(".subject-name", row).focus();
  });

  subjectRows.addEventListener("click", (event) => {
    const button = event.target.closest(".remove");
    if (!button) return;
    const row = button.closest(".subject-row");
    if (subjectRows.children.length > 1) row.remove();
    else $$("input", row).forEach((input) => { input.value = input.classList.contains("subject-max") ? "100" : ""; });
    $("#add-subject").disabled = false;
  });

  function gradingScaleHTML() {
    if (!studentCatalogue) return "";
    const rows = studentCatalogue.grade_scale.map((g, i, all) => {
      const upper = i === 0 ? 100 : all[i - 1].min_percent;
      const range = i === 0 ? `${g.min_percent}% and above` : `${g.min_percent}% to under ${upper}%`;
      return `<tr><td>${esc(g.grade)}</td><td class="text">${esc(g.meaning)}</td><td class="text">${esc(range)}</td><td>${g.grade_point}</td></tr>`;
    }).join("");
    return `
      <h3 class="section-title">Grading scale</h3>
      <div class="table-wrap"><table class="data-table">
        <thead><tr><th>Grade</th><th class="text">Meaning</th><th class="text">Marks</th><th>Points</th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div>`;
  }

  gradesForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const subjects = $$(".subject-row", subjectRows)
      .map((row) => ({
        name: $(".subject-name", row).value.trim(),
        marks: cleanNumber($(".subject-marks", row).value),
        max_marks: cleanNumber($(".subject-max", row).value),
        credits: cleanNumber($(".subject-credits", row).value),
      }))
      .filter((s) => s.marks !== "" || s.name !== "");
    if (!subjects.length) {
      render("grades", `<div class="error-box"><strong>Check the input</strong>Enter marks for at least one subject.</div>`);
      return;
    }
    if (!studentCatalogue) loadStudentFormulas();
    const data = await submit("grades", form, "/api/student/grades", { subjects });
    if (!data) return;
    const rows = data.subjects.map((s) => `
      <tr class="${s.passed ? "" : "fail"}">
        <td>${esc(s.name)}</td><td>${esc(num(s.marks))} / ${esc(num(s.max_marks))}</td>
        <td>${esc(pct(s.percentage))}</td><td>${esc(s.grade)}</td><td>${s.grade_point}</td>
      </tr>`).join("");
    const average = data.same_max_marks
      ? `${num(data.average_marks)} / ${num(data.subjects[0].max_marks)}`
      : pct(data.average_percentage);
    const failed = data.failed_subjects.length;
    const outcome = failed
      ? `${failed} subject${failed > 1 ? "s" : ""} below ${data.pass_percent}%`
      : "Passed every subject";
    render("grades", `
      <div class="readout fresh">
        <p class="readout-label">Overall percentage</p>
        <p class="readout-value">${esc(pct(data.percentage))}<span class="grade-badge" title="${esc(data.overall_meaning)}">${esc(data.overall_grade)}</span></p>
        <p class="readout-sub">${esc(num(data.total_marks))} out of ${esc(num(data.total_max))} marks, ${esc(data.overall_meaning.toLowerCase())}</p>
        ${answeredBy("student", data)}
      </div>
      <div class="stats">
        <div class="stat"><p class="stat-label">Average per subject</p><p class="stat-value">${esc(average)}</p></div>
        <div class="stat"><p class="stat-label">SGPA</p><p class="stat-value">${data.sgpa === null ? '<span class="muted">Add credits</span>' : esc(num(data.sgpa))}</p></div>
        <div class="stat"><p class="stat-label">Result</p><p class="stat-value">${esc(outcome)}</p></div>
      </div>
      <h3 class="section-title">Subjects</h3>
      <div class="table-wrap"><table class="data-table">
        <thead><tr><th>Subject</th><th>Marks</th><th>Percentage</th><th>Grade</th><th>Points</th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div>
      ${gradingScaleHTML()}`);
  });

  // ------------------------------------------------------------------
  // Attendance (student-service)
  // ------------------------------------------------------------------

  function meterScale(required) {
    // Edge labels are dropped when they would collide with the "required" label
    const labels = [];
    if (required > 18) labels.push('<span class="edge-start">0%</span>');
    labels.push(`<span class="target" style="left:${required}%">${esc(pct(required))} required</span>`);
    if (required < 82) labels.push('<span class="edge-end">100%</span>');
    return labels.join("");
  }

  $("#form-attendance").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = await submit("attendance", form, "/api/student/attendance", {
      attended: cleanNumber(form.attended.value),
      total: cleanNumber(form.total.value),
      required: cleanNumber(form.required.value) || 75,
    });
    if (!data) return;
    const good = data.meets_requirement;
    const next = good
      ? `<div class="stat"><p class="stat-label">You can miss</p><p class="stat-value">${data.can_miss} class${data.can_miss === 1 ? "" : "es"}</p></div>`
      : `<div class="stat"><p class="stat-label">Attend in a row</p><p class="stat-value">${data.must_attend === null ? "Not possible" : `${data.must_attend} class${data.must_attend === 1 ? "" : "es"}`}</p></div>`;
    render("attendance", `
      <div class="readout fresh">
        <p class="readout-label">Your attendance</p>
        <p class="readout-value">${esc(pct(data.percentage))}</p>
        <p class="message ${good ? "ok" : "bad"}">${esc(data.message)}</p>
        <div class="meter" role="img" aria-label="${esc(pct(data.percentage))} attended, ${esc(pct(data.required))} required">
          <div class="meter-fill ${good ? "" : "bad"}" style="width:${Math.min(data.percentage, 100)}%"></div>
          <span class="meter-target" style="left:${data.required}%"></span>
        </div>
        <div class="meter-scale">${meterScale(data.required)}</div>
        ${answeredBy("student", data)}
      </div>
      <div class="stats">
        <div class="stat"><p class="stat-label">Attended</p><p class="stat-value">${data.attended} of ${data.total}</p></div>
        ${next}
      </div>`);
  });

  // ------------------------------------------------------------------
  // Menus loaded from the services (units, GST rates, CGPA formulas)
  // ------------------------------------------------------------------

  const retryHandlers = {};

  function catalogueError(serviceKey, response, retry) {
    retryHandlers[serviceKey] = retry;
    const why = response.data.code === "service_unavailable" || response.status === 0
      ? `${SERVICE_NAMES[serviceKey]} isn't responding, so this tool can't load yet.`
      : esc(response.data.error || `Error ${response.status}`);
    return `<div class="error-box"><strong>Not available right now</strong>${why}
      <div><button class="button-secondary" type="button" data-retry="${serviceKey}">Try again</button></div></div>`;
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-retry]");
    if (button && retryHandlers[button.dataset.retry]) retryHandlers[button.dataset.retry]();
  });

  function ensureCatalogue(tool) {
    if (tool === "converter" && !unitCategories) loadConverterUnits();
    if (tool === "gst" && !gstSlabs) loadGstRates();
    if ((tool === "cgpa" || tool === "grades") && !studentCatalogue) loadStudentFormulas();
  }

  // ------------------------------------------------------------------
  // History (history-service + PostgreSQL)
  // ------------------------------------------------------------------

  let historyRecords = [];

  async function loadHistory() {
    const [list, stats] = await Promise.all([
      api("/api/history/records?limit=12"),
      api("/api/history/stats"),
    ]);
    const listEl = $("#history-list");
    const clearButton = $("#clear-history");
    if (!list.ok) {
      historyRecords = [];
      document.dispatchEvent(new CustomEvent("suite:history", { detail: { records: [], total: null, byTool: {}, unavailable: true } }));
      listEl.innerHTML = `<li class="history-empty">History is unavailable right now. Calculations still work; they just aren't saved.</li>`;
      clearButton.hidden = true;
      $("#history-count").textContent = "";
      return;
    }
    historyRecords = list.data.records;
    clearButton.hidden = historyRecords.length === 0;
    $("#history-count").textContent = stats.ok ? `${stats.data.total} saved` : "";
    document.dispatchEvent(new CustomEvent("suite:history", {
      detail: { records: historyRecords, total: stats.ok ? stats.data.total : null, byTool: stats.ok ? stats.data.by_tool : {} },
    }));
    if (!historyRecords.length) {
      listEl.innerHTML = `<li class="history-empty">Your results will appear here. They're stored in PostgreSQL, so they survive restarts.</li>`;
      return;
    }
    listEl.innerHTML = historyRecords.map((record, index) => {
      const label = (RECORD_TOOLS[record.tool] || [null, record.tool])[1];
      return `<li><button class="history-item" type="button" data-index="${index}" title="Load into ${esc(label)}">
        <span class="history-meta"><span>${esc(label)}</span><span>${esc(ago(record.created_at))}</span></span>
        <span class="history-summary">${esc(record.summary)}</span>
      </button></li>`;
    }).join("");
  }

  $("#clear-history").addEventListener("click", async () => {
    if (!window.confirm("Delete all saved history from the database?")) return;
    await api("/api/history/records", { method: "DELETE" });
    loadHistory();
  });

  // Clicking a recent result loads its inputs back into the right tool
  async function openRecord(index) {
    const record = historyRecords[index];
    const [tool] = (record && RECORD_TOOLS[record.tool]) || [];
    if (!tool) return;
    location.hash = tool;
    await restore(tool, record.input || {});
    const firstField = $(`#tool-${tool} .tool-form input[type="text"]`);
    if (firstField) firstField.focus();
  }

  $("#history-list").addEventListener("click", (event) => {
    const item = event.target.closest(".history-item");
    if (item) openRecord(Number(item.dataset.index));
  });

  async function waitFor(check, attempts = 30) {
    for (let i = 0; i < attempts && !check(); i += 1) {
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    return check();
  }

  async function restore(tool, input) {
    const extra = window.SuiteTools && window.SuiteTools[tool];
    if (extra && extra.restore) {
      await extra.restore(input);
      return;
    }
    const setRadio = (form, name, value) => {
      const radio = $(`input[name="${name}"][value="${value}"]`, form);
      if (radio) radio.checked = true;
    };
    if (tool === "calculator") {
      const form = $("#form-calculator");
      form.num1.value = input.num1 ?? "";
      form.num2.value = input.num2 ?? "";
      form.operation.value = input.operation || "add";
    } else if (tool === "converter") {
      if (!(await waitFor(() => unitCategories))) return;
      if (categoryById(input.category)) selectCategory(input.category, input.from_unit, input.to_unit);
      converterForm.value.value = input.value ?? "";
    } else if (tool === "gst") {
      if (!(await waitFor(() => gstSlabs))) return;
      gstForm.amount.value = input.amount ?? "";
      const known = $(`input[name="rate"][value="${input.rate}"]`, gstForm);
      if (known) known.checked = true;
      else { setRadio(gstForm, "rate", "custom"); gstForm.custom_rate.value = input.rate ?? ""; }
      setRadio(gstForm, "mode", input.mode || "exclusive");
      setRadio(gstForm, "supply", input.supply || "intra");
      updateGstHint();
    } else if (tool === "emi") {
      const form = $("#form-emi");
      form.principal.value = input.principal ?? "";
      form.annual_rate.value = input.annual_rate ?? "";
      const months = Number(input.months) || 0;
      const inYears = months % 12 === 0;
      form.tenure.value = inYears ? months / 12 : months;
      setRadio(form, "tenure_unit", inYears ? "years" : "months");
    } else if (tool === "cgpa") {
      if (!(await waitFor(() => studentCatalogue))) return;
      setRadio(cgpaForm, "direction", input.direction || "to_percentage");
      cgpaForm.formula.value = input.formula || "mitadt";
      cgpaForm.value.value = input.value ?? "";
      if (input.formula === "custom") {
        cgpaForm.multiplier.value = input.multiplier ?? "";
        cgpaForm.offset.value = input.offset ?? "";
      }
      updateCgpaForm();
    } else if (tool === "grades") {
      setSubjects(input.subjects || []);
    } else if (tool === "attendance") {
      const form = $("#form-attendance");
      form.attended.value = input.attended ?? "";
      form.total.value = input.total ?? "";
      form.required.value = input.required ?? 75;
    }
  }

  // ------------------------------------------------------------------
  // Service status (polls every service's health endpoint)
  // ------------------------------------------------------------------

  async function checkServices() {
    const results = await Promise.all(SERVICES.map((s) => api(s.path)));
    let running = 0;
    let database = "unknown";
    let cacheState = "unknown";
    const rows = SERVICES.map((service, i) => {
      const response = results[i];
      const up = response.ok;
      if (up) running += 1;
      if (service.key === "history") {
        if (response.ok) database = "connected";
        else if (response.data.database === "unreachable") database = "unreachable";
      }
      if (service.key === "math" && response.ok) cacheState = response.data.cache || "unknown";
      // history-service answering 503 means it is up but cannot reach the database
      const hostText = up ? esc(response.data.served_by || "running")
        : (service.key === "history" && response.data.database === "unreachable" ? "No database" : "Offline");
      return `<li>
        <span class="dot ${up ? "ok" : "bad"}"></span>
        <span class="service-name">${esc(service.name)}<small>${esc(service.label)}</small></span>
        <span class="service-host ${up ? "" : "bad"}" title="${up ? `Container ${hostText}` : ""}">${hostText}</span>
      </li>`;
    });
    const dbState = { connected: ["ok", "Connected"], unreachable: ["bad", "Unreachable"], unknown: ["", "Unknown"] }[database];
    rows.push(`<li>
      <span class="dot ${dbState[0]}"></span>
      <span class="service-name">db<small>PostgreSQL</small></span>
      <span class="service-host ${dbState[0] === "bad" ? "bad" : ""}">${dbState[1]}</span>
    </li>`);
    const cacheView = { connected: ["ok", "Connected"], unavailable: ["bad", "Unreachable"], disabled: ["", "Off"],
      unknown: ["", "Unknown"] }[cacheState] || ["", "Unknown"];
    rows.push(`<li>
      <span class="dot ${cacheView[0]}"></span>
      <span class="service-name">cache<small>Redis, for graphs</small></span>
      <span class="service-host ${cacheView[0] === "bad" ? "bad" : ""}">${cacheView[1]}</span>
    </li>`);
    $("#service-list").innerHTML = rows.join("");
    $("#services-checked").textContent = `checked ${new Date().toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", second: "2-digit" })}`;

    document.dispatchEvent(new CustomEvent("suite:status", {
      detail: {
        checkedAt: new Date(),
        database,
        cache: cacheState,
        services: SERVICES.map((service, i) => ({
          key: service.key, name: service.name, up: results[i].ok,
          host: results[i].ok ? results[i].data.served_by || "" : "",
          noDatabase: service.key === "history" && results[i].data.database === "unreachable",
        })),
      },
    }));

    const total = SERVICES.length;
    const dot = $("#system-dot");
    dot.className = `dot ${running === total ? "ok" : running === 0 ? "bad" : "partial"}`;
    $("#system-text").textContent = running === total
      ? `All ${total} services running`
      : running === 0 ? "Services are offline" : `${running} of ${total} services running`;

    // A tool whose menu failed to load gets another try once its service is back
    results.forEach((response, i) => {
      const key = SERVICES[i].key;
      if (!response.ok) return;
      if (key === "converter" && !unitCategories && currentTool === "converter") loadConverterUnits();
      if (key === "finance" && !gstSlabs && currentTool === "gst") loadGstRates();
      if (key === "student" && !studentCatalogue && (currentTool === "cgpa" || currentTool === "grades")) loadStudentFormulas();
      const extra = window.SuiteTools && window.SuiteTools[currentTool];
      if (extra && extra.serviceUp) extra.serviceUp(key);
    });
  }

  // ------------------------------------------------------------------
  // Shared with math.js
  // ------------------------------------------------------------------

  window.Suite = {
    $, $$, api, submit, render, esc, num, numHTML, pct, cleanNumber, useMinus, answeredBy, errorHTML,
    catalogueError, retryHandlers, loadHistory, checkServices, clearInvalid, SERVICE_NAMES,
    TOOL_TITLES, RECORD_TOOLS, SERVICES, ago, openRecord,
    currentTool: () => currentTool,
  };

  // ------------------------------------------------------------------
  // Start (after math.js has registered its tools; both scripts are deferred)
  // ------------------------------------------------------------------

  document.addEventListener("DOMContentLoaded", () => {
    setSubjects([]);
    window.addEventListener("hashchange", route);
    route();
    checkServices();
    loadHistory();
    setInterval(checkServices, 10000);
    setInterval(loadHistory, 30000);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") { checkServices(); loadHistory(); }
    });
  });
})();
