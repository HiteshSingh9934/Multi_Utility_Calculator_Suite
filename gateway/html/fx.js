/* Calculator Suite: small finishing touches for the interface (v3.3).
 *
 *   - the overview headline arrives one word at a time (the animation itself is in styles.css);
 *   - every tool page shows its menu icon beside the heading;
 *   - result panels, tiles and steps get a soft glow that follows the pointer;
 *   - the aurora behind the overview headline is started here (aurora.js);
 *   - buttons throw a few sparks when pressed.
 *
 * The aurora and the sparks are from React Bits (reactbits.dev, MIT licence with the Commons Clause).
 *
 * Nothing here is needed to use the app: without this file everything still works.
 * With "reduce motion" switched on in the system, the glow follows nothing and the headline is plain.
 */
(() => {
  "use strict";

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");

  // The headline: each word in its own span, so the stylesheet can bring them in one after another
  const title = document.getElementById("h-home");
  if (title && !title.querySelector(".w")) {
    const words = title.textContent.trim().split(/\s+/);
    title.setAttribute("aria-label", words.join(" "));
    title.innerHTML = words.map((word, i) => `<span class="w" aria-hidden="true" style="--i:${i}">${word}</span>`).join(" ");
  }

  // Every tool page gets the icon of its menu entry beside the heading
  document.querySelectorAll(".tool:not(.home)[data-tool]").forEach((tool) => {
    const head = tool.querySelector(".tool-head");
    const use = document.querySelector(`.tool-nav a[data-tool="${tool.dataset.tool}"] use`);
    if (!head || !use || head.querySelector(".tool-badge")) return;
    head.insertAdjacentHTML("afterbegin",
      `<span class="tool-badge" aria-hidden="true"><svg class="icon"><use href="${use.getAttribute("href")}"/></svg></span>`);
  });

  // The aurora behind the overview headline (aurora.js, from React Bits). It follows the theme.
  const auroraBox = document.getElementById("home-aurora");
  if (auroraBox && window.mountAurora) {
    const colours = () => document.documentElement.dataset.theme === "light"
      ? { colorStops: ["#6F97D6", "#F2A93B", "#6F97D6"], lightMode: true, opacity: 0.95 }
      : { colorStops: ["#3F66A8", "#F5A524", "#3F66A8"], lightMode: false, opacity: 0.62 };
    const aurora = window.mountAurora(auroraBox, { ...colours(), amplitude: 1.15, blend: 0.7, height: 0.52, glow: 0.7, layers: 2, speed: 0.8 });
    if (aurora) {
      auroraBox.classList.add("is-on");
      new MutationObserver(() => aurora.update(colours()))
        .observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    }
  }

  // Click sparks (the "ClickSpark" effect from React Bits): a small burst of lines where a button is pressed
  const sparkLayer = document.createElement("canvas");
  sparkLayer.className = "spark-layer";
  sparkLayer.setAttribute("aria-hidden", "true");
  document.body.appendChild(sparkLayer);
  const paint = sparkLayer.getContext("2d");
  const bursts = [];
  let sparkFrame = 0;
  const fitSparks = () => {
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    sparkLayer.width = Math.round(window.innerWidth * ratio);
    sparkLayer.height = Math.round(window.innerHeight * ratio);
    paint.setTransform(ratio, 0, 0, ratio, 0, 0);
  };
  const SPARK_MS = 520;
  const drawSparks = (now) => {
    sparkFrame = 0;
    paint.clearRect(0, 0, window.innerWidth, window.innerHeight);
    for (let i = bursts.length - 1; i >= 0; i -= 1) {
      const burst = bursts[i];
      const t = (now - burst.start) / SPARK_MS;
      if (t >= 1) { bursts.splice(i, 1); continue; }
      const ease = 1 - Math.pow(1 - t, 3);
      paint.strokeStyle = burst.colour;
      paint.lineWidth = 2;
      paint.lineCap = "round";
      paint.globalAlpha = 1 - t * t;
      burst.lines.forEach((line) => {
        const from = 8 + ease * line.reach * 0.55;
        const to = 8 + ease * line.reach;
        paint.beginPath();
        paint.moveTo(burst.x + Math.cos(line.angle) * from, burst.y + Math.sin(line.angle) * from);
        paint.lineTo(burst.x + Math.cos(line.angle) * to, burst.y + Math.sin(line.angle) * to);
        paint.stroke();
      });
    }
    paint.globalAlpha = 1;
    if (bursts.length) sparkFrame = requestAnimationFrame(drawSparks);
  };
  const SPARK_TARGETS = ".button-primary, .button-secondary, .preset, .sp-btn, .map-key";
  document.addEventListener("pointerdown", (event) => {
    if (reduced.matches || !event.target.closest || !event.target.closest(SPARK_TARGETS)) return;
    if (!sparkLayer.width) fitSparks();
    const count = 8;
    const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#f5a524";
    bursts.push({
      x: event.clientX, y: event.clientY, start: performance.now(), colour: accent,
      lines: Array.from({ length: count }, (_, i) => ({ angle: (i / count) * Math.PI * 2 + Math.random() * 0.3, reach: 24 + Math.random() * 10 })),
    });
    if (!sparkFrame) sparkFrame = requestAnimationFrame(drawSparks);
  }, { passive: true });
  window.addEventListener("resize", fitSparks);
  fitSparks();

  // The glow: the pointer's position, relative to the element under it, is written to two custom properties
  const GLOW = ".readout, .tile, .chaos-tile, .steps-player, .map-key, .preset";
  let frame = 0;
  document.addEventListener("pointermove", (event) => {
    if (reduced.matches || event.pointerType === "touch") return;
    const target = event.target.closest && event.target.closest(GLOW);
    if (!target) return;
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      const box = target.getBoundingClientRect();
      target.style.setProperty("--mx", `${event.clientX - box.left}px`);
      target.style.setProperty("--my", `${event.clientY - box.top}px`);
    });
  }, { passive: true });
})();
