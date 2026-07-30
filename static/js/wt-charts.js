/* Wealth Tracker — Chart.js helpers.
   One palette, one set of formatters, one grid style. Pages call
   WTCharts.line / bar / doughnut / sparkline and pass NO colours.

   Token values mirror static/css/wealth-design.css :root — keep in sync.

   NOTE: every chart uses maintainAspectRatio:false, so the <canvas> MUST live
   in a container with an explicit height (use the chart_card() macro, or
   wrap it in a div with style="height:320px"). Without one the chart
   collapses to zero height and appears blank. */
(function () {
    'use strict';

    var INK      = '#23251d';
    var BODY     = '#4d4f46';
    var MUTE     = '#6c6e63';
    var ASH      = '#9b9c92';
    var GRID     = '#dcdfd2';
    var BRAND    = '#f7a501';
    var BRAND_DK = '#b17816';
    var POS      = '#2c8c66';
    var NEG      = '#cd4239';
    var INFO     = '#2c84e0';
    var FONT     = "'IBM Plex Sans', system-ui, sans-serif";

    /* Categorical sequence for multi-series charts. Ordered so the first three
       are maximally distinguishable and no two adjacent entries share a hue
       family. NEVER reuse a colour inside one chart. */
    var PALETTE = [INK, BRAND, INFO, POS, NEG, BRAND_DK, MUTE, '#6b4fa8',
                   '#0f766e', '#9a3412'];

    var TONES = { pos: POS, neg: NEG, info: INFO, brand: BRAND, ink: INK, mute: MUTE };

    /* ---------------- formatters ---------------- */

    function fmtNum(n, digits) {
        if (n === null || n === undefined || isNaN(n)) return '—';
        return new Intl.NumberFormat('en-PK', {
            minimumFractionDigits: digits || 0,
            maximumFractionDigits: digits || 0
        }).format(Number(n));
    }

    function fmtMoney(n, ccy, digits) {
        if (n === null || n === undefined || isNaN(n)) return '—';
        return (ccy || 'Rs') + ' ' + fmtNum(n, digits);
    }

    function fmtPct(n, digits) {
        if (n === null || n === undefined || isNaN(n)) return '—';
        return Number(n).toFixed(digits === undefined ? 1 : digits) + '%';
    }

    /* Compact axis ticks — 1.2k / 3.4M. Replaces the (v/1000)+'k' hardcoded in
       page JS, which is wrong above a million. */
    function fmtCompact(n) {
        if (n === null || n === undefined || isNaN(n)) return '—';
        var v = Number(n);
        var neg = v < 0;
        var a = Math.abs(v);
        var out;
        if (a >= 1e9)      out = (a / 1e9).toFixed(a >= 1e10 ? 0 : 1) + 'B';
        else if (a >= 1e6) out = (a / 1e6).toFixed(a >= 1e7 ? 0 : 1) + 'M';
        else if (a >= 1e3) out = (a / 1e3).toFixed(a >= 1e4 ? 0 : 1) + 'k';
        else               out = String(Math.round(a));
        return (neg ? '-' : '') + out;
    }

    function hexToRgba(hex, alpha) {
        var h = String(hex).replace('#', '');
        if (h.length === 3) { h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2]; }
        var r = parseInt(h.substring(0, 2), 16);
        var g = parseInt(h.substring(2, 4), 16);
        var b = parseInt(h.substring(4, 6), 16);
        return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
    }

    /* ---------------- shared options ---------------- */

    function baseOptions(opts) {
        var o = opts || {};
        var currency = !!o.currency;
        var percent = !!o.percent;
        var showLegend = (o.showLegend === undefined || o.showLegend === null)
            ? true : !!o.showLegend;
        return {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: {
                    display: showLegend,
                    position: 'bottom',
                    labels: {
                        boxWidth: 12, padding: 15, color: BODY,
                        font: { family: FONT, size: 11 }
                    }
                },
                tooltip: {
                    backgroundColor: INK,
                    padding: 10,
                    cornerRadius: 6,
                    displayColors: true,
                    titleFont: { family: FONT, size: 12, weight: '700' },
                    bodyFont: { family: FONT, size: 12 },
                    callbacks: {
                        label: function (ctx) {
                            var v = ctx.parsed.y !== undefined ? ctx.parsed.y : ctx.parsed;
                            var txt = percent ? fmtPct(v)
                                : (currency ? fmtMoney(v, o.ccy) : fmtNum(v));
                            return (ctx.dataset.label ? ctx.dataset.label + ': ' : '') + txt;
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: { display: false },
                    border: { color: GRID },
                    ticks: { color: MUTE, font: { family: FONT, size: 11 } }
                },
                y: {
                    beginAtZero: true,
                    grid: { color: GRID, borderDash: [4, 4] },
                    border: { display: false },
                    ticks: {
                        color: MUTE,
                        font: { family: FONT, size: 11 },
                        callback: function (v) {
                            return percent ? fmtPct(v, 0) : fmtCompact(v);
                        }
                    }
                }
            }
        };
    }

    /* Shallow-merge overrides two levels deep (enough for scales.y.max). */
    function merge(base, extra) {
        if (!extra) return base;
        Object.keys(extra).forEach(function (k) {
            if (extra[k] && typeof extra[k] === 'object' && !Array.isArray(extra[k])
                && base[k] && typeof base[k] === 'object') {
                merge(base[k], extra[k]);
            } else {
                base[k] = extra[k];
            }
        });
        return base;
    }

    /* ---------------- safe renderer ---------------- */

    function safeRender(canvasId, config) {
        try {
            var el = document.getElementById(canvasId);
            if (!el) return null;
            if (typeof Chart === 'undefined') {
                console.warn('[WTCharts] Chart.js not loaded.');
                return null;
            }
            /* HTMX can swap a chart container back in; Chart.js throws
               "Canvas is already in use" unless the old instance is destroyed. */
            var prev = Chart.getChart(el);
            if (prev) prev.destroy();
            return new Chart(el, config);
        } catch (e) {
            console.error('[WTCharts] render failed for #' + canvasId, e);
            return null;
        }
    }

    function colourFor(series, i) {
        if (series && series.tone && TONES[series.tone]) return TONES[series.tone];
        return PALETTE[i % PALETTE.length];
    }

    /* ---------------- public helpers ---------------- */

    function line(canvasId, opts) {
        var o = opts || {};
        var series = o.series || [];
        if (!series.length) return null;
        var fill = (o.fill === undefined) ? true : !!o.fill;
        var datasets = series.map(function (s, i) {
            var c = colourFor(s, i);
            return {
                label: s.name || ('Series ' + (i + 1)),
                data: (s.data || []).map(Number),
                borderColor: c,
                backgroundColor: fill ? hexToRgba(c, 0.12) : c,
                fill: fill,
                tension: 0.3,
                borderWidth: 2,
                pointRadius: 3,
                pointHoverRadius: 5,
                pointBackgroundColor: c
            };
        });
        if (o.showLegend === undefined) o.showLegend = series.length > 1;
        return safeRender(canvasId, {
            type: 'line',
            data: { labels: o.labels || [], datasets: datasets },
            options: merge(baseOptions(o), o.overrides)
        });
    }

    function bar(canvasId, opts) {
        var o = opts || {};
        var series = o.series || [];
        if (!series.length) return null;
        var datasets = series.map(function (s, i) {
            var c = colourFor(s, i);
            if (s.type === 'line') {
                return {
                    type: 'line', label: s.name, data: (s.data || []).map(Number),
                    borderColor: c, backgroundColor: hexToRgba(c, 0.12),
                    fill: false, tension: 0.3, borderWidth: 2,
                    pointRadius: 3, pointBackgroundColor: c, order: 0
                };
            }
            return {
                label: s.name || ('Series ' + (i + 1)),
                data: (s.data || []).map(Number),
                backgroundColor: hexToRgba(c, 0.85),
                borderColor: c,
                borderWidth: 1,
                borderRadius: 4,
                order: 1
            };
        });
        if (o.showLegend === undefined) o.showLegend = series.length > 1;
        var options = merge(baseOptions(o), o.overrides);
        if (o.horizontal) options.indexAxis = 'y';
        if (o.stacked) { options.scales.x.stacked = true; options.scales.y.stacked = true; }
        return safeRender(canvasId, {
            type: 'bar',
            data: { labels: o.labels || [], datasets: datasets },
            options: options
        });
    }

    function doughnut(canvasId, opts) {
        var o = opts || {};
        var values = (o.values || []).map(Number);
        if (!values.length || values.every(function (v) { return !v; })) return null;
        var currency = !!o.currency;
        return safeRender(canvasId, {
            type: 'doughnut',
            data: {
                labels: o.labels || [],
                datasets: [{
                    data: values,
                    backgroundColor: values.map(function (_, i) { return PALETTE[i % PALETTE.length]; }),
                    borderColor: '#ffffff',
                    borderWidth: 2
                }]
            },
            options: merge({
                responsive: true,
                maintainAspectRatio: false,
                cutout: '62%',
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: { boxWidth: 12, padding: 12, color: BODY,
                                  font: { family: FONT, size: 11 } }
                    },
                    tooltip: {
                        backgroundColor: INK, padding: 10, cornerRadius: 6,
                        titleFont: { family: FONT, size: 12, weight: '700' },
                        bodyFont: { family: FONT, size: 12 },
                        callbacks: {
                            label: function (ctx) {
                                var v = ctx.parsed;
                                var txt = currency ? fmtMoney(v, o.ccy) : fmtNum(v);
                                return ctx.label + ': ' + txt;
                            }
                        }
                    }
                }
            }, o.overrides)
        });
    }

    function sparkline(canvasId, opts) {
        var o = opts || {};
        var data = (o.data || []).map(Number);
        if (!data.length) return null;
        var c = (o.tone && TONES[o.tone]) ? TONES[o.tone] : INK;
        return safeRender(canvasId, {
            type: 'line',
            data: {
                labels: data.map(function () { return ''; }),
                datasets: [{
                    data: data, borderColor: c,
                    backgroundColor: hexToRgba(c, 0.15),
                    fill: true, tension: 0.35, borderWidth: 1.5, pointRadius: 0
                }]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false }, tooltip: { enabled: false } },
                scales: { x: { display: false }, y: { display: false } },
                elements: { line: { borderJoinStyle: 'round' } }
            }
        });
    }

    window.WTCharts = {
        PALETTE: PALETTE,
        fmtNum: fmtNum,
        fmtMoney: fmtMoney,
        fmtPct: fmtPct,
        fmtCompact: fmtCompact,
        hexToRgba: hexToRgba,
        baseOptions: baseOptions,
        safeRender: safeRender,
        line: line,
        bar: bar,
        doughnut: doughnut,
        sparkline: sparkline
    };
})();
