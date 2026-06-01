/* Shared Chart.js helpers for the treasurer admin tabs (overview / dues /
 * tuition). Colors are read from the DaisyUI theme CSS vars at call time so
 * charts match silk (light) / abyss (dark). Requires Chart.js to be loaded
 * first. Exposes window.LSPCharts. */
(function () {
  "use strict";

  function cssVar(name, fallback) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }

  function colors() {
    return {
      primary: cssVar("--color-primary", "#5f8a5f"),
      success: cssVar("--color-success", "#5f8a5f"),
      info:    cssVar("--color-info", "#6b8fb5"),
      warning: cssVar("--color-warning", "#d4a017"),
      error:   cssVar("--color-error", "#b5483d"),
      neutral: cssVar("--color-base-content", "#222"),
    };
  }

  var usd0 = new Intl.NumberFormat("en-US", {
    style: "currency", currency: "USD", maximumFractionDigits: 0,
  });

  function el(id) { return document.getElementById(id); }

  function readJSON(id) {
    var n = el(id);
    return n ? JSON.parse(n.textContent) : null;
  }

  function ensureDefaults() {
    if (!window.Chart) return false;
    Chart.defaults.color = cssVar("--color-base-content", "#222");
    Chart.defaults.borderColor = "rgba(127, 127, 127, 0.15)";
    return true;
  }

  /* A compact single-row horizontal stacked money bar.
   * segments: [{ label, value, color }] */
  function moneyBar(canvasId, segments) {
    var c = el(canvasId);
    if (!c || !ensureDefaults()) return;
    var total = segments.reduce(function (a, s) { return a + (s.value || 0); }, 0);
    new Chart(c, {
      type: "bar",
      data: {
        labels: [""],
        datasets: segments.map(function (s) {
          return { label: s.label, data: [s.value || 0], backgroundColor: s.color, borderWidth: 0, barThickness: 26 };
        }),
      },
      options: {
        indexAxis: "y", responsive: true, maintainAspectRatio: false,
        scales: {
          x: { stacked: true, beginAtZero: true, display: false, max: total || 1 },
          y: { stacked: true, display: false },
        },
        plugins: {
          legend: { display: true, position: "bottom", labels: { boxWidth: 10, font: { size: 11 } } },
          tooltip: { callbacks: { label: function (ctx) { return ctx.dataset.label + ": " + usd0.format(ctx.parsed.x); } } },
        },
      },
    });
  }

  /* Vertical bar chart. datasets: [{ label, data, color }].
   * opts: { stacked: bool, currency: bool } */
  function bars(canvasId, labels, datasets, opts) {
    var c = el(canvasId);
    if (!c || !ensureDefaults()) return;
    opts = opts || {};
    new Chart(c, {
      type: "bar",
      data: {
        labels: labels,
        datasets: datasets.map(function (d) {
          return {
            label: d.label, data: d.data,
            backgroundColor: d.color, borderColor: d.color,
            borderWidth: opts.stacked ? 0 : 1,
          };
        }),
      },
      options: {
        responsive: true,
        scales: {
          x: { stacked: !!opts.stacked },
          y: {
            stacked: !!opts.stacked, beginAtZero: true,
            ticks: opts.currency ? { callback: function (v) { return usd0.format(v); } } : {},
          },
        },
        plugins: {
          legend: { display: datasets.length > 1 },
          tooltip: {
            callbacks: opts.currency ? {
              label: function (ctx) {
                return (ctx.dataset.label ? ctx.dataset.label + ": " : "") + usd0.format(ctx.parsed.y);
              },
            } : {},
          },
        },
      },
    });
  }

  window.LSPCharts = { colors: colors, readJSON: readJSON, moneyBar: moneyBar, bars: bars };
})();
