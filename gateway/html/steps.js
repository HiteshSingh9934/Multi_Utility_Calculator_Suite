/* Calculator Suite: the step player.
 *
 * A worked solution is written into the page as a list of steps (see stepsHTML in solver.js).
 * This file plays that list like a teacher at a board:
 *
 *   - the steps come one at a time, each opening smoothly under the one before;
 *   - the line of working is written from left to right, and the result on its right-hand side lights up;
 *   - a rail joins the numbered markers as each step is finished;
 *   - the answer closes the solution.
 *
 * The person is in control: Pause / Play, Next step, Replay, Show all, and a speed button (1x, 2x, 3x).
 * With "reduce motion" switched on in the system, everything is shown at once and the controls are hidden.
 * The text of every step is in the page from the start, so a screen reader or a printout gets all of it.
 *
 * Loaded after app.js (it uses window.Suite) and before solver.js.
 */
(() => {
  "use strict";

  const S = window.Suite;
  const REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)");

  // Time, in milliseconds at normal speed: the title, then the explanation, then the line of working
  const WORKING_STARTS = 480;
  const HOLD = 650;                       // a pause after a step, so there is time to read it
  const SPEEDS = [{ label: "1×", k: 1 }, { label: "2×", k: 0.5 }, { label: "3×", k: 0.34 }];

  const wipeTime = (step) => {
    const math = step.querySelector(".step-math");
    const length = math ? math.textContent.length : 0;
    const cells = step.querySelectorAll(".step-matrix span").length;
    return Math.min(1100, Math.max(450, length * 20)) + Math.min(cells * 40, 500);
  };

  const stepTime = (step) => {
    const text = step.querySelector(".step-text");
    const reading = text ? Math.min(900, text.textContent.length * 9) : 0;
    return Math.max(WORKING_STARTS + wipeTime(step), 220 + reading) + HOLD;
  };

  class Player {
    constructor(root) {
      this.root = root;
      this.steps = Array.from(root.querySelectorAll(".steps > .step"));
      this.answer = root.querySelector(".sp-answer");
      this.count = root.querySelector(".sp-count b");
      this.bar = root.querySelector(".sp-bar i");
      this.playButton = root.querySelector(".sp-play");
      this.speedButton = root.querySelector(".sp-speed");
      this.shown = 0;
      this.speed = 0;
      this.timer = 0;
      this.playing = false;
      this.following = true;
      this.onFinish = null;
      this.loop = false;
      this.autoScroll = true;                 // false for the overview's example, which must never move the page

      // Matrix cells come in one after another
      this.steps.forEach((step) => {
        step.querySelectorAll(".step-matrix span").forEach((cell, i) => cell.style.setProperty("--i", i));
        step.style.setProperty("--wipe", wipeTime(step));
      });

      root.addEventListener("click", (event) => this.click(event));
      // Someone who scrolls for themselves is not dragged back to the step being written
      ["wheel", "touchstart", "keydown"].forEach((name) =>
        window.addEventListener(name, () => { this.following = false; }, { passive: true }));
      this.draw();
    }

    // ---------- state ----------

    get finished() { return this.shown >= this.steps.length; }
    get alive() { return this.root.isConnected; }

    draw() {
      const total = this.steps.length;
      this.root.classList.toggle("is-playing", this.playing);
      this.root.classList.toggle("is-finished", this.finished);
      if (this.count) this.count.textContent = String(this.shown);
      if (this.bar) this.bar.style.transform = `scaleX(${total ? this.shown / total : 1})`;
      if (this.playButton) {
        const label = this.playing ? "Pause" : this.finished ? "Replay" : "Play";
        this.playButton.setAttribute("aria-label", label);
        this.playButton.title = label;
        this.playButton.querySelector("span").textContent = label;
        this.playButton.querySelector("use").setAttribute("href", this.playing ? "#i-pause" : this.finished ? "#i-replay" : "#i-play");
      }
    }

    reveal(index, { instant = false } = {}) {
      const step = this.steps[index];
      if (!step) return;
      this.steps.forEach((other) => other.classList.remove("is-live"));
      if (index > 0) this.steps[index - 1].classList.add("is-done");
      step.classList.add("is-shown");
      // "instant" steps appear in their final state, with none of the writing animation
      step.classList.add(instant ? "is-instant" : "is-live");
      this.shown = index + 1;
      if (this.finished) this.finishSoon(step, instant);
      this.draw();
      if (!instant) this.follow(step);
    }

    finishSoon(step, instant) {
      const done = () => {
        if (!this.alive || this.shown < this.steps.length) return;
        step.classList.add("is-done");
        step.classList.remove("is-live");
        if (this.answer) this.answer.classList.add("is-shown");
        this.draw();
      };
      if (instant) done();
      else setTimeout(done, (WORKING_STARTS + wipeTime(step)) * SPEEDS[this.speed].k + 200);
    }

    follow(element) {
      if (!this.autoScroll || !this.following) return;
      // Give the step a moment to open, then bring it into view only if it is not already
      setTimeout(() => {
        if (!this.alive || !this.following) return;
        const box = element.getBoundingClientRect();
        if (box.bottom > window.innerHeight - 24 || box.top < 70) {
          element.scrollIntoView({ block: "center", behavior: "smooth" });
        }
      }, 120);
    }

    // ---------- playing ----------

    play() {
      if (this.finished) { this.replay(); return; }
      this.playing = true;
      this.draw();
      this.tick();
    }

    pause() {
      this.playing = false;
      clearTimeout(this.timer);
      this.draw();
    }

    tick() {
      clearTimeout(this.timer);
      if (!this.playing || !this.alive) return;
      if (this.finished) {
        this.stop();
        // A looping player (the overview's example) starts again after a pause
        if (this.loop) this.loopTimer = setTimeout(() => { if (this.alive && !this.playing && this.finished) this.replay(); }, 5200);
        return;
      }
      this.reveal(this.shown);
      const step = this.steps[this.shown - 1];
      this.timer = setTimeout(() => this.tick(), stepTime(step) * SPEEDS[this.speed].k);
    }

    stop() {
      this.playing = false;
      this.draw();
      const callback = this.onFinish;
      this.onFinish = null;
      if (callback) setTimeout(callback, 400);
    }

    next() {
      this.pause();
      if (!this.finished) this.reveal(this.shown);
    }

    showAll() {
      this.pause();
      for (let i = this.shown; i < this.steps.length; i += 1) this.reveal(i, { instant: true });
      this.steps.forEach((step) => step.classList.add("is-done"));
      if (this.answer) this.answer.classList.add("is-shown", "is-instant");
      this.draw();
      this.stop();
    }

    replay() {
      this.pause();
      // Back to the empty state at once (transitions off), then play from the first step
      this.root.classList.add("no-motion");
      this.steps.forEach((step) => step.classList.remove("is-shown", "is-live", "is-done", "is-instant"));
      if (this.answer) this.answer.classList.remove("is-shown", "is-instant");
      this.shown = 0;
      this.draw();
      void this.root.offsetWidth;
      this.root.classList.remove("no-motion");
      this.following = true;
      this.playing = true;
      this.draw();
      this.timer = setTimeout(() => this.tick(), 300);
    }

    cycleSpeed() {
      this.speed = (this.speed + 1) % SPEEDS.length;
      this.root.style.setProperty("--k", SPEEDS[this.speed].k);
      this.speedButton.textContent = SPEEDS[this.speed].label;
      this.speedButton.setAttribute("aria-label", `Speed ${SPEEDS[this.speed].label}`);
    }

    click(event) {
      const button = event.target.closest("button");
      if (!button || !this.root.contains(button)) return;
      if (button.classList.contains("sp-play")) { this.playing ? this.pause() : this.play(); }
      else if (button.classList.contains("sp-next")) this.next();
      else if (button.classList.contains("sp-replay")) this.replay();
      else if (button.classList.contains("sp-all")) this.showAll();
      else if (button.classList.contains("sp-speed")) this.cycleSpeed();
    }
  }

  // Starts the players inside `root`. Two players on one page (the derivative and the integral) play one after the other.
  S.mountSteps = (root, { autoplay = true } = {}) => {
    const players = Array.from(root.querySelectorAll(".steps-player")).map((element) => new Player(element));
    if (!players.length) return [];
    if (REDUCED.matches) {
      players.forEach((player) => player.showAll());
      return players;
    }
    if (!autoplay) return players;
    players.forEach((player, i) => {
      const following = players[i + 1];
      if (following) player.onFinish = () => { if (following.alive && !following.shown) following.play(); };
    });
    // (not if the person has already pressed something in the meantime)
    setTimeout(() => { if (players[0].alive && !players[0].shown && !players[0].playing) players[0].play(); }, 350);
    return players;
  };
})();
