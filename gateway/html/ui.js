/* Calculator Suite: the overview's live system map, light and dark themes, quick search
 * (Ctrl K or /), copy buttons on answers, and the "runs on" tag in each tool's header.
 *
 * Loaded after app.js and math.js. app.js shares its helpers on window.Suite and announces
 * service health ("suite:status") and saved history ("suite:history") as DOM events.
 */
(() => {
  "use strict";

  const S = window.Suite;
  const { $, $$, esc } = S;
  const root = document.documentElement;

  // ------------------------------------------------------------------
  // What runs where. The map, the search and the tool headers all read this.
  // ------------------------------------------------------------------

  const TOOLS = [
    { id: "calculator", title: "Calculator", service: "calc", group: "Everyday",
      words: "add subtract multiply divide percent remainder basic arithmetic" },
    { id: "scientific", title: "Scientific calculator", service: "math", group: "Everyday",
      words: "expression sin cos tan log ln factorial power square root ncr npr degrees radians" },
    { id: "converter", title: "Unit converter", service: "converter", group: "Everyday",
      words: "length weight temperature area volume speed time data energy pressure km mile kg pound celsius" },
    { id: "plotter", title: "Function plotter", service: "math", group: "Graphs and 3D",
      words: "graph plot function roots maximum minimum curve 2d" },
    { id: "graph3d", title: "3D graph", service: "math", group: "Graphs and 3D",
      words: "surface plot parametric torus helix knot curve visualizer three dimensional" },
    { id: "solids", title: "3D shapes", service: "math", group: "Graphs and 3D",
      words: "volume surface area cube cuboid cylinder cone sphere hemisphere frustum pyramid torus geometry" },
    { id: "vectors", title: "3D vectors", service: "matrix", group: "Graphs and 3D",
      words: "dot cross product angle projection magnitude unit vector triple product" },
    { id: "matrices", title: "Matrices", service: "matrix", group: "Algebra and data",
      words: "matrix determinant inverse eigenvalue eigenvector rref rank transpose simultaneous equations linear algebra" },
    { id: "calculus", title: "Calculus", service: "math", group: "Algebra and data",
      words: "derivative differentiate integral integrate area under curve tangent slope" },
    { id: "statistics", title: "Statistics", service: "math", group: "Algebra and data",
      words: "mean median mode standard deviation variance quartile histogram box plot regression correlation" },
    { id: "gst", title: "GST calculator", service: "finance", group: "Business and finance",
      words: "tax cgst sgst igst price bill invoice" },
    { id: "emi", title: "EMI calculator", service: "finance", group: "Business and finance",
      words: "loan interest instalment monthly payment home car" },
    { id: "cgpa", title: "CGPA and percentage", service: "student", group: "Students",
      words: "sgpa grade point percentage convert" },
    { id: "grades", title: "Marks and grades", service: "student", group: "Students",
      words: "subjects marks grade sgpa result" },
    { id: "attendance", title: "Attendance", service: "student", group: "Students",
      words: "classes lectures 75 percent miss bunk" },
    { id: "chaos", title: "Chaos lab", service: "all", group: "System",
      words: "chaos crash kill fail break slow errors restart recover docker kubernetes resilience self healing" },
  ];
  const ICONS = { calculator: "calculator", scientific: "scientific", converter: "converter", plotter: "plotter",
    graph3d: "graph3d", solids: "solids", vectors: "vectors", matrices: "matrices", calculus: "calculus",
    statistics: "statistics", gst: "gst", emi: "emi", cgpa: "cgpa", grades: "grades", attendance: "attendance",
    chaos: "chaos" };

  // The containers, in the order of docker-compose.yml
  const CONTAINERS = [
    { key: "calc", name: "calc-service" },
    { key: "converter", name: "converter-service" },
    { key: "finance", name: "finance-service" },
    { key: "student", name: "student-service" },
    { key: "math", name: "math-service", store: { key: "cache", name: "cache", kind: "Redis", label: "cached graphs" } },
    { key: "matrix", name: "matrix-service" },
    { key: "solver", name: "solver-service", note: "Worked solutions and the Ask box" },
    { key: "history", name: "history-service", note: "Saves every result",
      store: { key: "db", name: "db", kind: "PostgreSQL", label: "every saved result" } },
  ];

  const icon = (name) => `<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;

  // ------------------------------------------------------------------
  // Light and dark themes
  // ------------------------------------------------------------------

  const themeButton = $("#theme-toggle");
  const themeColour = $('meta[name="theme-color"]');
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  const currentTheme = () => (root.dataset.theme === "light" ? "light" : "dark");

  function applyTheme(theme, remember) {
    if (theme === "light") root.dataset.theme = "light";
    else delete root.dataset.theme;
    const other = theme === "light" ? "dark" : "light";
    themeButton.setAttribute("aria-label", `Switch to the ${other} theme`);
    themeButton.title = `Switch to the ${other} theme`;
    themeColour.content = getComputedStyle(root).getPropertyValue("--bg").trim() || "#14171c";
    if (remember) {
      try { localStorage.setItem("theme", theme); } catch (err) { /* private window: just don't remember */ }
    }
  }

  function toggleTheme() {
    const next = currentTheme() === "light" ? "dark" : "light";
    if (!reducedMotion.matches) {
      root.classList.add("theme-fade");          // a short cross-fade answers the click
      setTimeout(() => root.classList.remove("theme-fade"), 400);
    }
    applyTheme(next, true);
    document.dispatchEvent(new CustomEvent("suite:theme", { detail: { theme: next } }));
    toast(next === "light" ? "Light theme on" : "Dark theme on");
  }

  themeButton.addEventListener("click", toggleTheme);
  applyTheme(currentTheme(), false);

  // ------------------------------------------------------------------
  // A short message at the bottom of the screen
  // ------------------------------------------------------------------

  const toastEl = $("#toast");
  let toastTimer = null;

  function toast(message) {
    toastEl.textContent = message;
    toastEl.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove("show"), 2200);
  }

  // ------------------------------------------------------------------
  // Copy an answer
  // ------------------------------------------------------------------

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (err) {
      // The clipboard API needs https or localhost; an address like http://192.168.1.5:8080 falls back to this
      const area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.cssText = "position:fixed;opacity:0;pointer-events:none";
      document.body.appendChild(area);
      area.select();
      let done = false;
      try { done = document.execCommand("copy"); } catch (e) { done = false; }
      area.remove();
      return done;
    }
  }

  const tidy = (text) => text.replace(/\s+/g, " ").trim();

  function addCopyButtons(container) {
    $$(".readout", container).forEach((readout) => {
      const value = $(".readout-value", readout);
      if (!value || $(".copy-button", readout)) return;
      readout.classList.add("has-copy");
      readout.insertAdjacentHTML("afterbegin",
        `<button class="copy-button" type="button" title="Copy the answer">${icon("copy")}<span>Copy</span></button>`);
    });
  }

  document.addEventListener("click", async (event) => {
    const button = event.target.closest(".copy-button");
    if (!button) return;
    const readout = button.closest(".readout");
    const label = $(".readout-label", readout);
    const value = tidy($(".readout-value", readout).innerText);
    const question = label ? tidy(label.innerText) : "";
    const text = question.endsWith("=") ? `${question} ${value}` : value;
    if (await copyText(text)) {
      button.classList.add("copied");
      button.querySelector("span").textContent = "Copied";
      button.querySelector("use").setAttribute("href", "#i-check");
      toast(`Copied: ${text.length > 60 ? `${text.slice(0, 57)}…` : text}`);
      setTimeout(() => {
        button.classList.remove("copied");
        button.querySelector("span").textContent = "Copy";
        button.querySelector("use").setAttribute("href", "#i-copy");
      }, 1600);
    } else {
      toast("Couldn't copy. Select the answer and press Ctrl C instead.");
    }
  });

  const resultsWatcher = new MutationObserver((changes) => {
    changes.forEach((change) => addCopyButtons(change.target));
  });
  $$(".result").forEach((box) => resultsWatcher.observe(box, { childList: true }));

  // ------------------------------------------------------------------
  // "Runs on <container>" in each tool's header, kept live
  // ------------------------------------------------------------------

  $$(".tool[data-service]").forEach((section) => {
    const key = section.dataset.service;
    const name = S.SERVICE_NAMES[key];
    if (!name) return;
    $(".tool-head", section).insertAdjacentHTML("beforeend",
      `<p class="tool-service" data-service-key="${esc(key)}"><span class="dot"></span>Runs on <code>${esc(name)}</code></p>`);
  });

  // ------------------------------------------------------------------
  // The overview: a live map of the containers, which is also the way into every tool
  // ------------------------------------------------------------------

  const mapEl = $("#system-map");

  function drawMap() {
    const rows = CONTAINERS.map((container, i) => {
      const tools = TOOLS.filter((t) => t.service === container.key);
      const keys = tools.length
        ? tools.map((t) => `<a class="map-key" href="#${t.id}">${icon(ICONS[t.id])}<span>${esc(t.title)}</span></a>`).join("")
        : `<p class="map-role">${esc(container.note || "")}</p>`;
      const store = container.store ? `
        <div class="map-store" data-node="${esc(container.store.key)}">
          <span class="map-node-icon">${icon(container.store.key === "db" ? "database" : "cache")}</span>
          <span class="map-node-text">
            <span class="map-node-line"><span class="dot"></span><code>${esc(container.store.name)}</code><span class="map-kind">${esc(container.store.kind)}</span></span>
            <small class="map-store-label">${esc(container.store.label)}</small>
          </span>
        </div>` : "";
      return `
        <li class="map-row" data-node="${esc(container.key)}" style="--i:${i}">
          <div class="map-unit">
            <div class="map-node">
              <span class="map-node-line"><span class="dot"></span><code>${esc(container.name)}</code></span>
              <small class="map-host" data-host>checking…</small>
            </div>
            ${store}
          </div>
          <div class="map-keys">${keys}</div>
        </li>`;
    }).join("");
    mapEl.innerHTML = `
      <div class="map-entry">
        <div class="map-node map-edge">
          <span class="map-node-icon">${icon("browser")}</span>
          <span class="map-node-text"><span class="map-node-line">Your browser</span><small>this page</small></span>
        </div>
        <span class="map-wire" aria-hidden="true"></span>
        <div class="map-node map-gateway" data-node="gateway">
          <span class="map-node-icon">${icon("gateway")}</span>
          <span class="map-node-text"><span class="map-node-line"><span class="dot ok"></span><code>gateway</code><span class="map-kind">Nginx</span></span>
          <small class="map-host">${esc(location.host || "localhost")}</small></span>
        </div>
      </div>
      <ol class="map-rows">${rows}</ol>`;
  }

  function setDot(dot, state) {
    if (!dot) return;
    dot.className = `dot ${state}`;
  }

  let firstStatus = true;

  document.addEventListener("suite:status", (event) => {
    const { services, database, cache, checkedAt } = event.detail;
    services.forEach((service) => {
      const state = service.up ? "ok" : "bad";
      const row = $(`.map-row[data-node="${service.key}"]`, mapEl);
      if (row) {
        row.classList.toggle("down", !service.up);
        setDot($(".map-node .dot", row), state);
        $("[data-host]", row).textContent = service.up
          ? (service.host ? `container ${service.host}` : "running")
          : service.noDatabase ? "running, but can't reach the database" : "not running";
      }
      $$(`.tool-service[data-service-key="${service.key}"] .dot`).forEach((dot) => setDot(dot, state));
    });
    const cacheState = { connected: "ok", unavailable: "bad" }[cache] || "";
    const dbState = { connected: "ok", unreachable: "bad" }[database] || "";
    setDot($('.map-store[data-node="cache"] .dot', mapEl), cacheState);
    setDot($('.map-store[data-node="db"] .dot', mapEl), dbState);
    const cacheStore = $('.map-store[data-node="cache"]', mapEl);
    if (cacheStore) cacheStore.classList.toggle("down", cacheState === "bad");
    const dbStore = $('.map-store[data-node="db"]', mapEl);
    if (dbStore) dbStore.classList.toggle("down", dbState === "bad");

    const down = services.filter((s) => !s.up).map((s) => s.name);
    const time = checkedAt.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", second: "2-digit" });
    let note;
    if (!down.length) {
      note = `All ${services.length} service containers are answering. Checked every 10 seconds, last at ${time}.`;
    } else if (down.length === 1) {
      note = `${down[0]} isn't answering, so its tools show an error until it's back. Last checked at ${time}.`;
    } else if (down.length === 2) {
      note = `${down[0]} and ${down[1]} aren't answering, so their tools show an error until they're back. Last checked at ${time}.`;
    } else {
      note = `${down.length} of ${services.length} service containers aren't answering, so their tools show an error until they're back. Last checked at ${time}.`;
    }
    $("#map-note").textContent = note;

    if (firstStatus) {
      firstStatus = false;
      mapEl.classList.add("live");       // the wires light up once, as the first answers come in
    }
  });

  // The chaos lab marks a container on the map while a fault is switched on (it clears itself when the fault ends)
  const faultTimers = {};
  document.addEventListener("suite:fault", (event) => {
    const { key, fault } = event.detail;
    const row = $(`.map-row[data-node="${key}"]`, mapEl);
    if (!row) return;
    clearTimeout(faultTimers[key]);
    if (fault) {
      row.dataset.fault = fault.mode === "slow" ? "slow" : "errors";
      faultTimers[key] = setTimeout(() => { delete row.dataset.fault; }, (fault.seconds_left + 1) * 1000);
    } else {
      delete row.dataset.fault;
    }
  });

  // The database node shows how many results are saved; the overview lists the latest ones
  document.addEventListener("suite:history", (event) => {
    const { records, total, unavailable } = event.detail;
    const label = $('.map-store[data-node="db"] .map-store-label', mapEl);
    if (label) label.textContent = total === null ? "every saved result" : `${S.num(total)} result${total === 1 ? "" : "s"} saved`;
    $("#home-recent-count").textContent = total === null ? "" : `${S.num(total)} saved in PostgreSQL`;
    const list = $("#home-recent-list");
    if (unavailable) {
      list.innerHTML = '<li class="history-empty">History is unavailable right now. Calculations still work; they just aren\'t saved.</li>';
      return;
    }
    if (!records.length) {
      list.innerHTML = '<li class="history-empty">Nothing saved yet. Open a tool from the map and your results will appear here.</li>';
      return;
    }
    list.innerHTML = records.slice(0, 6).map((record, index) => {
      const tool = (S.RECORD_TOOLS[record.tool] || [null, record.tool])[1];
      return `<li><button class="history-item" type="button" data-index="${index}" title="Load into ${esc(tool)}">
        <span class="history-meta"><span>${esc(tool)}</span><span>${esc(S.ago(record.created_at))}</span></span>
        <span class="history-summary">${esc(record.summary)}</span>
      </button></li>`;
    }).join("");
  });

  $("#home-recent-list").addEventListener("click", (event) => {
    const item = event.target.closest(".history-item");
    if (item) S.openRecord(Number(item.dataset.index));
  });

  drawMap();

  // ------------------------------------------------------------------
  // Quick search: Ctrl K (⌘ K on a Mac) or / opens it
  // ------------------------------------------------------------------

  const palette = $("#palette");
  const input = $("#palette-input");
  const list = $("#palette-list");
  const onMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
  $$(".search-keys").forEach((kbd) => { kbd.textContent = onMac ? "⌘ K" : "Ctrl K"; });

  let matches = [];
  let active = 0;

  function entries() {
    const light = currentTheme() === "light";
    return [
      { id: "home", title: "Overview", detail: "System map and recent results", icon: "overview", run: () => go("home") },
      ...TOOLS.map((t) => ({ id: t.id, title: t.title, detail: t.service === "all" ? "Break a container on purpose and watch it recover" : `${t.group}, runs on ${S.SERVICE_NAMES[t.service]}`,
        icon: ICONS[t.id], words: t.words, run: () => go(t.id) })),
      { id: "theme", title: light ? "Switch to the dark theme" : "Switch to the light theme", detail: "Appearance",
        icon: light ? "moon" : "sun", words: "theme dark light mode colour color appearance", run: toggleTheme },
    ];
  }

  function go(tool) {
    location.hash = tool;
  }

  function score(entry, terms) {
    const title = entry.title.toLowerCase();
    const words = `${title} ${entry.id} ${entry.words || ""}`.toLowerCase();
    let total = 0;
    for (const term of terms) {
      if (title.startsWith(term)) total += 3;
      else if (title.split(/\s+/).some((w) => w.startsWith(term))) total += 2;
      else if (words.includes(term)) total += 1;
      else return 0;
    }
    return total;
  }

  function update() {
    const terms = input.value.toLowerCase().split(/\s+/).filter(Boolean);
    const all = entries();
    matches = terms.length
      ? all.map((e) => [score(e, terms), e]).filter(([s]) => s > 0).sort((a, b) => b[0] - a[0]).map(([, e]) => e)
      : all;
    // Typing something that looks like a question adds a row that sends it to the solver (solver.js)
    const asking = terms.length && S.askEntry ? S.askEntry(input.value.trim()) : null;
    if (asking) matches = asking.first ? [asking.entry, ...matches] : [...matches, asking.entry];
    active = Math.min(active, Math.max(matches.length - 1, 0));
    list.innerHTML = matches.length
      ? matches.map((e, i) => `
        <li class="palette-item${i === active ? " active" : ""}" id="palette-${e.id}" role="option"
            aria-selected="${i === active}" data-index="${i}">
          ${icon(e.icon)}<span class="palette-title">${esc(e.title)}</span><span class="palette-detail">${esc(e.detail)}</span>
        </li>`).join("")
      : `<li class="palette-empty" role="presentation">No tool matches "${esc(input.value)}". Try a word like graph, loan or matrix.</li>`;
    if (matches.length) input.setAttribute("aria-activedescendant", `palette-${matches[active].id}`);
    else input.removeAttribute("aria-activedescendant");
  }

  function openPalette() {
    if (palette.open) return;
    input.value = "";
    active = 0;
    update();
    palette.showModal();
    input.focus();
  }

  function choose(index) {
    const entry = matches[index];
    if (!entry) return;
    palette.close();
    entry.run();
  }

  input.addEventListener("input", () => { active = 0; update(); });
  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!matches.length) return;
      active = (active + (event.key === "ArrowDown" ? 1 : -1) + matches.length) % matches.length;
      update();
      const item = $(`#palette-${matches[active].id}`);
      if (item) item.scrollIntoView({ block: "nearest" });
    } else if (event.key === "Enter") {
      event.preventDefault();
      choose(active);
    }
  });
  list.addEventListener("click", (event) => {
    const item = event.target.closest(".palette-item");
    if (item) choose(Number(item.dataset.index));
  });
  list.addEventListener("mousemove", (event) => {
    const item = event.target.closest(".palette-item");
    if (item && Number(item.dataset.index) !== active) { active = Number(item.dataset.index); update(); }
  });
  // A click on the dimmed backdrop closes the search
  palette.addEventListener("click", (event) => { if (event.target === palette) palette.close(); });

  $("#open-search").addEventListener("click", openPalette);
  document.addEventListener("keydown", (event) => {
    const typing = event.target.closest("input, textarea, select, [contenteditable]");
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      openPalette();
    } else if (event.key === "/" && !typing && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault();
      openPalette();
    }
  });
})();
