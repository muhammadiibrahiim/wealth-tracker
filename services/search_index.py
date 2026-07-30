"""Canonical registry of every navigable page in Wealth Tracker.

Both the command palette (`/api/search`, `/api/search/pages`) and the
completeness audit read this list. Adding a page to the app means adding a
line here — otherwise it exists but is unreachable by search.

Entry shape:
    title   human name, as the page's own <h1> shows it
    module  section label shown as the palette subtitle
    url     exact absolute path (no {params}, no .pdf, no modal fragments)
    keys    lowercase keyword blob for fuzzy matching — be generous, these
            are what make search feel good
    code    2-3 char uppercase go-to code (press G then the code), or ""
"""

PAGES = [
    # ---------------- Wealth ----------------
    {"title": "Wealth", "module": "Wealth", "url": "/wealth", "code": "WT",
     "keys": "wealth home net worth assets overview tracker money"},
    {"title": "Wealth Entries", "module": "Wealth", "url": "/wealth/entries", "code": "WE",
     "keys": "wealth entries monthly valuations history snapshots months record"},
    {"title": "New Wealth Entry", "module": "Wealth", "url": "/wealth/entries/new", "code": "WN",
     "keys": "new wealth entry add valuation record month create"},
    {"title": "Wealth Summary", "module": "Wealth", "url": "/wealth/entries/summary", "code": "WS",
     "keys": "wealth summary trends totals growth change month range chart"},
    {"title": "Assets", "module": "Wealth", "url": "/wealth/assets", "code": "AS",
     "keys": "assets list manage property cash gold accounts components net worth"},

    # ---------------- Habits ----------------
    {"title": "Daily Habits", "module": "Habits", "url": "/habits", "code": "HB",
     "keys": "habits daily tracker check 1% improvement routine tick today"},
    {"title": "Life Aspects", "module": "Habits", "url": "/habits/aspects", "code": "HA",
     "keys": "life aspects habits categories areas manage configure add"},
    {"title": "Habit Stats", "module": "Habits", "url": "/habits/stats", "code": "HS",
     "keys": "habit stats statistics streak completion rate chart trend progress"},

    # ---------------- Investments ----------------
    {"title": "Investments", "module": "Investments", "url": "/investments", "code": "IN",
     "keys": "investments list npv irr payback discount rate capital returns"},

    # ---------------- Accounts (net worth) ----------------
    {"title": "Net Worth", "module": "Accounts", "url": "/accounts", "code": "NW",
     "keys": "net worth accounts dashboard money manager balances assets liabilities"},
    {"title": "Import", "module": "Accounts", "url": "/accounts/import", "code": "AI",
     "keys": "import money manager upload sync csv data accounts file"},
    {"title": "Net Worth Reports", "module": "Accounts", "url": "/accounts/reports", "code": "AR",
     "keys": "accounts reports hub statements cashflow income expense trial balance"},
    {"title": "Cash Flow", "module": "Accounts · Reports", "url": "/accounts/reports/cashflow", "code": "ACF",
     "keys": "cash flow accounts inflow outflow movement money in out period"},
    {"title": "Income & Expense", "module": "Accounts · Reports", "url": "/accounts/reports/income-expense", "code": "IEX",
     "keys": "income expense accounts category spending earnings totals breakdown"},
    {"title": "Statements", "module": "Accounts · Reports", "url": "/accounts/reports/statements", "code": "STM",
     "keys": "statements accounts transactions ledger account history period"},
    {"title": "Trial Balance", "module": "Accounts · Reports", "url": "/accounts/reports/trial-balance", "code": "ATB",
     "keys": "trial balance accounts debits credits agree check tb"},

    # ---------------- Trade ----------------
    {"title": "Trade Dashboard", "module": "Trade", "url": "/trade", "code": "TD",
     "keys": "trade dashboard overview kpi profit sales receivable overdue capital roce"},
    {"title": "Trades", "module": "Trade", "url": "/trade/trades", "code": "TR",
     "keys": "trades list deals orders buy sell open closed delivered"},
    {"title": "Quotations", "module": "Trade", "url": "/trade/quotations", "code": "TQ",
     "keys": "quotations quotes price offer customer draft sent accepted rejected"},
    {"title": "Goods Received", "module": "Trade", "url": "/trade/goods-received", "code": "GR",
     "keys": "goods received inbound vendor delivery stock arrived pending receipts"},
    {"title": "Parties", "module": "Trade", "url": "/trade/parties", "code": "TP",
     "keys": "parties customers vendors suppliers buyers contacts master data"},
    {"title": "Partners", "module": "Trade", "url": "/trade/partners", "code": "TN",
     "keys": "partners profit share capital contribution allocation owner equity draw"},
    {"title": "Items", "module": "Trade", "url": "/trade/items", "code": "TI",
     "keys": "items products goods sku master data specs unit price cost"},
    {"title": "Cash Accounts", "module": "Trade", "url": "/trade/accounts", "code": "TA",
     "keys": "cash accounts bank wallet balance kind master data money"},
    {"title": "Chart of A/Cs", "module": "Trade", "url": "/trade/coa", "code": "COA",
     "keys": "chart of accounts coa ledger codes classes subclasses master"},
    {"title": "Vouchers", "module": "Trade", "url": "/trade/vouchers", "code": "TV",
     "keys": "vouchers journal entries receipt payment contra owner debit credit"},
    {"title": "Cash Projection", "module": "Trade", "url": "/trade/projection", "code": "TJ",
     "keys": "projection cash forecast sheet daily plan future runway negative"},
    {"title": "Testing", "module": "Trade", "url": "/trade/testing", "code": "TT",
     "keys": "testing diagnostics developer debug trade tools"},

    # ---------------- Trade reports ----------------
    {"title": "Reports", "module": "Trade", "url": "/trade/reports", "code": "RP",
     "keys": "reports hub trade financial statements business intelligence operational"},

    {"title": "Trial Balance", "module": "Trade · Reports", "url": "/trade/reports/trial-balance", "code": "TB",
     "keys": "trial balance debits credits accounts class agree check tb statement"},
    {"title": "Profit & Loss", "module": "Trade · Reports", "url": "/trade/reports/pnl", "code": "PL",
     "keys": "profit loss pnl p&l income statement revenue cogs expenses net margin"},
    {"title": "Balance Sheet", "module": "Trade · Reports", "url": "/trade/reports/balance-sheet", "code": "BS",
     "keys": "balance sheet assets liabilities equity position date statement"},
    {"title": "Cash Flow Statement", "module": "Trade · Reports", "url": "/trade/reports/cash-flow", "code": "CF",
     "keys": "cash flow statement indirect operating investing financing movement"},
    {"title": "General Ledger", "module": "Trade · Reports", "url": "/trade/reports/general-ledger", "code": "GL",
     "keys": "general ledger account transactions running balance history postings"},
    {"title": "Cashbook", "module": "Trade · Reports", "url": "/trade/reports/cashbook", "code": "CB",
     "keys": "cashbook cash bank transactions receipts payments movement daily"},
    {"title": "Day Book", "module": "Trade · Reports", "url": "/trade/reports/day-book", "code": "DB",
     "keys": "day book daybook vouchers date audit all entries single day"},
    {"title": "Party Ledger", "module": "Trade · Reports", "url": "/trade/reports/ledger", "code": "LG",
     "keys": "party ledger customer vendor statement balance transactions account"},

    {"title": "Customer Profitability", "module": "Trade · Reports", "url": "/trade/reports/customer-profitability", "code": "CP",
     "keys": "customer profitability revenue gross profit dso concentration ranking best worst"},
    {"title": "Vendor Performance", "module": "Trade · Reports", "url": "/trade/reports/vendor-performance", "code": "VP",
     "keys": "vendor performance supplier purchases delivery accuracy dpo ranking"},
    {"title": "Item Profitability", "module": "Trade · Reports", "url": "/trade/reports/item-profitability", "code": "IP",
     "keys": "item profitability product margin velocity spec revenue ranking"},
    {"title": "Trade Profitability", "module": "Trade · Reports", "url": "/trade/reports/trade-profitability", "code": "TF",
     "keys": "trade profitability deal gross profit variance unsettled top ranking"},
    {"title": "Working Capital", "module": "Trade · Reports", "url": "/trade/reports/working-capital", "code": "WC",
     "keys": "working capital dso dpo ccc cash conversion cycle current ratio roce health"},
    {"title": "Cash Forecast", "module": "Trade · Reports", "url": "/trade/reports/forecast", "code": "FC",
     "keys": "cash forecast projected 30 60 90 days future negative runway plan"},
    {"title": "Daily Cash Requirement", "module": "Trade · Reports", "url": "/trade/reports/daily-cash", "code": "DC",
     "keys": "daily cash requirement injection day by day need shortfall fund"},
    {"title": "Cash Flow Management", "module": "Trade · Reports", "url": "/trade/reports/cashflow-management", "code": "CM",
     "keys": "cash flow management delay vendor payments schedule fund plan tier"},

    {"title": "Sales Report", "module": "Trade · Reports", "url": "/trade/reports/sales", "code": "SR",
     "keys": "sales report revenue cost profit month trend register"},
    {"title": "Item Report", "module": "Trade · Reports", "url": "/trade/reports/items", "code": "IR",
     "keys": "item report units sold revenue margin per item register"},
    {"title": "AR Aging", "module": "Trade · Reports", "url": "/trade/reports/aging", "code": "AG",
     "keys": "ar aging receivables overdue buckets days customer collect debtors chase"},
    {"title": "AP Aging", "module": "Trade · Reports", "url": "/trade/reports/ap-aging", "code": "AP",
     "keys": "ap aging payables overdue buckets days vendor owe creditors"},
    {"title": "Pending Receivable Items", "module": "Trade · Reports", "url": "/trade/reports/pending-receivables", "code": "PR",
     "keys": "pending receivable items quantity owed vendor trade line value short"},
    {"title": "Expenses", "module": "Trade · Reports", "url": "/trade/reports/expenses", "code": "EX",
     "keys": "expenses vouchers plates design freight trips writeoff category cost spend"},
    {"title": "Bilty Report", "module": "Trade · Reports", "url": "/trade/reports/bilty", "code": "BR",
     "keys": "bilty freight consignment terminal weight transport dispatch amount"},
    {"title": "Goods Sent", "module": "Trade · Reports", "url": "/trade/reports/goods-sent", "code": "GS",
     "keys": "goods sent dispatch customer po quantity statement date range delivered"},
    {"title": "Vendor Pending Goods", "module": "Trade · Reports", "url": "/trade/reports/vendor-pending", "code": "VG",
     "keys": "vendor pending goods owed supplier statement outstanding quantity"},
    {"title": "Customer Pending Goods", "module": "Trade · Reports", "url": "/trade/reports/customer-pending", "code": "CG",
     "keys": "customer pending goods deliver owe outstanding quantity sale rate"},
]


def _rank(page, term):
    """Lower is better. Explicit ranking is what makes the palette feel
    responsive rather than random."""
    title = page["title"].lower()
    if title.startswith(term):
        return 0
    if any(w.startswith(term) for w in title.split()):
        return 1
    if term in title:
        return 2
    if term in page["keys"]:
        return 3
    return 99


def search_pages(term: str, limit: int = 12) -> list:
    """Match PAGES on title or keywords. Returns palette-shaped dicts."""
    term = (term or "").strip().lower()
    if not term:
        chosen = PAGES[:limit]
    else:
        scored = []
        for p in PAGES:
            r = _rank(p, term)
            if r < 99:
                scored.append((r, p))
        scored.sort(key=lambda t: (t[0], t[1]["title"]))
        chosen = [p for _, p in scored[:limit]]
    return [
        {"type": "Page", "title": p["title"], "subtitle": p["module"],
         "url": p["url"], "code": p["code"]}
        for p in chosen
    ]


def all_codes() -> dict:
    """{code: url} for the G-shortcut. Raises on a duplicate — a silent clash
    would make one page unreachable by keyboard, and that bug is invisible
    until someone complains."""
    out = {}
    dupes = []
    for p in PAGES:
        c = (p.get("code") or "").strip().upper()
        if not c:
            continue
        if c in out:
            dupes.append(c)
        out[c] = p["url"]
    if dupes:
        raise ValueError(f"duplicate go-to codes in search_index.PAGES: {sorted(set(dupes))}")
    return out
