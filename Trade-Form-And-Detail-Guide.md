# Trade — User Guide

How the **New Trade** form and the **Trade Detail** page work, end-to-end —
from the moment you click `+ New Trade` to the moment the trade is fully
paid and closed.

---

## Part 1 — The New Trade form

### Opening the form

Click **`+ New Trade`** from the Trade Dashboard (top-right) or the Trades
list. A centered modal slides in over the page. The cursor auto-jumps to
the first empty required field (Vendor) and opens its dropdown — so you
can start typing immediately, no clicking needed.

### Header fields

| Field | What it is | Behaviour |
|---|---|---|
| **Vendor** *(required)* | The supplier you're buying from. Searchable dropdown — type to filter. | When you pick a vendor, the **Vendor Terms** field below auto-fills with that vendor's default payment terms. |
| **Purchaser (Customer)** *(required)* | The buyer you're selling to. Same searchable dropdown UX. | When picked, **Customer Terms** auto-fills with the customer's default. |
| **Trade Date** *(required)* | The date this trade was struck. Defaults to today. | This date becomes the "issued on" date for invoices, the start point for due-date calculations, and the report-period anchor. |
| **Customer Terms (days)** *(required)* | How many days after delivery the customer has to pay. | Used to compute the per-delivery invoice due date. |
| **Vendor Terms (days)** *(required)* | How many days after delivery we have to pay the vendor. | Drives the *Vendor Due Date* badge on the trade detail. |

The two **Terms** fields can be overridden manually after auto-fill — useful
when this particular deal has off-standard terms.

### Line Items

A trade has **one or more line items**. Each line represents one distinct
product / spec combination at one price.

For each line:

| Field | What it does |
|---|---|
| **From Catalog** | Pick a pre-saved item (e.g. "Flyer", "Box"). When picked, the *Item Name, Unit, Default Cost, Default Price* and **all spec labels** for that item auto-populate. |
| **Item Name** *(required)* | Free-text name. Overrides whatever the catalog says — useful for one-off items. |
| **Qty** | The order quantity. Decimals are allowed (e.g. 1500.5). |
| **Unit** | "pcs", "kg", "sheets", whatever you measure in. |
| **Unit Cost** | What you pay the vendor per unit. |
| **Unit Price** | What you charge the customer per unit. |
| **Line Notes** | Free text — e.g. "rush job, ship Sat AM". |
| **Specifications** | Label / Value pairs, one per row. Add as many as you need with **+ add spec**. Examples: `Size: 14×14`, `Micron: 110`, `Print: 2-colour double-side`. |

Click **`+ Add line`** at the top of the section to add another line item.
Click **Remove line** in a line's footer to delete it before submitting.

The grid is responsive: on a wide screen each line shows in one row;
on narrower screens it stacks.

### Keyboard navigation

Every form in the app respects the same pattern:

1. **Auto-focus** lands on the first required field that's still empty.
2. **Tab / Enter / ↓ / →** advance to the next field.
3. **Shift-Tab / ↑ / ←** go back.
4. **Required + empty** fields *trap* the cursor — Tab/Enter/Arrows do
   nothing until you give the field a value. (Horizontal arrows still
   move the caret inside text inputs as long as it hasn't hit the edge.)
5. Searchable dropdowns **auto-open on focus**: type to filter,
   ↑/↓ to highlight, Enter to pick. After picking, focus jumps to the
   next field automatically.

This means you can complete the entire form without touching the mouse.

### Submitting

Click **Create Trade**. The trade is created with status **OPEN** — no
journal entries are posted yet. Goods haven't moved; this is just the
agreement. The modal closes and you're redirected to the **Trade Detail**
page for the new trade.

### What happens on the server

- A new trade reference is allocated (TRD-0001, TRD-0002, …).
- The customer / vendor due dates are computed (trade date + terms).
- Each line's `ordered_quantity` is captured separately from `quantity`
  so over- / under-delivery can be tracked later without losing the
  original commitment.
- All specifications are saved with their label-value pairs.

No money has moved yet. Nothing hits the ledger until you mark a
delivery — partial or complete.

---

## Part 2 — The Trade Detail page

This is the operational cockpit for one trade. Everything that happens
to the deal — deliveries, costs, payments, documents — lives here.

The page is laid out top-to-bottom in roughly the order things happen
in a trade's life. Let's walk through it.

### Top action row

**Left side:**
- The trade reference, big and bold (e.g. `TRD-0003`).
- A status pill next to it: **Open** · **Delivered** · **Partially Paid** ·
  **Paid** · **Closed** · **Cancelled**. Colour-coded.
- The trade date as a subtitle.

**Right side — action buttons (visibility depends on status):**

| Button | When it appears | What it does |
|---|---|---|
| **+ Receive Partial** | Open or Delivered, until fully delivered | Opens the partial-receive modal — record qty received for one or more lines on one date. |
| **Mark Complete** | Open trades | Final delivery confirmation. Posts the SAL / PUR / closing entries. |
| **+ Record Cost** | Any active status | Add a one-off trade cost (e.g. broker commission, demurrage). |
| **Record Customer Payment** | When customer outstanding > 0 | Log a cash inflow from the customer. |
| **Close Trade** | When fully paid | Mark the trade closed — final state, no more changes. |
| **Cancel** | Any active status | Reverse all linked journals and set status to Cancelled. |
| **Delete** | Always | Permanently remove the trade and every journal entry tied to it. *Cannot be undone* — use Cancel instead if you might need an audit trail. |

### Header cards

A 4-column strip showing the deal's parties and timing at a glance:

1. **Vendor (we buy)** — name + phone number if recorded.
2. **Purchaser (we sell)** — same.
3. **Customer Terms** — number of days + the computed due date.
   If the due date is in the past and customer outstanding > 0, it goes
   orange/bold.
4. **Vendor Terms** — same shape but for our payable to the vendor.

### Totals strip

Three big-number cards:
- **Total Cost** — sum of (qty × unit_cost) across all lines
- **Total Sale** — sum of (qty × unit_price)
- **Gross Profit** — sale minus cost. Green border if positive, orange if
  negative — visible from across the room.

### Line Items table

Each row is one line of the trade:

| Column | What it shows |
|---|---|
| **Item** | Item name, plus any line notes underneath |
| **Specs** | All saved label-value pairs (e.g. *Size: 14×14, Print: 2-colour*) |
| **Qty** | Final qty + unit. If the *ordered_quantity* differs from the *quantity* (because actual delivery came in over/short), a small delta is shown underneath: e.g. *ordered 5000 (+200)* in green, or *(-500)* in orange. |
| **Unit Cost** | What we pay per unit |
| **Unit Price** | What we charge per unit |
| **Line Cost** | qty × unit_cost |
| **Line Sale** | qty × unit_price |
| **Actions** | **Remove** link (when trade is still editable) |

### Documents

Every trade automatically exposes a fixed set of customer- and
vendor-facing PDFs — derived from the live trade data, generated on
demand. No upload, no manual creation. Each row has an **Open PDF**
button that opens the doc in a new tab.

| Doc | Audience | What it contains |
|---|---|---|
| 🧾 **Invoice** | Customer | Customer-facing bill. Subtotal, less cash received, less customer-paid costs, balance due. |
| 📨 **Order Confirmation** | Customer | Confirms the order back to the customer. **Always shows the originally-ordered qty (not the final delivered qty)** and includes a ±10–15 % quantity-tolerance note. |
| 🚚 **Delivery Note + Packing Slip** | Customer + warehouse | One PDF combining the priced delivery table and the unpriced warehouse packing checklist, with two signature blocks. Quantities reflect the trade's final delivered amount. |
| 🏷️ **Vendor Purchase Order** | Vendor | Our PO to the supplier — line items at cost rate, payment terms based on vendor terms. |
| 🧾 **Payment Receipt · {date}** | Customer | One row per inbound payment. Each is a separate receipt PDF with the specific payment date, amount, method and reference. |

In addition, **per-delivery-event** docs appear (one row per unique
receipt date, with a pale-yellow background to distinguish them):

| Per-event doc | What's different |
|---|---|
| 🚚 **Delivery + Packing · {date}** | DN+PS for the goods received that day only — qty / values reflect just that delivery. |
| 🧾 **Invoice · {date}** | Per-receipt invoice billed for the qty received on that date. If a customer-paid bilty exists for that delivery, the invoice automatically shows a *Less: Bilty paid by customer* line and a **Net Amount Due** callout below the standard total. Due date = delivery date + customer terms. |

### Customer PO & Attachments

Documents from the **buyer's** side — usually their original purchase
order. Drop one (or several) files, click to browse, or **paste**
(Cmd+V) directly into the zone. Multiple files supported.

For each uploaded attachment you see:
- File link with a 📎 icon
- Kind (Customer PO / Other)
- Size
- Upload date
- **Delete** link

### Receipts (Partial Deliveries)

When a trade ships in batches, each batch becomes a row here:

| Column | What it shows |
|---|---|
| **Item** | Which line was delivered |
| **Received On** | Date of delivery |
| **Qty** | Amount delivered in this batch |
| **Vendor Invoice** | Click 📎 to open the vendor's invoice image you uploaded during partial-receive (or it shows "—") |
| **Bilty** | If no bilty: a blue **+ Add Bilty** link. If a bilty exists: 🚛 Amount · Edit (orange), plus a *paid by customer* chip if applicable, plus the kgs and terminal name on the next line. |
| **Notes** | Free text recorded at receive time |
| **Actions** | Delete this receipt |

#### How partial receipts work

When you click **+ Receive Partial** at the top:
1. A modal opens showing each trade line with: ordered qty (read-only),
   already-received total (read-only), and a *qty for this delivery*
   input you fill in per line.
2. You can attach a **vendor invoice file** for each line (image / PDF) —
   supports click, drag-drop, or Cmd+V paste.
3. The receive date defaults to today but is editable.
4. Submitting saves the receipts. **No journal entries are posted at this
   stage** — partial receipts are just operational records.

#### How bilty works

Bilty is the **transport expense** for a delivery. Each receipt date can
have at most one bilty. Click **+ Add Bilty** on any receipt row:

1. Modal opens scoped to that specific delivery date.
2. **Description** — e.g. "Bilty Karachi → Lahore".
3. **Customer paid this on our behalf** checkbox — when ticked, the
   expense reduces the customer's receivable instead of cash.
4. **Paid From (cash / bank)** — picker; hidden when "paid by customer"
   is ticked.
5. **Expense Account** — locked to **Profit / Loss A/C** (project
   convention — bilty is a trade cost so it routes through the same
   clearing account as SAL/PUR, not a separate operating-expense
   account).
6. **Amount** — leave at 0 to record "no bilty for this delivery".
7. **Weight (kgs)** — for reporting / record-keeping.
8. **Terminal / Carrier** — typeahead. Type the carrier's name; if it
   exists in your past terminals it autocompletes, otherwise a new
   terminal is created on save.

Behaviour rules:

- **Editing a bilty updates the SAME entry in place.** No reversal
  entries, no new EXP- references. The voucher list stays clean.
- **Saving with amount = 0** removes the bilty entirely (entry +
  metadata + line items) — not a stub, not a reversal, just gone.
- When ticked **paid by customer**, the bilty amount is automatically
  deducted from the per-receipt invoice and reduces the customer's
  outstanding receivable.

### Costs Absorbed by Capital

Any **Record Cost** entries (bilty, demurrage, loading, broker fees,
etc.) appear here:

| Column | What it shows |
|---|---|
| **Ref** | Journal voucher reference (e.g. JV-0007) |
| **Date** | Cost date |
| **Description** | Free text you entered |
| **Payee** | Account code + name. If the customer paid, an orange **paid by customer** chip appears. |
| **Amount** | Cost amount. Green if paid by customer (receivable reduction), orange if absorbed by capital. |
| **Actions** | **Delete** — reverses the underlying journal entry |

A *Total Cost Absorbed* number sits at the top-right of the section
header.

### Customer Payments (Inbound)

A consolidated view of every cash inflow against this trade, plus any
costs the customer paid on our behalf (treated as cash-equivalent
since they reduce the receivable).

**Summary strip:** Invoiced · Paid in cash · *Paid via cost absorption*
(only shown when > 0) · Outstanding

**Table rows:**
- One row per *Record Customer Payment* — date, source account, method,
  amount (green +), Delete link.
- One row per customer-paid cost / bilty — same shape but with the
  *paid by customer* chip.

> **Note:** There is no Vendor Payments table on the trade page.
> Vendor payments are tracked **globally** on the party (vendor) ledger,
> not per-trade. The block at the bottom of this section points you to
> the Parties ledger or the Vouchers page for vendor payouts.

### Notes / Cancellation Reason

If you typed any **Notes** on the new-trade form, they appear in a
yellow accent card near the bottom.

If the trade was **Cancelled**, a red accent card shows the cancellation
reason.

---

## Part 3 — Trade lifecycle (typical day-in-the-life)

A back-to-back trade typically goes:

1. **Quote → accept → trade is created** (OPEN status). No journals.
2. **Customer's PO arrives** → upload it via the *Customer PO &
   Attachments* section. Multi-file, paste-friendly.
3. **Order Confirmation PDF** is sent to the customer (Documents
   section) — shows ordered qty + 10-15 % tolerance.
4. **Vendor PO PDF** is sent to the supplier.
5. **First partial delivery** → click **+ Receive Partial**, enter qty,
   upload vendor invoice. No journals yet.
6. **Add bilty** for that delivery (on the receipt row). DR P&L A/C /
   CR cash (or customer A/R if they paid).
7. **Per-event Invoice + DN+PS PDFs** for that delivery become available
   in the Documents section (pale yellow rows).
8. **Customer pays** → click **Record Customer Payment**. Posts the cash
   receipt; *Outstanding* drops.
9. **More partial deliveries** … each repeats the cycle.
10. **Mark Complete** → posts the full SAL + PUR entries (final qtys),
    then the closing entry transferring profit to Capital A/C. Status
    flips to **Delivered**.
11. **Final customer payment(s)** → status flips to **Partially Paid**
    or **Paid** as the cash comes in.
12. **Close Trade** → status flips to **Closed**. The trade is now
    history; everything stays viewable but nothing more can be added.

If anything goes wrong before close:
- **Cancel** posts reversal entries for everything that was posted —
  preserving an audit trail. Status flips to **Cancelled**.
- **Delete** wipes the trade + all linked journals from history. No
  audit trail. Use only when the trade was a mistake.

That's the entire trade flow, from quote to close.
