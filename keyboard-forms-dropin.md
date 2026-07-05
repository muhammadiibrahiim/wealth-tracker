# Keyboard-driven forms + auto-opening searchable dropdowns

Drop this into any web project. You get:

- **Every `<select>` becomes a search-as-you-type widget** — the moment focus lands on it, the dropdown opens. Type to filter, ↑/↓ to highlight, Enter to pick. The native `<select>` stays in the DOM (hidden) so form submission works unchanged on the server.
- **"Stay until filled" guard** — Tab / Enter / Arrow keys are swallowed when the current field is `required` and empty. The cursor literally cannot move to the next field until the user picks/types a value.
- **Form-wide keyboard navigation** — Enter and ↓/→ advance to the next field. ↑/← go back. Horizontal arrows respect the caret position in text inputs (only advance when the caret is at the edge).
- **Auto-focus first empty required field** — when a page (or modal) loads.
- **Select-on-focus** for text/number inputs, so typing the first digit replaces the default "0" or "1" instead of appending.
- **Opt-out per field** — add `data-no-search` on a `<select>` to keep it native; add `required` on the underlying `<select>` to enable the stay-until-filled guard.

The whole thing is ~250 lines of vanilla JS + ~50 lines of CSS. No dependencies. No build step.

---

## 1) Drop in this CSS

```css
/* ─── Searchable select widget ─── */
.ss-wrap { position: relative; }

.ss-input {
  background: #fff; color: #23251d;
  border: 1px solid #d4d6cd; border-radius: 6px;
  font-size: 0.9375rem; line-height: 1.4;
  padding: 8px 12px; min-height: 40px; width: 100%;
  box-sizing: border-box;
}
.ss-input:focus {
  outline: none !important; border-color: #23251d !important;
  box-shadow: 0 0 0 3px rgba(35, 37, 29, 0.12) !important;
}

.ss-dropdown {
  position: absolute; top: 100%; left: 0; right: 0; z-index: 60;
  background: #fff; border: 1px solid #d4d6cd; border-top: none;
  border-radius: 0 0 6px 6px;
  max-height: 280px; overflow-y: auto;
  box-shadow: 0 8px 16px rgba(35,37,29,0.10);
}
.ss-option {
  padding: 8px 12px; cursor: pointer; font-size: 14px;
  border-bottom: 1px solid #eef0e8; color: #23251d;
}
.ss-option:last-child { border-bottom: none; }
.ss-option:hover, .ss-option.active { background: #fef7e6; }
.ss-empty { padding: 16px; text-align: center; color: #65675e; font-size: 13px; }

.ss-chip {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 12px;
  background: #fff; border: 1px solid #d4d6cd; border-radius: 6px;
  min-height: 40px; box-sizing: border-box; cursor: pointer;
}
.ss-chip:hover { border-color: #23251d; }
.ss-chip-label {
  flex: 1; color: #23251d; font-weight: 500; font-size: 14px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.ss-chip-clear {
  background: transparent; border: none; cursor: pointer;
  color: #65675e; padding: 2px 6px; border-radius: 4px; flex-shrink: 0;
}
.ss-chip-clear:hover { background: #f3f4f6; color: #cd4239; }

.ss-hidden {
  position: absolute; opacity: 0; pointer-events: none; height: 0; width: 0;
}
```

(Adjust the hex colours to match the host design system. The only structural
constraints are `.ss-wrap { position: relative }` and `.ss-dropdown { position:
absolute }` — everything else is cosmetic.)

---

## 2) Drop in this JS

```html
<script>
(function () {
  // ═════════════════════════════════════════════════════════════════
  // Public: window._enhanceSelects(scope?), window._focusFirstField(scope?)
  // Call them on page load and after any DOM swap (e.g. modal open, HTMX
  // swap, React subtree mount). They're idempotent — a select that's
  // already wrapped is skipped via `data-enhanced`.
  // ═════════════════════════════════════════════════════════════════

  function _escapeHtml(s) {
    return String(s).replace(/[&<>"]/g, c =>
      ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;' }[c]));
  }

  // List the focusable fields in a scope, in DOM order.
  // Includes the visible search input of each enhanced select.
  function _focusableFields(scope) {
    return Array.from(scope.querySelectorAll(
      'input:not([type=hidden]):not([disabled]):not([readonly]),' +
      'select:not([disabled]):not([data-enhanced]),' +
      'textarea:not([disabled]):not([readonly])'
    )).filter(el => el.offsetParent !== null);
  }

  // Auto-focus the first required-and-empty field; fall back to the first
  // focusable field. For enhanced selects, "required" lives on the hidden
  // <select> — we mirror it via data-ss-required on the visible input so the
  // check works there too.
  function _focusFirstField(scope) {
    var list = _focusableFields(scope);
    var first = list.find(el => (el.required || el.dataset.ssRequired === '1') && !el.value)
              || list[0];
    if (first) try {
      first.focus();
      if (first.select && first.tagName === 'INPUT') first.select();
    } catch (e) {}
  }
  window._focusFirstField = _focusFirstField;

  function _advanceField(el, dir) {
    var form = el.closest('form') || document.body;
    var list = _focusableFields(form);
    var i = list.indexOf(el);
    if (i === -1) return;
    var next = list[i + dir];
    if (next) next.focus();
  }

  // Select-on-focus for text-shaped inputs so typing replaces default values.
  document.addEventListener('focusin', function (e) {
    var t = e.target;
    if (!t || t.tagName !== 'INPUT') return;
    var type = (t.type || '').toLowerCase();
    if (!['text','number','email','password','search','tel','url'].includes(type)) return;
    setTimeout(() => { try { if (document.activeElement === t) t.select(); } catch(e) {} }, 0);
  });

  function _caretAtStart(input) {
    var t = (input.type || '').toLowerCase();
    if (!['text','email','password','search','tel','url'].includes(t)) return true;
    try { return input.selectionStart === 0 && input.selectionEnd === 0; } catch (e) { return true; }
  }
  function _caretAtEnd(input) {
    var t = (input.type || '').toLowerCase();
    if (!['text','email','password','search','tel','url'].includes(t)) return true;
    try { var n = input.value.length; return input.selectionStart === n && input.selectionEnd === n; } catch (e) { return true; }
  }

  // The "stay until filled" predicate.
  function _isRequiredEmpty(el) {
    if (!el) return false;
    if (el.dataset && el.dataset.ssRequired === '1') {
      var wrap = el.closest('.ss-wrap');
      var sel = wrap ? wrap.querySelector('select') : null;
      if (sel) return sel.required && !sel.value;
    }
    return el.required && !el.value;
  }

  // Form-wide keyboard handler. Textareas + buttons are left alone.
  document.addEventListener('keydown', function (e) {
    var t = e.target;
    if (!t || !t.tagName) return;
    var tag = t.tagName.toLowerCase();
    var type = (t.type || '').toLowerCase();
    if (tag === 'textarea' || tag === 'button') return;
    var key = e.key;

    // ── Stay-until-filled guard ────────────────────────────────────
    var navKeys = ['Enter', 'ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight', 'Tab'];
    if (navKeys.includes(key) && _isRequiredEmpty(t)) {
      e.preventDefault();
      return;
    }

    if (key === 'Enter') {
      var form = t.closest('form');
      if (form) {
        var list = _focusableFields(form);
        var i = list.indexOf(t);
        if (i !== -1 && i < list.length - 1) {
          e.preventDefault(); _advanceField(t, 1);
        }
      }
      return;
    }
    if (key === 'ArrowDown' || key === 'ArrowUp') {
      if (tag === 'select') return;          // let native selects open
      if (tag === 'input' && ['number','date','datetime-local','time'].includes(type)) return;
      e.preventDefault();
      _advanceField(t, key === 'ArrowDown' ? 1 : -1);
      return;
    }
    if (key === 'ArrowRight') {
      if (tag === 'input' && ['text','email','password','search','tel','url'].includes(type)) {
        if (!_caretAtEnd(t)) return;         // let caret move within text
      }
      e.preventDefault(); _advanceField(t, 1); return;
    }
    if (key === 'ArrowLeft') {
      if (tag === 'input' && ['text','email','password','search','tel','url'].includes(type)) {
        if (!_caretAtStart(t)) return;
      }
      e.preventDefault(); _advanceField(t, -1); return;
    }
  });

  // ═════════════════════════════════════════════════════════════════
  // Enhance every <select> into a search widget with chip + dropdown.
  // Native <select> stays in DOM (hidden) so form submit is unchanged.
  // Add data-no-search to a <select> to opt out (keep it native).
  // ═════════════════════════════════════════════════════════════════
  function _enhanceSelects(scope) {
    scope = scope || document;
    scope.querySelectorAll('select:not([data-enhanced])').forEach(function (sel) {
      sel.dataset.enhanced = '1';
      if (sel.hasAttribute('data-no-search')) return;
      var real = Array.from(sel.options).filter(o => o.value !== '');
      if (real.length === 0) return;
      _wrapSelect(sel);
    });
  }
  window._enhanceSelects = _enhanceSelects;

  function _wrapSelect(sel) {
    var placeholder = (sel.options[0] && sel.options[0].value === '')
                      ? sel.options[0].text : 'Search…';
    var wrap = document.createElement('div'); wrap.className = 'ss-wrap';
    var input = document.createElement('input');
    input.type = 'text'; input.className = 'ss-input';
    input.placeholder = placeholder; input.autocomplete = 'off';
    if (sel.required) {
      input.setAttribute('aria-required', 'true');
      input.dataset.ssRequired = '1';
    }
    var chip = document.createElement('div'); chip.className = 'ss-chip';
    chip.style.display = 'none';
    var dropdown = document.createElement('div'); dropdown.className = 'ss-dropdown';
    dropdown.style.display = 'none';

    sel.classList.add('ss-hidden'); sel.tabIndex = -1;
    sel.parentNode.insertBefore(wrap, sel);
    wrap.appendChild(input); wrap.appendChild(chip);
    wrap.appendChild(dropdown); wrap.appendChild(sel);

    var activeIdx = -1, visible = [];

    function readOptions() {
      return Array.from(sel.options)
        .map(o => ({ value: o.value, label: o.text }))
        .filter(o => o.value !== '');
    }
    function render(filter) {
      var q = (filter || '').trim().toLowerCase();
      visible = readOptions().filter(o => !q || o.label.toLowerCase().includes(q)).slice(0, 100);
      if (!visible.length) {
        dropdown.innerHTML = '<div class="ss-empty">No matches</div>';
      } else {
        dropdown.innerHTML = visible.map((o, i) =>
          '<div class="ss-option' + (i === activeIdx ? ' active' : '') + '" data-idx="' + i + '">' +
          _escapeHtml(o.label) + '</div>'
        ).join('');
        dropdown.querySelectorAll('.ss-option').forEach(el => {
          el.addEventListener('mousedown', e => {
            e.preventDefault();
            pick(parseInt(el.dataset.idx, 10));
          });
        });
      }
      dropdown.style.display = 'block';   // ← dropdown auto-opens here
    }
    function pick(idx) {
      if (idx < 0 || idx >= visible.length) return;
      var o = visible[idx];
      sel.value = o.value;
      sel.dispatchEvent(new Event('change', { bubbles: true }));
      showChip(o);
      // Move focus to the next field automatically after a pick.
      setTimeout(() => {
        var fields = _focusableFields(document)
          .concat(Array.from(document.querySelectorAll('.ss-input')));
        fields.sort((a, b) =>
          (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) ? -1 : 1);
        var i = fields.findIndex(f => wrap.contains(f));
        var next = i >= 0 ? fields[i + 1] : null;
        if (next) { next.focus(); if (next.select) next.select(); }
      }, 0);
    }
    function showChip(o) {
      input.style.display = 'none';
      dropdown.style.display = 'none';
      chip.style.display = 'flex';
      chip.innerHTML =
        '<span class="ss-chip-label">' + _escapeHtml(o.label) + '</span>' +
        '<button type="button" class="ss-chip-clear" tabindex="-1" title="Change">✕</button>';
      chip.querySelector('.ss-chip-clear').addEventListener('click', e => {
        e.stopPropagation(); clearChip();
      });
      chip.tabIndex = 0;
      chip.onclick = clearChip;
    }
    function clearChip() {
      sel.value = '';
      sel.dispatchEvent(new Event('change', { bubbles: true }));
      chip.style.display = 'none';
      input.style.display = '';
      input.value = '';
      input.focus();
      render('');
    }

    // ── Auto-open on focus ──────────────────────────────────────────
    input.addEventListener('focus', () => { activeIdx = -1; render(input.value); });
    input.addEventListener('input', () => { activeIdx = -1; render(input.value); });
    input.addEventListener('blur',  () => { setTimeout(() => dropdown.style.display = 'none', 120); });
    input.addEventListener('keydown', e => {
      if (e.key === 'ArrowDown') {
        e.preventDefault(); e.stopPropagation();
        activeIdx = Math.min(activeIdx + 1, visible.length - 1);
        render(input.value);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault(); e.stopPropagation();
        activeIdx = Math.max(activeIdx - 1, 0);
        render(input.value);
      } else if (e.key === 'Enter') {
        // Pick the highlighted option, or auto-pick the first visible match.
        var idx = activeIdx >= 0 ? activeIdx : (visible.length >= 1 ? 0 : -1);
        e.preventDefault(); e.stopPropagation();
        if (idx >= 0 && visible[idx]) pick(idx);
      } else if (e.key === 'Escape') {
        e.stopPropagation();
        dropdown.style.display = 'none';
      } else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        e.stopPropagation();                // let caret move inside the typed text
      }
    });

    // Pre-populate from existing value (edit mode).
    var pre = readOptions().find(o => o.value === sel.value);
    if (pre) showChip(pre);

    // Keep chip in sync if the underlying select is mutated externally.
    sel.addEventListener('change', () => {
      if (sel.value === '') {
        chip.style.display = 'none';
        input.style.display = '';
      } else {
        var m = readOptions().find(o => o.value === sel.value);
        if (m) showChip(m);
      }
    });
  }

  // ═════════════════════════════════════════════════════════════════
  // Wire-up on load + HTMX swap (drop the htmx handler if you don't use HTMX).
  // ═════════════════════════════════════════════════════════════════
  window.addEventListener('load', function () {
    _enhanceSelects(document);
    var firstForm = document.querySelector('main form') || document.querySelector('form');
    if (firstForm) _focusFirstField(firstForm);
  });

  // OPTIONAL — only if the host project uses HTMX.
  document.addEventListener('htmx:afterSwap', function (e) {
    if (e.detail.target && e.detail.target.id === 'modal-container') {
      setTimeout(function () {
        _enhanceSelects(e.detail.target);
        _focusFirstField(e.detail.target);
      }, 50);
    } else if (e.detail.target) {
      _enhanceSelects(e.detail.target);
    }
  });
})();
</script>
```

---

## 3) How to use it from your form markup

```html
<form>
  <!-- A required select — gets enhanced, dropdown opens on focus,
       Tab/Enter/arrows are blocked until the user picks something. -->
  <select name="vendor_id" required>
    <option value="">— Select vendor —</option>
    <option value="1">Ahmed poly bags</option>
    <option value="2">Capital A/C</option>
    <option value="3">Ibrahim (CEO)</option>
    <option value="4">Sansa Flyers</option>
  </select>

  <!-- A required text input — same guard applies (can't Tab away until filled). -->
  <input name="description" required placeholder="e.g. June rent">

  <!-- Optional: opt out of the search widget for this one select. -->
  <select name="quick_pick" data-no-search>
    <option value="">— pick —</option>
    <option value="a">Yes</option>
    <option value="b">No</option>
  </select>

  <button type="submit">Save</button>
</form>
```

That's it. No init code per form. The `load` handler enhances every `<select>` in the page once, and (if HTMX is loaded) the `htmx:afterSwap` handler enhances any newly-swapped-in markup.

---

## 4) Mental model — what the user actually experiences

1. Page loads → first empty `required` field gets focus automatically.
2. If it's a `<select>` → its search input is focused and the dropdown is already open.
3. User types → list filters live. Arrow keys highlight. Enter picks.
4. After picking → the underlying `<select>` is set, a tidy chip replaces the input ("Ahmed poly bags ✕"), and **focus jumps to the next field**.
5. If the next field is required and empty → Tab / Enter / Arrows are swallowed until it's filled.
6. Horizontal arrows in text inputs move the caret normally; they only advance fields when the caret is at the edge.
7. Cmd/Ctrl-click and mouse interactions work as expected — the keyboard layer just augments them.

---

## 5) Notes for porting to another stack

- **No HTMX?** Drop the `htmx:afterSwap` listener. If you use React/Vue/Svelte, call `window._enhanceSelects(rootEl)` after the relevant subtree mounts, and `window._focusFirstField(rootEl)` after the modal opens. Both functions are idempotent.
- **No `<form>` wrapper?** `_advanceField` falls back to `document.body` for the focusable scope, so it still works on free-floating forms.
- **Server-side validation still wins.** The "stay until filled" guard is UX, not a security control — `required` on the hidden `<select>` ensures native form submission still rejects empty values.
- **Accessibility.** The widget input gets `aria-required="true"` when the underlying select is required. The chip's clear button is `tabindex="-1"` so it doesn't pollute the tab order; clicking it (or the chip) clears the value and re-opens the search.
- **Keyboard-only users** can clear a chip by pressing Tab to it (the chip itself is `tabindex="0"`) and hitting Enter — that re-opens the search input.
