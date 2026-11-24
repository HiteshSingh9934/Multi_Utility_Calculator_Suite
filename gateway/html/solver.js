/* Calculator Suite: worked solutions and the chaos lab.
 *
 *   The Ask box (overview and quick search)   -> POST /api/solver/ask
 *   "Show steps" in Calculus, Matrices, GST and EMI -> /api/solver/derivative, /integral, /matrix-steps, /gst-steps, /emi-steps
 *   The Chaos lab                              -> POST /api/<service>/chaos, GET /api/<service>/health
 *
 * Loaded after app.js, math.js and ui.js; it uses the helpers app.js shares on window.Suite.
 */
(() => {
  "use strict";

  const S = window.Suite;
  const { $, $$, api, esc } = S;

  const icon = (name) => `<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const toast = (message) => {
    const el = $("#toast");
    el.textContent = message;
    el.classList.add("show");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => el.classList.remove("show"), 2200);
  };

  // x^2 and e^(2x) get real superscripts, as in the other tools
  function mathHTML(text) {
    text = String(text ?? "");
    let out = "";
    for (let i = 0; i < text.length; i += 1) {
      if (text[i] === "^" && text[i + 1] === "(") {
        let depth = 0;
        let j = i + 1;
        for (; j < text.length; j += 1) {
          if (text[j] === "(") depth += 1;
          if (text[j] === ")" && --depth === 0) break;
        }
        if (j < text.length) {
          out += `<sup>${mathHTML(text.slice(i + 2, j))}</sup>`;
          i = j;
          continue;
        }
      } else if (text[i] === "^") {
        const power = /^[−-]?(\d+(\.\d+)?|[A-Za-zπλ])/.exec(text.slice(i + 1));
        if (power) {
          out += `<sup>${esc(power[0])}</sup>`;
          i += power[0].length;
          continue;
        }
      }
      out += esc(text[i]);
    }
    return out;
  }

  // ------------------------------------------------------------------
  // Worked solutions: the steps, the matrices inside them, and who helped
  // ------------------------------------------------------------------

  function matrixHTML(matrix) {
    if (!matrix || !matrix.rows || !matrix.rows.length) return "";
    const cols = matrix.rows[0].length;
    const split = matrix.split === null || matrix.split === undefined ? undefined : matrix.split;
    const cells = matrix.rows.map((row) => row.map((cell, c) =>
      `<span class="${split !== undefined && c === split ? "split-left" : ""}">${esc(cell)}</span>`).join("")).join("");
    return `<div class="matrix-out step-matrix" style="--cols:${cols}" role="img" aria-label="Matrix">${cells}</div>`;
  }

  // A line of working such as "EMI = 500000 × 0.0075 ÷ 1.3 = ₹15,899.87": what is on the right of the last "="
  // gets a highlight when the line has been written, so the eye lands on the result of the step.
  function workingHTML(text, { last = false } = {}) {
    text = String(text ?? "");
    const at = Math.max(text.lastIndexOf(" = "), text.lastIndexOf(" ≈ "));
    if (at > 0) {
      const left = text.slice(0, at);
      const sign = text.slice(at + 1, at + 2);
      const right = text.slice(at + 3);
      const balanced = (open, close) => left.split(open).length === left.split(close).length;
      // A formula such as "P × r × (1 + r)^n" is not a result: only numbers are lit, and on the last step anything
      const hasVariable = /(^|[^A-Za-zπλ])[A-Za-zπλ](?![A-Za-zπλ])/.test(right);
      if (right.length && right.length <= 42 && balanced("(", ")") && balanced("[", "]") && (!hasVariable || last)) {
        return `<span class="wipe">${mathHTML(left)} ${sign} <mark class="step-result">${mathHTML(right)}</mark></span>`;
      }
    }
    return `<span class="wipe">${mathHTML(text)}</span>`;
  }

  function playerControlsHTML(count) {
    const button = (cls, name, label) => `<button class="sp-btn ${cls}" type="button" aria-label="${label}" title="${label}">
      ${icon(name)}<span>${label}</span></button>`;
    return `<div class="sp-controls" role="group" aria-label="Playback">
      <button class="sp-btn sp-play primary" type="button" aria-label="Pause" title="Pause">${icon("pause")}<span>Pause</span></button>
      ${button("sp-next", "next", "Next step")}
      ${button("sp-replay", "replay", "Replay")}
      ${button("sp-all", "all", "Show all")}
      <button class="sp-btn sp-speed" type="button" aria-label="Speed 1×" title="Change the speed">1×</button>
    </div>`;
  }

  // The worked solution: every step is in the page from the start, and steps.js plays them one by one
  function stepsHTML(steps, answer) {
    if (!steps || !steps.length) return "";
    const items = steps.map((step, index) => `
      <li class="step">
        <div class="step-body"><div class="step-inner">
          <p class="step-rule">${esc(step.rule)}</p>
          ${step.text ? `<p class="step-text">${mathHTML(step.text)}</p>` : ""}
          ${step.math ? `<p class="step-math">${workingHTML(step.math, { last: index === steps.length - 1 })}<i class="caret" aria-hidden="true"></i></p>` : ""}
          ${matrixHTML(step.matrix)}
        </div></div>
      </li>`).join("");
    const closing = answer ? `
      <div class="sp-answer">
        <svg class="sp-check" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="m7.5 12.5 3 3 6-7"/></svg>
        <div><p class="sp-answer-label">So the answer is</p><p class="sp-answer-value">${mathHTML(answer)}</p></div>
      </div>` : "";
    return `<section class="steps-player" aria-label="Worked solution">
      <header class="sp-head">
        <div class="sp-title"><h3>Worked solution</h3><span class="sp-count" aria-hidden="true">Step <b>0</b> of ${steps.length}</span></div>
        ${playerControlsHTML(steps.length)}
        <div class="sp-bar" aria-hidden="true"><i></i></div>
      </header>
      <ol class="steps">${items}</ol>
      ${closing}
    </section>`;
  }

  // A short loading state: three pulsing dots and the outline of the answer that is on its way
  const workingStateHTML = (text) => `<div class="working" role="status">
      <p class="ask-working"><span class="dots" aria-hidden="true"><i></i><i></i><i></i></span>${esc(text)}</p>
      <div class="skeleton" aria-hidden="true"><i></i><i></i><i></i></div>
    </div>`;

  // The overview shows one worked solution playing by itself, so the main feature is visible before anything is asked.
  // It is fixed text (the same EMI as the first example), not a call to a service.
  (function mountHeroDemo() {
    const slot = document.getElementById("hero-demo");
    if (!slot) return;
    const steps = [
      { rule: "What we know", text: "The loan, the yearly rate and the number of monthly payments.",
        math: "P = ₹5,00,000,   rate = 9% a year,   n = 36 months" },
      { rule: "Monthly interest rate", text: "Interest is charged every month, so divide by 12 and by 100.",
        math: "r = 9 ÷ 12 ÷ 100 = 0.0075" },
      { rule: "Growth factor", text: "One month's growth, repeated 36 times.",
        math: "(1 + 0.0075)^36 = 1.3086454" },
      { rule: "Substitute", text: "Put the numbers into the EMI formula.",
        math: "EMI = 500000 × 0.0075 × 1.3086454 ÷ (1.3086454 − 1) = ₹15,899.87" },
    ];
    slot.innerHTML = `<p class="demo-caption">Every answer comes with its working. This one is playing on its own:</p>
      ${stepsHTML(steps, "₹15,899.87 a month")}`;
    const [player] = S.mountSteps(slot, { autoplay: false });
    if (!player) return;
    player.loop = true;
    player.autoScroll = false;
    // Play only while it is on screen
    new IntersectionObserver((entries) => {
      const on = entries.some((entry) => entry.isIntersecting);
      if (on && !player.playing && !player.finished) player.play();
      else if (!on && player.playing) player.pause();
    }, { threshold: 0.35 }).observe(slot);
  })();

  function usedHTML(data) {
    const used = data.used || [];
    if (!used.length) return "";
    const names = used.map((u) => `<code>${esc(u.service)}</code>`).join(", ");
    const saved = data.saved === false ? `<span class="warn">Not saved to history: history-service is unavailable</span>` : "";
    return `<div class="readout-foot"><span>Worked out by ${names}</span>${saved}</div>`;
  }

  function solutionHTML(data, { title } = {}) {
    const details = (data.details || []).length
      ? `<div class="tiles">${data.details.map((d) => `
          <div class="tile"><p class="tile-label">${esc(d.label)}</p><p class="tile-value">${mathHTML(d.value)}</p></div>`).join("")}</div>`
      : "";
    const notes = (data.notes || []).map((n) => `<p class="hint">${esc(n)}</p>`).join("");
    return `
      <div class="readout fresh solution">
        <p class="readout-label">${esc(title || data.understood || "")}</p>
        <p class="readout-value formula-value">${mathHTML(data.answer)}</p>
        ${matrixHTML(data.matrix)}
        ${usedHTML(data)}
      </div>
      ${details}${notes}${stepsHTML(data.steps, data.answer)}`;
  }

  function problemHTML(response) {
    const data = response.data || {};
    if (response.status === 0) return S.errorHTML("solver", response);
    if (data.code === "service_unavailable") {
      const who = data.service || "solver-service";
      return `<div class="error-box"><strong>${esc(who)} isn't responding</strong>
        ${esc(data.error || "")} Its container may be stopped, or restarting after a crash. Try again in a moment.</div>`;
    }
    if (data.code === "not_understood") {
      const examples = (data.examples || []).map((e) => `<button class="preset" type="button" data-ask="${esc(e)}">${esc(e)}</button>`).join("");
      return `<div class="error-box"><strong>I didn't catch that</strong>${esc(data.error)}</div>
        ${examples ? `<div class="presets ask-suggest" aria-label="Examples">${examples}</div>` : ""}`;
    }
    if (data.code === "cannot_solve") {
      return `<div class="error-box"><strong>I can't solve that one</strong>${esc(data.error)}</div>`;
    }
    return S.errorHTML("solver", response);
  }

  // ------------------------------------------------------------------
  // The Ask box
  // ------------------------------------------------------------------

  const askForm = $("#ask-form");
  const askInput = $("#ask-input");
  const askResult = $("#ask-result");
  let lastOpen = null;

  const TOOL_FORM = { emi: "#form-emi", gst: "#form-gst", plotter: "#form-plotter", graph3d: "#form-graph3d",
    scientific: "#form-scientific", matrices: "#form-matrices" };

  // Puts an answer's inputs into the real tool and, where it makes sense, presses its button
  async function openInTool(open, { submit = true } = {}) {
    if (!open || !open.tool) return;
    const tool = open.tool;
    location.hash = tool;
    await new Promise((resolve) => setTimeout(resolve, 60));
    const section = $(`#tool-${tool}`);
    if (!section) return;
    const extra = window.SuiteTools && window.SuiteTools[tool];
    if (open.restore && extra && extra.restore) await extra.restore(open.restore);
    Object.entries(open.fields || {}).forEach(([id, value]) => {
      const field = document.getElementById(id);
      if (field) { field.value = String(value); field.dispatchEvent(new Event("input", { bubbles: true })); }
    });
    Object.entries(open.choices || {}).forEach(([name, value]) => {
      const radio = $(`input[name="${name}"][value="${value}"]`, section);
      if (radio) { radio.checked = true; radio.dispatchEvent(new Event("change", { bubbles: true })); }
    });
    const form = $(TOOL_FORM[tool] || "form", section);
    if (submit && form && tool !== "matrices") form.requestSubmit();
    if (tool === "matrices") toast("Matrix filled in. Press the button to see the answer.");
  }

  async function ask(text) {
    text = String(text || "").trim();
    if (!text) { askInput.focus(); return; }
    if (S.currentTool() !== "home") location.hash = "home";
    askInput.value = text;
    const button = $("button[type=submit]", askForm);
    button.disabled = true;
    askResult.innerHTML = workingStateHTML("Working on it…");
    const response = await api("/api/solver/ask", { method: "POST", body: { text } });
    button.disabled = false;
    if (!response.ok) {
      askResult.innerHTML = problemHTML(response);
      if (response.status === 0 || response.data.code === "service_unavailable") S.checkServices();
      return;
    }
    const data = response.data;
    lastOpen = data.open || null;
    const open = data.open && data.open.tool
      ? `<div class="result-actions"><button class="button-secondary" type="button" id="ask-open">Open in ${esc(S.TOOL_TITLES[data.open.tool] || data.open.tool)}</button></div>`
      : "";
    askResult.innerHTML = `<div class="ask-answer">${solutionHTML(data)}${open}</div>`;
    S.mountSteps(askResult);
    S.loadHistory();
    if (data.hands_over) openInTool(data.open);      // "plot sin(x)" goes straight to the plotter
  }

  askForm.addEventListener("submit", (event) => { event.preventDefault(); ask(askInput.value); });
  askResult.addEventListener("click", (event) => {
    const example = event.target.closest("[data-ask]");
    if (example) { ask(example.dataset.ask); return; }
    if (event.target.closest("#ask-open")) openInTool(lastOpen);
  });

  const EXAMPLES = ["EMI for 5 lakh at 9% for 3 years", "derivative of x^2 sin(x)", "integrate x e^x from 0 to 2",
    "solve x^2 - 5x + 6 = 0", "inverse of [[2,1],[5,3]]", "18% GST on 2499"];
  $("#ask-examples").innerHTML = EXAMPLES.map((e) => `<button class="preset" type="button" data-ask="${esc(e)}">${esc(e)}</button>`).join("");
  $("#ask-examples").addEventListener("click", (event) => {
    const example = event.target.closest("[data-ask]");
    if (example) ask(example.dataset.ask);
  });

  // A history record made by the solver asks its question again
  window.SuiteTools = window.SuiteTools || {};
  window.SuiteTools.home = Object.assign(window.SuiteTools.home || {}, {
    restore(input) { if (input && input.question) ask(input.question); },
  });

  // Quick search (Ctrl K): anything that looks like a sum or a question gets an "Ask" row
  S.askEntry = (typed) => {
    const looksLikeQuestion = /[0-9=+*/^]|\b(of|for|at|solve|derivative|integral|integrate|convert|plot|gst|emi)\b/i.test(typed) && typed.length > 3;
    const words = typed.split(/\s+/).length;
    if (!looksLikeQuestion && words < 3) return null;
    return {
      first: looksLikeQuestion,
      entry: { id: "ask", title: `Ask: ${typed}`, detail: "Worked answer from solver-service", icon: "ask", run: () => ask(typed) },
    };
  };

  // ------------------------------------------------------------------
  // "Show steps" next to the buttons of Calculus, Matrices, GST and EMI
  // ------------------------------------------------------------------

  function stepsHost(tool) {
    let host = $(`#steps-${tool}`);
    if (!host) {
      host = document.createElement("div");
      host.className = "steps-out";
      host.id = `steps-${tool}`;
      host.setAttribute("aria-live", "polite");
      $(`#result-${tool}`).after(host);
    }
    return host;
  }

  function addStepsButton(tool, formSelector, handler) {
    const form = $(formSelector);
    const actions = $(".form-actions", form);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "button-secondary steps-button";
    button.innerHTML = `${icon("ask")}Show steps`;
    actions.appendChild(button);
    // The old steps belong to the old answer
    form.addEventListener("submit", () => { stepsHost(tool).innerHTML = ""; });
    button.addEventListener("click", async () => {
      const host = stepsHost(tool);
      button.disabled = true;
      host.innerHTML = workingStateHTML("Working out the steps…");
      try {
        host.innerHTML = await handler(form);
      } finally {
        button.disabled = false;
      }
      S.mountSteps(host);
      host.scrollIntoView({ block: "nearest", behavior: "smooth" });
      S.loadHistory();
    });
    return button;
  }

  const sections = (parts) => parts.map(({ heading, body }) => `<section class="steps-section"><h3>${esc(heading)}</h3>${body}</section>`).join("");
  const solve = async (path, body) => api(path, { method: "POST", body });

  addStepsButton("calculus", "#form-calculus", async (form) => {
    const expression = form.expression.value;
    const [d, i] = await Promise.all([
      solve("/api/solver/derivative", { expression, at: form.x0.value }),
      solve("/api/solver/integral", { expression, lower: form.a.value, upper: form.b.value }),
    ]);
    const parts = [];
    if (d.ok) parts.push({ heading: "The derivative", body: solutionHTML(d.data) });
    else parts.push({ heading: "The derivative", body: problemHTML(d) });
    if (i.ok) parts.push({ heading: "The integral", body: solutionHTML(i.data) });
    else parts.push({ heading: "The integral", body: problemHTML(i) });
    return sections(parts);
  });

  const stepsError = (response) => problemHTML(response);

  addStepsButton("emi", "#form-emi", async (form) => {
    const response = await solve("/api/solver/emi-steps", {
      principal: S.cleanNumber(form.principal.value), annual_rate: S.cleanNumber(form.annual_rate.value),
      tenure: S.cleanNumber(form.tenure.value), tenure_unit: form.tenure_unit.value,
    });
    return response.ok ? solutionHTML(response.data) : stepsError(response);
  });

  addStepsButton("gst", "#form-gst", async (form) => {
    const picked = $('input[name="rate"]:checked', form);
    const rate = picked && picked.value !== "custom" ? picked.value : form.custom_rate.value;
    const response = await solve("/api/solver/gst-steps", {
      amount: S.cleanNumber(form.amount.value), rate: S.cleanNumber(rate), mode: form.mode.value,
    });
    return response.ok ? solutionHTML(response.data) : stepsError(response);
  });

  // Matrices: determinant, inverse, row reduction and simultaneous equations have worked solutions
  const matrixForm = $("#form-matrices");
  const readGrid = (name) => {
    const inputs = $$(`.matrix-editor[data-matrix="${name}"] input[data-r]`, matrixForm);
    const rows = Math.max(0, ...inputs.map((el) => Number(el.dataset.r) + 1));
    const cols = Math.max(0, ...inputs.map((el) => Number(el.dataset.c) + 1));
    const grid = Array.from({ length: rows }, () => Array(cols).fill(""));
    inputs.forEach((el) => { grid[Number(el.dataset.r)][Number(el.dataset.c)] = S.cleanNumber(el.value); });
    return grid;
  };
  const matrixSteps = addStepsButton("matrices", "#form-matrices", async (form) => {
    const operation = form.operation.value;
    const body = { operation, matrix: readGrid("a") };
    if (operation === "solve") {
      const b = readGrid("b");
      body.constants = b.map((row) => row[0]);
    }
    const response = await solve("/api/solver/matrix-steps", body);
    return response.ok ? solutionHTML(response.data) : stepsError(response);
  });
  const WITH_STEPS = new Set(["determinant", "inverse", "rref", "solve"]);
  const syncMatrixButton = () => { matrixSteps.hidden = !WITH_STEPS.has(matrixForm.operation.value); };
  matrixForm.operation.addEventListener("change", () => { syncMatrixButton(); stepsHost("matrices").innerHTML = ""; });
  syncMatrixButton();

  // ------------------------------------------------------------------
  // Chaos lab
  // ------------------------------------------------------------------

  const targetSelect = $("#chaos-target");
  const board = $("#chaos-board");
  const logEl = $("#chaos-log");
  const clockEl = $("#chaos-clock");
  const hintEl = $("#chaos-hint");
  const labForm = $("#form-chaos");
  const SECONDS = 30;
  const LAB = S.SERVICES.map((service) => ({ key: service.key, name: service.name, label: service.label }));
  const state = Object.fromEntries(LAB.map((s) => [s.key, { up: null, uptime: null, host: "", fault: null, downSince: null }]));
  let logCount = 0;

  targetSelect.innerHTML = LAB.map((s) => `<option value="${s.key}">${esc(s.name)}</option>`).join("");
  board.innerHTML = LAB.map((s) => `
    <div class="chaos-tile" data-key="${s.key}">
      <span class="dot"></span>
      <span class="chaos-name">${esc(s.name)}<small>${esc(s.label)}</small></span>
      <span class="chaos-state" data-state>checking…</span>
      <span class="chaos-up" data-uptime></span>
    </div>`).join("");

  const nowText = () => new Date().toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", second: "2-digit" });

  function log(text, kind = "info") {
    if (!logCount) logEl.innerHTML = "";
    logCount += 1;
    logEl.insertAdjacentHTML("afterbegin", `<li class="chaos-event ${kind}"><time>${nowText()}</time><span>${text}</span></li>`);
    while (logEl.children.length > 40) logEl.lastElementChild.remove();
  }

  function uptimeText(seconds) {
    if (seconds === null || seconds === undefined) return "";
    if (seconds < 60) return `up ${seconds} s`;
    if (seconds < 3600) return `up ${Math.floor(seconds / 60)} min ${seconds % 60} s`;
    return `up ${Math.floor(seconds / 3600)} h ${Math.floor((seconds % 3600) / 60)} min`;
  }

  function drawTile(service) {
    const s = state[service.key];
    const tile = $(`.chaos-tile[data-key="${service.key}"]`, board);
    const label = $("[data-state]", tile);
    tile.classList.toggle("down", s.up === false);
    tile.classList.toggle("faulted", s.up === true && Boolean(s.fault));
    $(".dot", tile).className = `dot ${s.up === false ? "bad" : s.fault ? "partial" : s.up ? "ok" : ""}`;
    if (s.up === false) label.textContent = "not answering";
    else if (s.fault) label.textContent = `${s.fault.mode === "slow" ? "slow" : "returning errors"}, ${s.fault.seconds_left} s left`;
    else label.textContent = s.up ? "running" : "checking…";
    $("[data-uptime]", tile).textContent = s.up ? uptimeText(s.uptime) : "";
  }

  async function poll() {
    if (document.hidden || S.currentTool() !== "chaos") return;
    clockEl.textContent = `checked ${nowText()}`;
    const answers = await Promise.all(LAB.map((s) => api(`/api/${s.key}/health`)));
    LAB.forEach((service, i) => {
      const response = answers[i];
      const s = state[service.key];
      const up = response.ok;
      if (!up && s.up !== false) {
        s.downSince = Date.now();
        if (s.up !== null) log(`<code>${esc(service.name)}</code> stopped answering`, "bad");
      } else if (up && s.up === false) {
        const seconds = Math.max(1, Math.round((Date.now() - s.downSince) / 1000));
        log(`<code>${esc(service.name)}</code> is back after about ${seconds} s, started fresh (${uptimeText(response.data.uptime_seconds)})`, "ok");
        s.downSince = null;
      } else if (up && s.up && s.host === response.data.served_by && response.data.uptime_seconds + 1 < s.uptime) {
        log(`<code>${esc(service.name)}</code> restarted so quickly that it was never seen down (uptime back to ${response.data.uptime_seconds} s)`, "ok");
      }
      const fault = up ? response.data.chaos || null : null;
      if (up && fault && (!s.fault || s.fault.mode !== fault.mode)) {
        log(`<code>${esc(service.name)}</code> is now ${fault.mode === "slow" ? "slow" : "returning errors"} for ${fault.seconds_left} s`, "warn");
      } else if (up && !fault && s.fault) {
        log(`<code>${esc(service.name)}</code> is back to normal`, "ok");
      }
      s.up = up;
      s.host = up ? response.data.served_by || "" : s.host;
      s.uptime = up ? response.data.uptime_seconds : s.uptime;
      s.fault = fault;
      drawTile(service);
      document.dispatchEvent(new CustomEvent("suite:fault", { detail: { key: service.key, fault } }));
    });
  }

  const HINTS = {
    crash: (n) => `${n} stops and starts again. Docker Compose restarts it in a second or two; Kubernetes does the same. ` +
      "On Kubernetes each service has two copies, so a crash is covered by the other one.",
    slow: (n) => `Every request to ${n} takes about 2.5 seconds for ${SECONDS} seconds. Its health check stays fast.`,
    errors: (n) => `Every request to ${n} fails with an error for ${SECONDS} seconds. Its health check stays fast.`,
  };
  function updateHint() {
    const service = LAB.find((s) => s.key === targetSelect.value);
    hintEl.textContent = HINTS[labForm.mode.value](service ? service.name : "the container");
  }
  targetSelect.addEventListener("change", updateHint);
  $$('input[name="mode"]', labForm).forEach((radio) => radio.addEventListener("change", updateHint));
  updateHint();

  async function inject(key, mode) {
    const service = LAB.find((s) => s.key === key);
    const path = `/api/${key}/chaos`;
    const response = await api(path, { method: "POST", body: mode === "heal" ? { mode } : { mode, seconds: SECONDS } });
    if (response.ok) {
      if (mode === "crash") log(`Crash sent to <code>${esc(service.name)}</code>`, "info");
      else if (mode !== "heal") log(`${mode === "slow" ? "Slow" : "Errors"} sent to <code>${esc(service.name)}</code> for ${SECONDS} s`, "info");
      return true;
    }
    const data = response.data || {};
    if (data.code === "chaos_disabled") log(`The chaos lab is switched off on <code>${esc(service.name)}</code>. Set CHAOS_ENABLED=true and start it again.`, "bad");
    else if (data.code === "service_unavailable" || response.status === 0) log(`<code>${esc(service.name)}</code> is already down, so there is nothing to break`, "warn");
    else log(`Couldn't reach <code>${esc(service.name)}</code>: ${esc(data.error || `error ${response.status}`)}`, "bad");
    return false;
  }

  labForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = $("button[type=submit]", labForm);
    button.disabled = true;
    await inject(targetSelect.value, labForm.mode.value);
    button.disabled = false;
    poll();
  });

  $("#chaos-surprise").addEventListener("click", async () => {
    const service = LAB[Math.floor(Math.random() * LAB.length)];
    const mode = ["crash", "slow", "errors"][Math.floor(Math.random() * 3)];
    targetSelect.value = service.key;
    $(`input[name="mode"][value="${mode}"]`, labForm).checked = true;
    updateHint();
    await inject(service.key, mode);
    poll();
  });

  $("#chaos-heal").addEventListener("click", async () => {
    const working = LAB.filter((s) => state[s.key].up !== false);
    await Promise.all(working.map((s) => api(`/api/${s.key}/chaos`, { method: "POST", body: { mode: "heal" } })));
    log("Every running container was told to go back to normal", "info");
    poll();
  });

  setInterval(poll, 1000);
  document.addEventListener("suite:status", () => { if (S.currentTool() === "chaos") poll(); });
  window.addEventListener("hashchange", () => { if (location.hash === "#chaos") poll(); });
  window.SuiteTools.chaos = Object.assign(window.SuiteTools.chaos || {}, { onShow: poll });
})();
