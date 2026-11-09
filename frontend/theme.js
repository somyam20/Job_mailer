/* Theme (mode + accent), live wallpaper and logo shared by every page. */
(() => {
  const store = {
    get: (k, d) => { try { return localStorage.getItem("jm_" + k) || d; } catch { return d; } },
    set: (k, v) => { try { localStorage.setItem("jm_" + k, v); } catch {} },
  };
  const ACCENTS = { indigo: ["#5b5bf7", "#a855f7"], ocean: ["#0891b2", "#2563eb"], sunset: ["#f97316", "#e11d48"],
                    forest: ["#059669", "#65a30d"], rose: ["#db2777", "#9333ea"] };
  const WALLPAPERS = { planes: "Planes", aurora: "Aurora", stars: "Starfield", off: "Off" };
  const html = document.documentElement;
  const darkQuery = matchMedia("(prefers-color-scheme: dark)");
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

  const state = { mode: store.get("mode", "auto"), accent: store.get("accent", "indigo"), wall: store.get("wall", "planes") };

  function apply() {
    const dark = state.mode === "dark" || (state.mode === "auto" && darkQuery.matches);
    html.dataset.mode = dark ? "dark" : "light";
    html.dataset.accent = state.accent;
    wallpaper.restart();
  }
  darkQuery.addEventListener("change", () => state.mode === "auto" && apply());

  // ---------- logo: an envelope folding into a paper plane ----------
  const LOGO = `<svg viewBox="0 0 48 48" aria-hidden="true"><defs><linearGradient id="lg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="var(--a1)"/><stop offset="1" stop-color="var(--a2)"/></linearGradient></defs>
    <rect x="2" y="2" width="44" height="44" rx="13" fill="url(#lg)"/>
    <path d="M11 24.5 37 13l-6.5 23-7.2-7.6-5.3 4.1.7-7.3z" fill="#fff"/>
    <path d="M18.7 25.9 37 13 23.3 28.4" fill="none" stroke="url(#lg)" stroke-width="1.6" stroke-linejoin="round"/>
    <path d="M8 33c3-1 5 1 8 0" stroke="#fff" stroke-opacity=".7" stroke-width="2" stroke-linecap="round" fill="none"/></svg>`;
  document.querySelectorAll("[data-logo]").forEach(el => {
    el.classList.add("logo");
    el.innerHTML = LOGO + `<span>Job<b>Mailer</b></span>`;
  });

  // ---------- live wallpaper (canvas) ----------
  const wallpaper = (() => {
    let canvas, ctx, raf, items = [], w, h, t = 0;
    const css = v => getComputedStyle(html).getPropertyValue(v).trim();
    function size() {
      const dpr = Math.min(devicePixelRatio || 1, 2);
      w = innerWidth; h = innerHeight;
      canvas.width = w * dpr; canvas.height = h * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    function seed() {
      const n = state.wall === "stars" ? Math.round(w * h / 9000) : state.wall === "aurora" ? 4 : Math.max(8, Math.round(w / 110));
      items = Array.from({ length: n }, (_, i) => ({
        x: Math.random() * w, y: Math.random() * h, s: .6 + Math.random() * .9, r: Math.random() * Math.PI * 2,
        v: .25 + Math.random() * .6, ph: Math.random() * 6.28, kind: i % 3 === 0 ? "env" : "plane",
      }));
    }
    function plane(x, y, s, rot, color) {
      ctx.save(); ctx.translate(x, y); ctx.rotate(rot); ctx.scale(s, s);
      ctx.fillStyle = color; ctx.beginPath();
      ctx.moveTo(-14, 2); ctx.lineTo(16, -10); ctx.lineTo(8, 14); ctx.lineTo(1, 6); ctx.closePath(); ctx.fill();
      ctx.globalAlpha *= .6; ctx.beginPath(); ctx.moveTo(1, 6); ctx.lineTo(16, -10); ctx.lineTo(-2, 11); ctx.closePath(); ctx.fill();
      ctx.restore();
    }
    function envelope(x, y, s, rot, color) {
      ctx.save(); ctx.translate(x, y); ctx.rotate(rot * .2); ctx.scale(s, s);
      ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.lineJoin = "round";
      ctx.strokeRect(-12, -8, 24, 16); ctx.beginPath(); ctx.moveTo(-12, -8); ctx.lineTo(0, 2); ctx.lineTo(12, -8); ctx.stroke();
      ctx.restore();
    }
    function frame() {
      t += 1;
      const dark = html.dataset.mode === "dark";
      const a1 = css("--a1"), a2 = css("--a2");
      ctx.clearRect(0, 0, w, h);
      if (state.wall === "aurora") {
        items.forEach((b, i) => {
          const x = w * (.2 + .6 * (.5 + .5 * Math.sin(t * .002 * b.v + b.ph)));
          const y = h * (.2 + .6 * (.5 + .5 * Math.cos(t * .0017 * b.v + b.ph * 1.3)));
          const r = Math.max(w, h) * (.35 + .1 * b.s);
          const g = ctx.createRadialGradient(x, y, 0, x, y, r);
          g.addColorStop(0, (i % 2 ? a1 : a2) + (dark ? "40" : "33")); g.addColorStop(1, "transparent");
          ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
        });
      } else if (state.wall === "stars") {
        items.forEach(p => {
          p.y += p.v * .15; if (p.y > h) { p.y = 0; p.x = Math.random() * w; }
          ctx.globalAlpha = (dark ? .5 : .35) + .4 * Math.sin(t * .03 * p.v + p.ph);
          ctx.fillStyle = p.kind === "env" ? a2 : a1;
          ctx.beginPath(); ctx.arc(p.x, p.y, p.s * 1.6, 0, 6.28); ctx.fill();
        });
        ctx.globalAlpha = 1;
      } else {
        items.forEach(p => {
          p.x += p.v * 1.1; p.y -= p.v * .45 + Math.sin(t * .02 + p.ph) * .25;
          if (p.x > w + 40 || p.y < -40) { p.x = -30; p.y = h * (.2 + Math.random() * .9); }
          ctx.globalAlpha = dark ? .22 : .16;
          const c = p.kind === "env" ? a2 : a1;
          p.kind === "env" ? envelope(p.x, p.y, p.s * 1.1, Math.sin(t * .01 + p.ph), c)
                           : plane(p.x, p.y, p.s * 1.2, -.35 + Math.sin(t * .015 + p.ph) * .12, c);
        });
        ctx.globalAlpha = 1;
      }
      if (!reduced) raf = requestAnimationFrame(frame);
    }
    function restart() {
      if (!canvas) {
        canvas = document.createElement("canvas"); canvas.id = "wallpaper"; canvas.setAttribute("aria-hidden", "true");
        document.body.prepend(canvas); ctx = canvas.getContext("2d");
        addEventListener("resize", () => { size(); seed(); });
        document.addEventListener("visibilitychange", () => { cancelAnimationFrame(raf); if (!document.hidden && state.wall !== "off") frame(); });
      }
      cancelAnimationFrame(raf);
      size();
      if (state.wall === "off") { ctx.clearRect(0, 0, w, h); return; }
      seed(); requestAnimationFrame(frame);  // after the new theme's colours are in place
    }
    return { restart };
  })();

  // ---------- theme picker: any [data-theme-picker] button opens it ----------
  function picker(btn) {
    const host = btn.parentElement; host.style.position = "relative";
    let pop = host.querySelector(".theme-pop");
    if (pop) return pop.remove();
    pop = document.createElement("div"); pop.className = "theme-pop";
    const draw = () => {
      pop.innerHTML = `<h5>Mode</h5><div class="seg">${["light", "dark", "auto"].map(m =>
          `<button type="button" data-m="${m}" class="${state.mode === m ? "on" : ""}">${{ light: "☀ Light", dark: "☾ Dark", auto: "◐ Auto" }[m]}</button>`).join("")}</div>
        <h5>Colour</h5><div class="swatches">${Object.entries(ACCENTS).map(([k, [c1, c2]]) =>
          `<button type="button" class="swatch ${state.accent === k ? "on" : ""}" data-a="${k}" title="${k}" aria-label="${k} theme"
             style="background:linear-gradient(135deg,${c1},${c2})"></button>`).join("")}</div>
        <h5>Live wallpaper</h5><div class="seg">${Object.entries(WALLPAPERS).map(([k, v]) =>
          `<button type="button" data-w="${k}" class="${state.wall === k ? "on" : ""}">${v}</button>`).join("")}</div>`;
    };
    pop.onclick = e => {
      e.stopPropagation();
      const b = e.target.closest("button"); if (!b) return;
      if (b.dataset.m) store.set("mode", state.mode = b.dataset.m);
      if (b.dataset.a) store.set("accent", state.accent = b.dataset.a);
      if (b.dataset.w) store.set("wall", state.wall = b.dataset.w);
      apply(); draw();
    };
    draw(); host.appendChild(pop);
    setTimeout(() => document.addEventListener("click", function off(e) {
      if (!host.contains(e.target)) { pop.remove(); document.removeEventListener("click", off); }
    }));
  }
  document.addEventListener("click", e => { const b = e.target.closest("[data-theme-picker]"); if (b) picker(b); });

  window.JMTheme = { apply, state };
  apply();
})();
