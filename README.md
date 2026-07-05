# Wealth Tracker - Phase 1

A comprehensive wealth tracking web application built with FastAPI, SQLModel, SQLite, Jinja2, HTMX, and Tailwind CSS.

## Features

### Assets Management
- Create, read, update, and delete assets
- Case-insensitive unique asset names per user
- Real-time search with HTMX
- Asset slug generation for URL-friendly identifiers

### Wealth Tracking
- Monthly asset valuations with PKR currency support
- **Supports negative values** for tracking liabilities and debts (e.g., loans, credit cards)
- Automatic upsert (one entry per asset per month)
- Previous month entries allowed - not limited to current month
- Change computation comparing current vs previous month
- Detailed month view with per-asset changes
- Allocation breakdown: 10% donation, 20% personal expense, 70% investment

### Summary & Analytics
- Date range filtering
- Average monthly net worth gain calculation
- Networth timeline visualization
- CSV export functionality
- Month-over-month comparison

## Architecture

### Backend Stack
- **FastAPI**: Modern web framework with automatic API documentation
- **SQLModel**: Type-safe ORM combining SQLAlchemy and Pydantic
- **SQLite**: Lightweight database with Alembic migrations
- **Layered Architecture**:
  - `models.py`: Database models (Asset, AssetValuation, MonthNetworth)
  - `schemas.py`: Request/response validation schemas
  - `services/`: Business logic layer (assets.py, wealth.py)
  - `routes/`: API endpoints (assets.py, wealth.py)
  - `utils.py`: Helper functions for dates, formatting, slugs

### Frontend Stack
- **Jinja2**: Server-side templating
- **HTMX**: Dynamic updates without JavaScript
- **Tailwind CSS**: Utility-first styling via CDN

### Database Schema

**Asset**
- id (PK), user_id, name, slug
- Unique constraint: (user_id, slug)
- Cascade delete to valuations

**AssetValuation**
- id (PK), user_id, asset_id (FK), year_month, value
- Unique constraint: (user_id, asset_id, year_month)
- Indexes: (user_id, year_month), (user_id, asset_id, year_month)

**MonthNetworth** (Cache)
- id (PK), user_id, year_month, networth
- Unique constraint: (user_id, year_month)

## Installation

### Prerequisites
- Python 3.10+
- pip

### Setup

1. **Clone/Download the project**
```powershell
cd "c:\Users\USMAN\OneDrive\Desktop\Wealth Tracker"
```

2. **Install dependencies**
```powershell
pip install -r requirements.txt
```

3. **Run database migrations**
```powershell
alembic upgrade head
```

4. **Seed demo data (optional)**
```powershell
python seed.py
```

## Running the Application

### Development Server
```powershell
uvicorn main:app --reload --port 8003
```

Visit: **http://localhost:8003**

### Production
```powershell
uvicorn main:app --host 0.0.0.0 --port 8003
```

## Testing

Run the complete test suite:
```powershell
pytest tests/ -v
```

Run specific test file:
```powershell
pytest tests/test_assets.py -v
```

Test coverage:
- 33 tests covering assets, wealth, and API endpoints
- Service layer logic validation
- HTMX endpoint testing
- Edge cases (duplicate assets, negative values, missing data)

## Project Structure

```
Wealth Tracker/
├── main.py                     # FastAPI app entry point
├── database.py                 # Database configuration
├── models.py                   # SQLModel data models
├── schemas.py                  # Pydantic schemas
├── config.py                   # App configuration
├── utils.py                    # Utility functions
├── seed.py                     # Database seeding
│
├── services/                   # Business logic layer
│   ├── __init__.py
│   ├── assets.py              # Asset management
│   └── wealth.py              # Wealth tracking
│
├── routes/                     # API endpoints
│   ├── __init__.py
│   ├── assets.py              # Asset routes
│   └── wealth.py              # Wealth routes
│
├── templates/                  # Jinja2 templates
│   ├── base.html              # Base layout
│   ├── wealth_home.html       # Home page
│   ├── assets_list.html       # Assets list
│   ├── asset_new_modal.html   # Create asset modal
│   ├── asset_edit_modal.html  # Edit asset modal
│   ├── wealth_entries_list.html
│   ├── wealth_entries_new.html
│   ├── wealth_month_detail.html
│   ├── wealth_summary.html
│   └── partials/              # HTMX partial templates
│       ├── asset_list_rows.html
│       └── valuation_rows.html
│
├── static/                     # Static assets (empty for now)
│
├── tests/                      # Test suite
│   ├── conftest.py            # Test configuration
│   ├── test_assets.py         # Asset tests
│   ├── test_wealth.py         # Wealth tests
│   └── test_api.py            # API endpoint tests
│
├── alembic/                    # Database migrations
│   ├── versions/
│   └── env.py
│
├── requirements.txt
├── pyproject.toml
├── alembic.ini
└── README.md
```

## API Endpoints

### Assets
- `GET /wealth/assets` - List assets (with search)
- `GET /wealth/assets/new` - New asset form (modal)
- `POST /wealth/assets` - Create asset
- `GET /wealth/assets/{id}/edit` - Edit asset form (modal)
- `POST /wealth/assets/{id}/rename` - Rename asset
- `POST /wealth/assets/{id}/delete` - Delete asset

### Wealth
- `GET /wealth` - Home page
- `GET /wealth/entries` - List entries
- `GET /wealth/entries/new` - New entry form
- `POST /wealth/entries/add_row` - Add/update valuation (HTMX)
- `GET /wealth/entries/{year_month}` - Month detail
- `GET /wealth/entries/summary` - Summary with filters
- `GET /wealth/entries/summary/csv` - CSV export

### System
- `GET /` - Redirects to /wealth
- `GET /health` - Health check

## Key Features Implementation

### 1. Asset Name Uniqueness
- Case-insensitive via slug normalization
- User-scoped uniqueness (multiple users can have same asset name)
- Validation at service layer with descriptive errors

### 2. Valuation Upsert
- One valuation per asset per month
- UPDATE if exists, INSERT if new
- Automatic MonthNetworth cache update

### 3. Change Computation
- Compares current month vs most recent previous month
- Handles missing previous data (treats as 0)
- Per-asset and aggregate calculations
- Allocation formulas: donation (10%), personal (20%), investment (70%)

### 4. Range Statistics
- Flexible date range (specific or all-time)
- Average monthly gain: (end - start) / number_of_gaps
- Networth timeline with month-over-month changes

### 5. HTMX Integration
- Partial template updates for smooth UX
- Modals without page refresh
- Search debouncing (300ms)
- Inline form validation

## Data Invariants

✅ `year_month` format: "YYYY-MM" (validated)  
✅ `value` >= 0.00 (enforced)  
✅ Asset slug: lowercase, hyphenated (auto-generated)  
✅ Decimal precision: 2 places (quantized)  
✅ Cascade delete: Asset → AssetValuation  
✅ Cache consistency: MonthNetworth auto-updated  

## Multi-User Support

Currently configured for single-user mode with `DEFAULT_USER_ID = 1`.

**For multi-user:**
1. Add authentication middleware
2. Replace `DEFAULT_USER_ID` with session user
3. Add User model with relationships
4. Update all queries to filter by authenticated user

## Troubleshooting

### Database Issues
```powershell
# Reset database
Remove-Item wealth_tracker.db
alembic upgrade head
python seed.py
```

### Port Already in Use
```powershell
# Use different port
uvicorn main:app --reload --port 8001
```

### Missing Dependencies
```powershell
pip install -r requirements.txt --upgrade
```

## Future Enhancements (Post-Phase 1)

- [ ] User authentication & authorization
- [ ] Asset categories/tags
- [ ] Multi-currency support
- [ ] Interactive charts (Chart.js/Plotly)
- [ ] Budget tracking
- [ ] Recurring expense tracking
- [ ] Goal setting & progress
- [ ] Mobile-responsive refinements
- [ ] Dark mode
- [ ] Export to PDF

## Technical Decisions

### Why HTMX over React/Vue?
- Simpler architecture for server-side rendering
- No build step required
- Progressive enhancement
- Smaller payload, faster initial load

### Why SQLite?
- Zero configuration
- File-based (easy backup)
- Sufficient for single-user/small-scale
- Can migrate to PostgreSQL later

### Why Alembic?
- Idempotent migrations
- Version control for schema
- Team collaboration support
- Rollback capability

## License

MIT License - Feel free to use for personal or commercial projects.

## Author

Built as Phase 1 of Wealth Tracker application.

---

**Status**: ✅ Phase 1 Complete - All features implemented and tested
