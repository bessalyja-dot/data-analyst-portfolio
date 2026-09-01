/* Маленький набор графиков на голом SVG: линия, горизонтальные бары, тепловая карта.
   Цвета берутся из CSS-переменных, поэтому тёмная тема работает без перерисовки. */

const SVG = "http://www.w3.org/2000/svg";
const el = (name, attrs = {}, text) => {
  const n = document.createElementNS(SVG, name);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (text != null) n.textContent = text;
  return n;
};

function frame(mount, w, h) {
  mount.innerHTML = "";
  const svg = el("svg", { viewBox: `0 0 ${w} ${h}`, role: "img" });
  const tip = document.createElement("div");
  tip.className = "tip";
  mount.append(svg, tip);
  const show = (html, x, y) => {
    tip.innerHTML = html;
    tip.style.opacity = 1;
    const box = mount.getBoundingClientRect();
    const px = (x / w) * box.width, py = (y / h) * box.height;
    tip.style.left = Math.min(Math.max(px - tip.offsetWidth / 2, 0), box.width - tip.offsetWidth) + "px";
    tip.style.top = Math.max(py - tip.offsetHeight - 12, 0) + "px";
  };
  const hide = () => (tip.style.opacity = 0);
  return { svg, show, hide };
}

const ticks = (max, count = 4) => {
  const step = Math.pow(10, Math.floor(Math.log10(max / count)));
  const s = [1, 2, 2.5, 5, 10].map((m) => m * step).find((v) => max / v <= count) || step * 10;
  return Array.from({ length: Math.floor(max / s) + 1 }, (_, i) => i * s);
};

/* Линия с вертикальным курсором и подсказкой по ближайшей точке. */
function lineChart(mount, { values, labels, tip, tickEvery = 3, area = true, yFmt = String }) {
  const w = 900, h = 300, pad = { l: 74, r: 18, t: 14, b: 30 };
  const { svg, show, hide } = frame(mount, w, h);
  const max = Math.max(...values) * 1.08;
  const X = (i) => pad.l + (i * (w - pad.l - pad.r)) / Math.max(1, values.length - 1);
  const Y = (v) => h - pad.b - (v / max) * (h - pad.t - pad.b);

  for (const t of ticks(max)) {
    svg.append(el("line", { x1: pad.l, x2: w - pad.r, y1: Y(t), y2: Y(t), stroke: "var(--grid)", "stroke-width": 1 }));
    svg.append(el("text", { x: pad.l - 10, y: Y(t) + 4, "text-anchor": "end", fill: "var(--ink-3)", "font-size": 12 }, yFmt(t)));
  }
  labels.forEach((l, i) => {
    if (i % tickEvery) return;
    svg.append(el("text", { x: X(i), y: h - 9, "text-anchor": "middle", fill: "var(--ink-3)", "font-size": 12 }, l));
  });

  const d = values.map((v, i) => `${i ? "L" : "M"}${X(i)},${Y(v)}`).join(" ");
  if (area) {
    svg.append(el("path", {
      d: `${d} L${X(values.length - 1)},${Y(0)} L${X(0)},${Y(0)} Z`,
      fill: "var(--accent-soft)",
    }));
  }
  svg.append(el("path", { d, fill: "none", stroke: "var(--accent)", "stroke-width": 2, "stroke-linejoin": "round" }));

  const cursor = el("line", { y1: pad.t, y2: h - pad.b, stroke: "var(--axis)", "stroke-width": 1, opacity: 0 });
  const dot = el("circle", { r: 4.5, fill: "var(--accent)", stroke: "var(--surface)", "stroke-width": 2, opacity: 0 });
  svg.append(cursor, dot);

  const hit = el("rect", { x: 0, y: 0, width: w, height: h, fill: "transparent" });
  svg.append(hit);
  hit.addEventListener("mousemove", (e) => {
    const box = svg.getBoundingClientRect();
    const rel = ((e.clientX - box.left) / box.width) * w;
    const i = Math.max(0, Math.min(values.length - 1, Math.round(((rel - pad.l) / (w - pad.l - pad.r)) * (values.length - 1))));
    cursor.setAttribute("x1", X(i)); cursor.setAttribute("x2", X(i)); cursor.setAttribute("opacity", 1);
    dot.setAttribute("cx", X(i)); dot.setAttribute("cy", Y(values[i])); dot.setAttribute("opacity", 1);
    show(tip(i), X(i), Y(values[i]));
  });
  hit.addEventListener("mouseleave", () => { cursor.setAttribute("opacity", 0); dot.setAttribute("opacity", 0); hide(); });
}

/* Горизонтальные бары с подписью значения на конце. */
function barsH(mount, { rows, fmt = String, tip }) {
  const barH = 26, gap = 12, w = 900, labelW = 150;
  const h = rows.length * (barH + gap) + 10;
  const { svg, show, hide } = frame(mount, w, h);
  const max = Math.max(...rows.map((r) => r.value));
  const full = w - labelW - 90;

  rows.forEach((r, i) => {
    const y = i * (barH + gap) + 4;
    svg.append(el("text", { x: 0, y: y + barH / 2 + 5, fill: "var(--ink-2)", "font-size": 14 }, r.label));
    const bw = Math.max(2, (r.value / max) * full);
    svg.append(el("rect", { x: labelW, y, width: bw, height: barH, rx: 4, fill: r.color || "var(--accent)" }));
    svg.append(el("text", { x: labelW + bw + 10, y: y + barH / 2 + 5, fill: "var(--ink-2)", "font-size": 13.5, "font-variant-numeric": "tabular-nums" }, fmt(r.value)));
    const hit = el("rect", { x: 0, y: y - gap / 2, width: w, height: barH + gap, fill: "transparent" });
    hit.addEventListener("mousemove", () => tip && show(tip(r), labelW + bw / 2, y));
    hit.addEventListener("mouseleave", hide);
    svg.append(hit);
  });
}

/* Тепловая карта на одном синем тоне: чем выше значение, тем темнее. */
function heatmap(mount, { matrix, rowLabels, colLabels, fmt = String, tip, cell = 34, labelW = 74 }) {
  const gapPx = 2;
  const w = labelW + colLabels.length * cell;
  const h = 24 + rowLabels.length * cell;
  const { svg, show, hide } = frame(mount, w, h);
  const flat = matrix.flat().filter((v) => v != null);
  const max = Math.max(...flat);

  colLabels.forEach((c, j) => svg.append(el("text", { x: labelW + j * cell + cell / 2, y: 14, "text-anchor": "middle", fill: "var(--ink-3)", "font-size": 11 }, c)));
  rowLabels.forEach((r, i) => {
    svg.append(el("text", { x: labelW - 10, y: 24 + i * cell + cell / 2 + 4, "text-anchor": "end", fill: "var(--ink-3)", "font-size": 11.5, "font-variant-numeric": "tabular-nums" }, r));
    matrix[i].forEach((v, j) => {
      if (v == null) return;
      const t = Math.min(1, v / max);
      const x = labelW + j * cell, y = 24 + i * cell;
      const rect = el("rect", {
        x: x + gapPx / 2, y: y + gapPx / 2, width: cell - gapPx, height: cell - gapPx, rx: 3,
        fill: "var(--seq-2)", "fill-opacity": (0.12 + 0.88 * t).toFixed(3),
      });
      rect.addEventListener("mousemove", () => show(tip(i, j, v), x + cell / 2, y));
      rect.addEventListener("mouseleave", hide);
      svg.append(rect);
      if (t > 0.18) {
        svg.append(el("text", {
          x: x + cell / 2, y: y + cell / 2 + 4, "text-anchor": "middle", "font-size": 10.5,
          "pointer-events": "none", "font-variant-numeric": "tabular-nums",
          fill: t > 0.62 ? "var(--surface)" : "var(--ink-2)",
        }, fmt(v)));
      }
    });
  });
}

function themeToggle(btn) {
  const apply = (t) => { document.documentElement.dataset.theme = t; btn.textContent = t === "dark" ? "Светлая" : "Тёмная"; };
  const stored = (() => { try { return localStorage.getItem("theme"); } catch { return null; } })();
  const start = stored || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  apply(start);
  btn.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    apply(next);
    try { localStorage.setItem("theme", next); } catch {}
  });
}

window.Charts = { lineChart, barsH, heatmap, themeToggle };
