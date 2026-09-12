/* Calibraton3000 swipe UI. Vanilla, no build step. */
(() => {
  "use strict";

  const SESSION_ID =
    (crypto.randomUUID && crypto.randomUUID()) ||
    `s-${Date.now()}-${Math.random().toString(16).slice(2)}`;

  const el = (id) => document.getElementById(id);
  const card = el("card");
  const empty = el("empty");
  const btnLike = el("btn-like");
  const btnDislike = el("btn-dislike");
  const wouldApply = el("would-apply");
  const wouldGet = el("would-get");

  let current = null;
  let sessionCount = 0;
  let busy = false;

  // ---- helpers ----------------------------------------------------------

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
    btnLike.disabled = state;
    btnDislike.disabled = state;
  }

  // ---- rendering --------------------------------------------------------

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
    el("title").textContent = job.title || "Untitled role";
    el("company").textContent = job.company || "Unknown company";
    el("blurb").textContent = job.blurb || "";
    el("score").textContent = Number(job.score ?? 0).toFixed(1);
    wouldApply.checked = false;
    wouldGet.checked = false;
    setBusy(false);
  }

  async function loadNext() {
    const { ok, body } = await api("/api/next");
    if (!ok) { toast("Could not load the next job."); return; }
    render(body.job, body.remaining);
  }

  // ---- swiping ----------------------------------------------------------

  async function swipe(verdict) {
    if (busy || !current) return;
    setBusy(true);
    card.classList.add(verdict === "like" ? "gone-right" : "gone-left");

    const { ok, body } = await api("/api/decision", {
      method: "POST",
      body: JSON.stringify({
        job_id: current.id,
        verdict,
        would_apply: wouldApply.checked,
        would_get: wouldGet.checked,
        session_id: SESSION_ID,
      }),
    });

    if (!ok) {
      toast(body.detail || "Could not record that swipe.");
      card.className = "card";
      setBusy(false);
      return;
    }

    sessionCount = body.session_count;
    el("session-count").textContent = sessionCount;
    setTimeout(loadNext, 160);
  }

  btnLike.addEventListener("click", () => swipe("like"));
  btnDislike.addEventListener("click", () => swipe("dislike"));

  document.addEventListener("keydown", (event) => {
    if (event.target.matches("input, textarea")) return;
    if (event.key === "ArrowRight") swipe("like");
    if (event.key === "ArrowLeft") swipe("dislike");
  });

  // Touch swipe. Optional sugar; buttons and keys remain the real interface.
  let touchStartX = null;
  card.addEventListener("touchstart", (e) => { touchStartX = e.changedTouches[0].clientX; }, { passive: true });
  card.addEventListener("touchend", (e) => {
    if (touchStartX === null) return;
    const dx = e.changedTouches[0].clientX - touchStartX;
    touchStartX = null;
    if (Math.abs(dx) > 70) swipe(dx > 0 ? "like" : "dislike");
  }, { passive: true });

  // ---- session end ------------------------------------------------------

  el("btn-end").addEventListener("click", async () => {
    const { body } = await api("/api/recalibrate", { method: "POST" });
    if (body.status === "refused") {
      toast(body.reason, 6000);
      return;
    }
    const moved = Object.values(body.delta || {}).filter((d) => Math.abs(d) > 1e-9).length;
    toast(`Recalibrated on ${body.n} decisions. ${moved} weight(s) moved. Logged to ${body.log}.`, 7000);
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
