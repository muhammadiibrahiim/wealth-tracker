/* Wealth Tracker — report toolkit.
   Progressive enhancement for any <table class="wt-table">. Opt in per table
   with data attributes; nothing here runs unless a table asks for it.

     <table class="wt-table" id="tbl-x" data-sortable>   → click a <th> to sort
     <input data-table-search="tbl-x">                   → filter rows
     <button data-table-export="tbl-x">                  → download visible rows as CSV
     <span data-table-count="tbl-x">                     → "showing N of M"
     <div data-date-presets data-start="date_from" data-end="date_to">
     <button data-print>

   Per-column opt-outs:  <th data-no-sort>   <th data-no-export>

   Re-initialises on htmx:afterSwap and is idempotent (data-wt-ready), so a
   swapped-in table keeps its toolkit and never double-binds. */
(function () {
    'use strict';

    var HIDDEN = 'wt-row-hidden';

    /* ============================================================
       Cell value extraction — the piece everything else depends on.
       Returns a Number, a lowercase String, or null (null always sorts last).
       ============================================================ */
    function parseCell(td) {
        if (!td) return null;
        if (td.dataset && td.dataset.sortValue !== undefined) {
            var dv = parseFloat(td.dataset.sortValue);
            return isNaN(dv) ? String(td.dataset.sortValue).toLowerCase() : dv;
        }
        var raw = (td.textContent || '').trim();
        if (!raw || raw === '—' || raw === '-' || raw === '—') return null;

        /* Parenthesised negatives: (1,200) → -1200 */
        var negParen = /^\(.*\)$/.test(raw);
        var s = raw.replace(/^\(|\)$/g, '');

        /* Strip a leading currency word/symbol, thousands separators,
           a trailing %, and a trailing unit (d / days / x / mos). */
        s = s.replace(/^[^\d\-+.]*/, '')          // leading Rs, $, etc.
             .replace(/,/g, '')
             .replace(/%$/, '')
             .replace(/\s*(days?|d|x|mos?)$/i, '')
             .trim();

        if (s !== '' && !isNaN(s) && /^[-+]?[\d.]+$/.test(s)) {
            var n = parseFloat(s);
            return negParen ? -Math.abs(n) : n;
        }

        /* Dates the app renders, e.g. "05 Jul 2026" or "2026-07-05". */
        var t = Date.parse(raw);
        if (!isNaN(t) && /\d{4}/.test(raw)) return t;

        return raw.toLowerCase();
    }

    function compare(a, b) {
        if (a === null && b === null) return 0;
        if (a === null) return 1;      /* nulls always last... */
        if (b === null) return -1;     /* ...in both directions */
        if (typeof a === 'number' && typeof b === 'number') return a - b;
        return String(a).localeCompare(String(b));
    }

    /* Data rows only — totals and group headers never take part in a sort. */
    function dataRows(tbody) {
        return Array.prototype.filter.call(tbody.rows, function (tr) {
            return !tr.classList.contains('wt-total') && !tr.classList.contains('wt-group');
        });
    }
    function fixedRows(tbody) {
        return Array.prototype.filter.call(tbody.rows, function (tr) {
            return tr.classList.contains('wt-total') || tr.classList.contains('wt-group');
        });
    }

    /* ============================================================
       Sorting
       ============================================================ */
    function wireSort(table) {
        if (table.dataset.wtReady === '1') return;
        table.dataset.wtReady = '1';

        var thead = table.tHead;
        var tbody = table.tBodies[0];
        if (!thead || !tbody) return;

        /* Stamp the server's order so the third click can restore it. */
        Array.prototype.forEach.call(tbody.rows, function (tr, i) {
            if (tr.dataset.wtIdx === undefined) tr.dataset.wtIdx = i;
        });

        var headRow = thead.rows[thead.rows.length - 1];
        if (!headRow) return;

        Array.prototype.forEach.call(headRow.cells, function (th, colIdx) {
            if (th.dataset.noSort !== undefined) return;
            th.classList.add('wt-th-sort');
            th.setAttribute('role', 'button');
            th.setAttribute('tabindex', '0');
            th.setAttribute('aria-sort', 'none');
            if (!th.querySelector('.wt-sort-ind')) {
                var ind = document.createElement('span');
                ind.className = 'wt-sort-ind';
                th.appendChild(ind);
            }
            function activate() { doSort(table, headRow, th, colIdx); }
            th.addEventListener('click', activate);
            th.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
                    e.preventDefault(); activate();
                }
            });
        });
    }

    function doSort(table, headRow, th, colIdx) {
        var tbody = table.tBodies[0];
        var current = th.getAttribute('aria-sort');
        var next = current === 'none' ? 'ascending'
                 : current === 'ascending' ? 'descending' : 'none';

        /* Only one active column at a time. */
        Array.prototype.forEach.call(headRow.cells, function (c) {
            if (c.dataset.noSort === undefined) {
                c.setAttribute('aria-sort', 'none');
                var i = c.querySelector('.wt-sort-ind');
                if (i) i.textContent = '';
            }
        });
        th.setAttribute('aria-sort', next);
        var ind = th.querySelector('.wt-sort-ind');
        if (ind) ind.textContent = next === 'ascending' ? '▲' : next === 'descending' ? '▼' : '';

        var rows = dataRows(tbody);
        var fixed = fixedRows(tbody);

        if (next === 'none') {
            rows.sort(function (a, b) {
                return (parseInt(a.dataset.wtIdx, 10) || 0) - (parseInt(b.dataset.wtIdx, 10) || 0);
            });
        } else {
            var dir = next === 'ascending' ? 1 : -1;
            rows.sort(function (a, b) {
                return dir * compare(parseCell(a.cells[colIdx]), parseCell(b.cells[colIdx]));
            });
        }

        /* Re-append: data first, then totals/groups, so a totals row can never
           end up in the middle of the data. */
        rows.forEach(function (r) { tbody.appendChild(r); });
        fixed.forEach(function (r) { tbody.appendChild(r); });
    }

    /* ============================================================
       Search / filter
       ============================================================ */
    function wireSearch(input) {
        if (input.dataset.wtReady === '1') return;
        input.dataset.wtReady = '1';
        var timer = null;
        input.addEventListener('input', function () {
            clearTimeout(timer);
            timer = setTimeout(function () { applyFilter(input.dataset.tableSearch); }, 120);
        });
    }

    function applyFilter(tableId) {
        var table = document.getElementById(tableId);
        if (!table) return;
        var input = document.querySelector('[data-table-search="' + tableId + '"]');
        var q = input ? (input.value || '').trim().toLowerCase() : '';
        var tbody = table.tBodies[0];
        if (!tbody) return;

        var shown = 0, total = 0;
        Array.prototype.forEach.call(tbody.rows, function (tr) {
            if (tr.classList.contains('wt-total')) { tr.classList.remove(HIDDEN); return; }
            if (tr.classList.contains('wt-group')) return;   /* handled below */
            total++;
            var hit = !q || (tr.textContent || '').toLowerCase().indexOf(q) !== -1;
            tr.classList.toggle(HIDDEN, !hit);
            if (hit) shown++;
        });

        /* A group header survives only if something under it survived. */
        var group = null, groupHasVisible = false;
        Array.prototype.forEach.call(tbody.rows, function (tr) {
            if (tr.classList.contains('wt-group')) {
                if (group) group.classList.toggle(HIDDEN, !groupHasVisible);
                group = tr; groupHasVisible = false;
            } else if (!tr.classList.contains('wt-total') && !tr.classList.contains(HIDDEN)) {
                groupHasVisible = true;
            }
        });
        if (group) group.classList.toggle(HIDDEN, !groupHasVisible);

        updateCount(tableId, shown, total, !!q);
    }

    function updateCount(tableId, shown, total, filtered) {
        var el = document.querySelector('[data-table-count="' + tableId + '"]');
        if (!el) return;
        if (!filtered) {
            el.textContent = total ? (total + ' row' + (total === 1 ? '' : 's')) : '';
        } else {
            /* Totals are NOT recomputed client-side — say so rather than
               showing a total that silently covers hidden rows. */
            el.textContent = 'showing ' + shown + ' of ' + total +
                ' · totals cover all ' + total;
        }
    }

    /* ============================================================
       CSV export — of the CURRENTLY VISIBLE rows, in screen order
       ============================================================ */
    function csvEscape(v) {
        var s = String(v === null || v === undefined ? '' : v);
        return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    }

    function cellForExport(cell) {
        if (cell.dataset && cell.dataset.sortValue !== undefined) return cell.dataset.sortValue;
        var v = parseCell(cell);
        if (typeof v === 'number' && cell.classList.contains('num')) return v;
        return (cell.textContent || '').trim().replace(/\s+/g, ' ');
    }

    function toCSV(table) {
        var out = [];
        var skip = {};
        if (table.tHead) {
            var hr = table.tHead.rows[table.tHead.rows.length - 1];
            var head = [];
            Array.prototype.forEach.call(hr.cells, function (th, i) {
                if (th.dataset.noExport !== undefined) { skip[i] = true; return; }
                head.push(csvEscape((th.textContent || '').replace(/[▲▼]/g, '').trim()));
            });
            out.push(head.join(','));
        }
        Array.prototype.forEach.call(table.tBodies, function (tbody) {
            Array.prototype.forEach.call(tbody.rows, function (tr) {
                if (tr.classList.contains(HIDDEN)) return;
                var row = [];
                Array.prototype.forEach.call(tr.cells, function (td, i) {
                    if (skip[i]) return;
                    row.push(csvEscape(cellForExport(td)));
                });
                out.push(row.join(','));
            });
        });
        return out.join('\r\n');
    }

    function slug(s) {
        return String(s || 'report').toLowerCase()
            .replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60);
    }

    function wireExport(button) {
        if (button.dataset.wtReady === '1') return;
        button.dataset.wtReady = '1';
        button.addEventListener('click', function () {
            var table = document.getElementById(button.dataset.tableExport);
            if (!table) return;
            var csv = toCSV(table);
            var d = table.dataset.exportDate || new Date().toISOString().slice(0, 10);
            var name = slug(document.title.split('·')[0]) + '-' + d + '.csv';
            var blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' });
            var url = URL.createObjectURL(blob);
            var a = document.createElement('a');
            a.href = url; a.download = name;
            document.body.appendChild(a); a.click(); document.body.removeChild(a);
            setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
        });
    }

    /* ============================================================
       Date presets
       ============================================================ */
    function iso(d) {
        return d.getFullYear() + '-' +
            String(d.getMonth() + 1).padStart(2, '0') + '-' +
            String(d.getDate()).padStart(2, '0');
    }

    function rangePresets() {
        var now = new Date();
        var y = now.getFullYear(), m = now.getMonth();
        var q = Math.floor(m / 3);
        return [
            { label: 'This month',   start: new Date(y, m, 1),          end: now },
            { label: 'Last month',   start: new Date(y, m - 1, 1),      end: new Date(y, m, 0) },
            { label: 'Last 30 days', start: new Date(now.getTime() - 29 * 864e5), end: now },
            { label: 'This quarter', start: new Date(y, q * 3, 1),      end: now },
            { label: 'Year to date', start: new Date(y, 0, 1),          end: now },
            { label: 'Last year',    start: new Date(y - 1, 0, 1),      end: new Date(y - 1, 11, 31) },
            { label: 'All time',     start: null,                       end: null }
        ];
    }

    function singlePresets() {
        var now = new Date();
        var y = now.getFullYear(), m = now.getMonth();
        var q = Math.floor(m / 3);
        return [
            { label: 'Today',              start: now },
            { label: 'End of last month',  start: new Date(y, m, 0) },
            { label: 'End of last quarter',start: new Date(y, q * 3, 0) },
            { label: 'End of last year',   start: new Date(y - 1, 11, 31) }
        ];
    }

    function wirePresets(box) {
        if (box.dataset.wtReady === '1') return;
        box.dataset.wtReady = '1';

        var single = box.dataset.mode === 'single';
        var startName = box.dataset.start;
        var endName = box.dataset.end;
        var form = box.closest('form');
        if (!form || !startName) return;

        var startEl = form.querySelector('[name="' + startName + '"]');
        var endEl = endName ? form.querySelector('[name="' + endName + '"]') : null;

        var list = single ? singlePresets() : rangePresets();
        list.forEach(function (p) {
            var b = document.createElement('button');
            b.type = 'button';
            b.className = 'wt-preset';
            b.textContent = p.label;

            var sVal = p.start ? iso(p.start) : '';
            var eVal = (!single && p.end) ? iso(p.end) : '';

            /* Highlight whichever preset matches the current values. */
            var curS = startEl ? (startEl.value || '') : '';
            var curE = endEl ? (endEl.value || '') : '';
            if (curS === sVal && (single || curE === eVal)) b.classList.add('wt-preset--active');

            b.addEventListener('click', function () {
                if (startEl) startEl.value = sVal;
                if (endEl) endEl.value = eVal;
                if (typeof form.requestSubmit === 'function') form.requestSubmit();
                else form.submit();
            });
            box.appendChild(b);
        });
    }

    /* ============================================================
       Print
       ============================================================ */
    function wirePrint(button) {
        if (button.dataset.wtReady === '1') return;
        button.dataset.wtReady = '1';
        button.addEventListener('click', function () { window.print(); });
    }

    /* ============================================================
       Init — idempotent, safe to call on any scope
       ============================================================ */
    function init(scope) {
        scope = scope || document;
        if (!scope.querySelectorAll) return;
        try {
            Array.prototype.forEach.call(
                scope.querySelectorAll('table.wt-table[data-sortable]'), wireSort);
            Array.prototype.forEach.call(
                scope.querySelectorAll('[data-table-search]'), wireSearch);
            Array.prototype.forEach.call(
                scope.querySelectorAll('[data-table-export]'), wireExport);
            Array.prototype.forEach.call(
                scope.querySelectorAll('[data-date-presets]'), wirePresets);
            Array.prototype.forEach.call(
                scope.querySelectorAll('[data-print]'), wirePrint);
            /* Seed the row counts. */
            Array.prototype.forEach.call(
                scope.querySelectorAll('[data-table-count]'), function (el) {
                    applyFilter(el.dataset.tableCount);
                });
        } catch (e) {
            console.error('[WTReport] init failed', e);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { init(document); });
    } else {
        init(document);
    }
    document.body && document.body.addEventListener('htmx:afterSwap', function (evt) {
        init(evt.detail && evt.detail.target ? evt.detail.target : document);
    });
    document.addEventListener('htmx:afterSwap', function (evt) {
        init(evt.detail && evt.detail.target ? evt.detail.target : document);
    });

    window.WTReport = {
        init: init,
        parseCell: parseCell,
        toCSV: toCSV,
        applyFilter: applyFilter
    };
})();
