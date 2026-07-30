/* Wealth Tracker — global search palette + keyboard shortcuts.
   Ported from the Trading Software command palette.

     /              open search
     ?              this help
     G then a code  jump straight to a page
     ↑ ↓ ↵ Esc      navigate / open / close

   Markup lives in templates/base.html; styles in wealth-design.css §13.
   Registry comes from /api/search/pages, records from /api/search.

   The global keydown handler deliberately mirrors base.html's "typing in a
   field" test so the two never fight: base.html owns Enter/Arrows/Tab for
   form navigation, this owns / ? g and only outside fields. */
(function () {
    'use strict';

    var overlay     = document.getElementById('wtPaletteOverlay');
    var input       = document.getElementById('wtPaletteInput');
    var resultsBox  = document.getElementById('wtPaletteResults');
    var helpOverlay = document.getElementById('wtHelpOverlay');
    var goToast     = document.getElementById('wtGoToast');

    /* Complete no-op on a page without the markup — never a console error. */
    if (!overlay || !input || !resultsBox) return;

    var PAGES = [], CODES = {}, CODE_LIST = [];
    var items = [], active = 0, searchTimer = null, booted = false;

    /* ============================================================
       Registry — fetched lazily on first use, not on every page load
       ============================================================ */
    function ensureRegistry(cb) {
        if (booted) { cb(); return; }
        fetch('/api/search/pages', { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : { pages: [], codes: {} }; })
            .then(function (d) {
                PAGES = d.pages || {};
                if (!Array.isArray(PAGES)) PAGES = [];
                CODES = d.codes || {};
                CODE_LIST = Object.keys(CODES);
                booted = true; cb();
            })
            .catch(function () { booted = true; cb(); });   /* degrade, never throw */
    }

    /* ============================================================
       Render
       ============================================================ */
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }

    function render(list) {
        items = list;
        active = 0;
        if (!list.length) {
            resultsBox.innerHTML = '<div class="wt-palette-empty">No matches found</div>';
            return;
        }
        resultsBox.innerHTML = list.map(function (r, i) {
            return '<a class="wt-palette-item' + (i === 0 ? ' active' : '') + '" href="' +
                esc(r.url) + '" data-i="' + i + '">' +
                '<span class="wt-palette-type">' + esc(r.type) + '</span>' +
                '<span class="wt-palette-main">' +
                '<span class="wt-palette-title">' + esc(r.title) + '</span>' +
                (r.subtitle ? '<span class="wt-palette-sub">' + esc(r.subtitle) + '</span>' : '') +
                '</span>' +
                (r.code ? '<span class="wt-palette-code">G&nbsp;' + esc(r.code) + '</span>' : '') +
                '</a>';
        }).join('');
    }

    function highlight() {
        var els = resultsBox.querySelectorAll('.wt-palette-item');
        Array.prototype.forEach.call(els, function (el, i) {
            el.classList.toggle('active', i === active);
            if (i === active && el.scrollIntoView) el.scrollIntoView({ block: 'nearest' });
        });
    }

    /* ============================================================
       Search — instant page hits, then records from the server
       ============================================================ */
    function dedupe(list) {
        var seen = {}, out = [];
        list.forEach(function (r) {
            if (!r || !r.url) return;
            var k = r.type + '|' + r.url;
            if (seen[k]) return;
            seen[k] = 1; out.push(r);
        });
        return out;
    }

    function doSearch(q) {
        var term = (q || '').trim().toLowerCase();
        var pageHits = PAGES.filter(function (p) {
            if (!term) return true;
            return (p.title || '').toLowerCase().indexOf(term) !== -1 ||
                   (p.keys || '').indexOf(term) !== -1;
        });
        if (!term) { render(pageHits.slice(0, 12)); return; }

        render(dedupe(pageHits));                 /* instant, no network wait */

        fetch('/api/search?q=' + encodeURIComponent(term), { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : { results: [] }; })
            .then(function (d) { render(dedupe(pageHits.concat(d.results || []))); })
            .catch(function () { /* keep the page hits already on screen */ });
    }

    /* ============================================================
       Open / close
       ============================================================ */
    function openPalette() {
        ensureRegistry(function () {
            overlay.classList.add('open');
            input.value = '';
            doSearch('');
            setTimeout(function () { input.focus(); }, 30);
        });
    }
    function closePalette() { overlay.classList.remove('open'); }

    input.addEventListener('input', function () {
        clearTimeout(searchTimer);
        var q = input.value;
        searchTimer = setTimeout(function () { doSearch(q); }, 140);
    });

    input.addEventListener('keydown', function (e) {
        if (e.key === 'ArrowDown') {
            e.preventDefault(); active = Math.min(active + 1, items.length - 1); highlight();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault(); active = Math.max(active - 1, 0); highlight();
        } else if (e.key === 'Enter') {
            e.preventDefault();
            if (items[active]) window.location.href = items[active].url;
        } else if (e.key === 'Escape') {
            closePalette();
        }
    });

    resultsBox.addEventListener('mousemove', function (e) {
        var it = e.target.closest ? e.target.closest('.wt-palette-item') : null;
        if (it) { active = parseInt(it.dataset.i, 10) || 0; highlight(); }
    });

    overlay.addEventListener('click', function (e) {
        if (e.target === overlay) closePalette();
    });

    var openBtn = document.getElementById('wtOpenPalette');
    if (openBtn) openBtn.addEventListener('click', openPalette);

    /* ============================================================
       Help modal — read-only list of go-to codes, grouped by module
       ============================================================ */
    function renderGotoCodes() {
        var box = document.getElementById('wtGotoCodes');
        if (!box) return;
        var groups = {}, order = [];
        PAGES.forEach(function (p) {
            if (!p.code) return;
            var sec = p.subtitle || 'Other';
            if (!groups[sec]) { groups[sec] = []; order.push(sec); }
            groups[sec].push(p);
        });
        var html = '';
        order.forEach(function (sec) {
            html += '<div class="wt-section-title" style="margin-top:14px;">' + esc(sec) + '</div>' +
                '<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px 18px;">';
            groups[sec].forEach(function (p) {
                html += '<div style="display:flex;align-items:center;gap:8px;min-width:0;">' +
                    '<span class="wt-palette-code" style="margin-left:0;">' + esc(p.code) + '</span>' +
                    '<span class="wt-meta" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' +
                    esc(p.title) + '</span></div>';
            });
            html += '</div>';
        });
        box.innerHTML = html;
    }

    function openHelp() {
        if (!helpOverlay) return;
        ensureRegistry(function () {
            renderGotoCodes();
            helpOverlay.classList.add('open');
        });
    }
    function closeHelp() { if (helpOverlay) helpOverlay.classList.remove('open'); }

    var helpBtn = document.getElementById('wtOpenHelp');
    if (helpBtn) helpBtn.addEventListener('click', openHelp);
    var helpClose = document.getElementById('wtHelpClose');
    if (helpClose) helpClose.addEventListener('click', closeHelp);
    if (helpOverlay) helpOverlay.addEventListener('click', function (e) {
        if (e.target === helpOverlay) closeHelp();
    });

    /* ============================================================
       Go-to toast
       ============================================================ */
    var toastTimer = null;
    function showGoToast(msg, ms) {
        if (!goToast) return;
        goToast.textContent = msg;
        goToast.classList.add('show');
        if (toastTimer) clearTimeout(toastTimer);
        toastTimer = setTimeout(function () { goToast.classList.remove('show'); }, ms || 1400);
    }

    /* ============================================================
       Global keydown — order of checks matters, see the file header
       ============================================================ */
    var gMode = false, gBuf = '', gTimer = null;

    function gReset() {
        gMode = false; gBuf = '';
        if (gTimer) { clearTimeout(gTimer); gTimer = null; }
    }
    function gArm() {
        if (gTimer) clearTimeout(gTimer);
        gTimer = setTimeout(function () {
            var u = CODES[gBuf];
            gReset();
            if (u) window.location.href = u;
        }, 1300);
    }

    document.addEventListener('keydown', function (e) {
        /* (a) never intercept a system shortcut */
        if (e.ctrlKey || e.metaKey || e.altKey) { gReset(); return; }

        /* (b) Escape closes whatever is open */
        if (e.key === 'Escape') {
            if (overlay.classList.contains('open')) closePalette();
            if (helpOverlay && helpOverlay.classList.contains('open')) closeHelp();
            gReset();
            return;
        }

        /* (c) same "in a field" test base.html uses */
        var t = e.target;
        var inField = t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' ||
                            t.tagName === 'SELECT' || t.isContentEditable);

        /* (d) go-mode buffer — runs before the inField guard so a code can
               still be typed if focus lands oddly */
        if (gMode) {
            if (!/^[a-zA-Z0-9]$/.test(e.key)) { gReset(); return; }
            e.preventDefault();
            gBuf += e.key.toUpperCase();
            var exact = CODES[gBuf];
            var longer = CODE_LIST.some(function (c) {
                return c.length > gBuf.length && c.slice(0, gBuf.length) === gBuf;
            });
            if (exact && !longer) { var u = exact; gReset(); window.location.href = u; return; }
            var anyPrefix = exact || longer || CODE_LIST.some(function (c) {
                return c.slice(0, gBuf.length) === gBuf;
            });
            if (!anyPrefix) { gReset(); showGoToast('No page for that code'); return; }
            showGoToast('Go to… ' + gBuf, 1300);
            gArm();
            return;
        }

        /* (e) everything below only fires outside a field */
        if (inField) return;

        if (e.key === '/') { e.preventDefault(); openPalette(); return; }
        if (e.key === '?') { e.preventDefault(); openHelp(); return; }
        if (e.key.toLowerCase() === 'g') {
            e.preventDefault();
            gMode = true; gBuf = '';
            ensureRegistry(function () {});
            showGoToast('Go to… type a page code', 1300);
            gArm();
            return;
        }
    });
})();
