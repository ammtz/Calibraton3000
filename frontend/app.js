/* Calibraton3000. You gut-check a ranker's placement; it learns where that ranker is wrong. */
(() => {
  "use strict";

  const SESSION_ID =
    (crypto.randomUUID && crypto.randomUUID()) ||
    `s-${Date.now()}-${Math.random().toString(16).slice(2)}`;

  const el = (id) => document.getElementById(id);
  const card = el("card");
  const empty = el("empty");
  const buttons = [...document.querySelectorAll("[data-rating]")];
  const wouldApply = el("would-apply");
  const wouldGet = el("would-get");

  let current = null;
  let busy = false;

  async function api(path, options) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    const body = await res.json().catch(() => ({}));
    return { ok: res.ok, status: res.status, body };
  }

  let toastTimer = null;
  function toast(message, ms = 4000) {
    const node = el("toast");
    node.textContent = message;
    node.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { node.hidden = true; }, ms);
  }

  function setBusy(state) {
    busy = state;
    buttons.forEach((b) => { b.disabled = state; });
  }

  function render(job, remaining) {
    current = job;
    el("remaining").textContent = remaining ? `${remaining} left` : "";

    if (!job) {
      card.hidden = true;
      empty.hidden = false;
      setBusy(true);
      return;
    }

    empty.hidden = true;
    card.hidden = false;
    card.className = "card";

    // The source names itself in the payload, or stays anonymous. Either works.
    const who = job.source || "the ranker";

    if (job.scored) {
      el("rank").textContent =
        job.rank && job.rank_total ? `#${job.rank} of ${job.rank_total}` : "ranked";
      el("rank").className = "rank";
      el("prompt").textContent = `Did ${who} put this in the right place?`;
    } else {
      // No rank to check, so the rating reads as an absolute call. Trained apart.
      el("rank").textContent = "UNRANKED";
      el("rank").className = "rank unscored";
      el("prompt").textContent = `${who} couldn't rank this one. Call it yourself.`;
    }

    el("known").textContent =
      job.known != null && job.known_total ? `${job.known}/${job.known_total} known` : "";
    el("title").textContent = job.title || "Untitled role";
    el("company").textContent = job.company || "Unknown company";
    el("blurb").textContent = job.blurb || "";

    wouldApply.checked = false;
    wouldGet.checked = false;
    setBusy(false);
  }

  async function loadNext() {
    const { ok, body } = await api("/api/next");
    if (!ok) { toast("Could not load the next card."); return; }
    render(body.job, body.remaining);
  }

  async function rate(rating) {
    if (busy || !current) return;
    setBusy(true);
    card.classList.add(rating >= 4 ? "gone-right" : rating <= 2 ? "gone-left" : "gone-down");

    const { ok, body } = await api("/api/decision", {
      method: "POST",
      body: JSON.stringify({
        job_id: current.id,
        rating,
        would_apply: wouldApply.checked,
        would_get: wouldGet.checked,
        session_id: SESSION_ID,
      }),
    });

    if (!ok) {
      toast(body.detail || "Could not record that rating.");
      card.className = "card";
      setBusy(false);
      return;
    }

    el("session-count").textContent = body.session_count;
    setTimeout(loadNext, 160);
  }

  buttons.forEach((b) => b.addEventListener("click", () => rate(Number(b.dataset.rating))));

  document.addEventListener("keydown", (event) => {
    if (event.target.matches("input, textarea")) return;
    const key = Number(event.key);
    if (key >= 1 && key <= 5) rate(key);
    // Arrows kept for the extremes; the middle three need a number.
    if (event.key === "ArrowLeft") rate(1);
    if (event.key === "ArrowRight") rate(5);
  });

  let touchStartX = null;
  card.addEventListener("touchstart", (e) => { touchStartX = e.changedTouches[0].clientX; }, { passive: true });
  card.addEventListener("touchend", (e) => {
    if (touchStartX === null) return;
    const dx = e.changedTouches[0].clientX - touchStartX;
    touchStartX = null;
    if (Math.abs(dx) > 70) rate(dx > 0 ? 5 : 1);
  }, { passive: true });

  el("btn-end").addEventListener("click", async () => {
    const { body } = await api("/api/recalibrate", { method: "POST" });
    if (body.status === "refused") { toast(body.reason, 6000); return; }
    const moved = Object.values(body.delta || {}).filter((d) => Math.abs(d) > 1e-9).length;
    toast(
      `Recalibrated on ${body.trained_on} of ${body.n} decisions. ` +
      `${moved} dimension(s) moved. Logged to ${body.log}.`, 7000);
  });

  el("btn-trends").addEventListener("click", async () => {
    const { body } = await api("/api/trends");
    el("trends-body").textContent = body.count
      ? JSON.stringify(body.runs, null, 2)
      : "No recalibration runs logged yet.";
    el("trends-dialog").showModal();
  });

  el("btn-close-trends").addEventListener("click", () => el("trends-dialog").close());

  loadNext();
})();
