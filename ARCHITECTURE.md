# 🏗️ Technical Architecture - Wealth Tracker Phase 1

## System Overview

```
┌─────────────┐      ┌──────────────┐      ┌─────────────┐
│   Browser   │─────▶│   FastAPI    │─────▶│   SQLite    │
│ (HTMX/HTML) │◀─────│  + Jinja2    │◀─────│  Database   │
└─────────────┘      └──────────────┘      └─────────────┘
     │                      │                      │
     │                      │                      │
     └──────── HTMX ────────┴────── SQLModel ─────┘
```

## Technology Stack

### Backend
- **FastAPI** 0.109.0 - Modern Python web framework
- **SQLModel** 0.0.14 - Type-safe ORM (SQLAlchemy + Pydantic)
- **Alembic** 1.13.1 - Database migrations
- **Python** 3.10+ - Programming language

### Frontend
- **Jinja2** 3.1.3 - Server-side templating
- **HTMX** 1.9.10 - Dynamic HTML without JavaScript
- **Tailwind CSS** (CDN) - Utility-first styling

### Database
- **SQLite** - File-based relational database
- **Location**: `wealth_tracker.db`

### Testing
- **pytest** 7.4.4 - Testing framework
- **pytest-asyncio** 0.23.3 - Async test support
- **httpx** 0.26.0 - HTTP client for API tests

## Architecture Layers

### 1. Presentation Layer (Routes)

**routes/assets.py**
- Handles HTTP requests for asset management
- Returns HTML responses (Jinja2 templates)
- HTMX-aware (checks HX-Request header)
- Endpoints: list, create, edit, rename, delete

**routes/wealth.py**
- Manages wealth entry requests
- Computes aggregations for display
- Supports CSV export
- Endpoints: entries, new entry, month detail, summary

**Key Pattern:**
```python
@router.get("/path")
async def handler(request: Request, session: Session = Depends(get_session)):
    data = service.do_work(session, ...)
    return templates.TemplateResponse("template.html", {...})
```

### 2. Business Logic Layer (Services)

**services/assets.py**
```python
class AssetService:
    - create_asset()      # Validates uniqueness, normalizes slug
    - list_assets()       # Optional search filtering
    - rename_asset()      # Checks for conflicts
    - delete_asset()      # Hard delete with cascade
```

**services/wealth.py**
```python
class WealthService:
    - upsert_valuation()              # Create or update
    - get_month_snapshot()            # All valuations for month
    - get_previous_month_snapshot()   # Latest month before current
    - compute_changes()               # Per-asset and aggregate math
    - list_months()                   # All months with data
    - range_stats()                   # Average gain calculation
    - recalc_month_networth_cache()   # Update materialized view
```

**Key Principles:**
- Pure business logic (no HTTP concerns)
- Database session passed as parameter
- Exceptions for validation errors
- Return domain objects or DTDs

### 3. Data Access Layer (Models)

**models.py**
```python
class Asset(SQLModel, table=True):
    - Relationship: one-to-many with AssetValuation
    - Cascade delete to valuations
    - Unique constraint: (user_id, slug)

class AssetValuation(SQLModel, table=True):
    - Foreign key: assets.id (ON DELETE CASCADE)
    - Unique constraint: (user_id, asset_id, year_month)
    - Indexes for efficient queries

class MonthNetworth(SQLModel, table=True):
    - Materialized cache for performance
    - Updated on valuation upsert
    - Unique constraint: (user_id, year_month)
```

**Indexes:**
- `idx_user_slug` on `assets(user_id, slug)` - UNIQUE
- `idx_user_asset_month` on `asset_valuations(user_id, asset_id, year_month)` - UNIQUE
- `idx_user_month` on `asset_valuations(user_id, year_month)` - Non-unique
- `idx_user_month_networth` on `month_networth(user_id, year_month)` - UNIQUE

### 4. Validation Layer (Schemas)

**schemas.py**
```python
# Request validation
class AssetCreate(BaseModel):
    asset_name: str (1-255 chars)

class ValuationCreate(BaseModel):
    asset_id: int
    year_month: str (pattern: YYYY-MM)
    value: Decimal (>= 0, 2 decimal places)

# Response serialization
class AssetResponse(BaseModel):
    from_attributes = True  # For SQLModel compatibility
```

### 5. Utility Layer

**utils.py**
- `normalize_slug()` - Convert name to URL-safe slug
- `parse_year_month()` - Validate and parse YYYY-MM
- `format_currency()` - $1,234.56
- `format_delta()` - +$500.00 or -$100.00
- `quantize_decimal()` - Enforce 2 decimal places

**config.py**
- Application constants
- Allocation percentages
- Default user ID

**database.py**
- Engine creation
- Session factory
- Dependency injection helper

## Data Flow Examples

### Creating an Asset

```
1. Browser: POST /wealth/assets {asset_name: "Savings"}
2. Route: routes/assets.py::create_asset()
3. Service: AssetService.create_asset(session, 1, "Savings")
   - Normalize slug: "savings"
   - Check uniqueness: SELECT ... WHERE user_id=1 AND slug='savings'
   - Insert: Asset(user_id=1, name="Savings", slug="savings")
4. Route: Return asset_list_rows.html partial
5. HTMX: Swap into #asset-list div
6. Browser: Updated list displayed
```

### Computing Month Changes

```
1. Browser: GET /wealth/entries/2024-11
2. Route: routes/wealth.py::month_detail()
3. Service: WealthService.compute_changes(session, 1, "2024-11")
   - Get current snapshot: {asset1: 1500, asset2: 2000}
   - Get previous snapshot: {asset1: 1000, asset2: 1800}
   - Compute per-asset: {asset1: +500, asset2: +200}
   - Compute totals: networth_change=700, donation=70, etc.
4. Route: Return wealth_month_detail.html
5. Browser: Full page with tables and cards
```

### HTMX Partial Update

```
1. Browser: Input keyup event (search)
2. HTMX: GET /wealth/assets?query=sav (300ms debounce)
   - Header: HX-Request: true
3. Route: Check request.headers.get("HX-Request")
4. Service: AssetService.list_assets(session, 1, "sav")
5. Route: Return partial template (just rows)
6. HTMX: Swap into target div
7. Browser: Only affected section updated
```

## Database Schema

```sql
CREATE TABLE assets (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(255) NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    CONSTRAINT idx_user_slug UNIQUE (user_id, slug)
);

CREATE TABLE asset_valuations (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    asset_id INTEGER NOT NULL,
    year_month VARCHAR(7) NOT NULL,
    value DECIMAL(18,2) NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE,
    CONSTRAINT idx_user_asset_month UNIQUE (user_id, asset_id, year_month)
);

CREATE INDEX idx_user_month ON asset_valuations(user_id, year_month);

CREATE TABLE month_networth (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    year_month VARCHAR(7) NOT NULL,
    networth DECIMAL(18,2) NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    CONSTRAINT idx_user_month_networth UNIQUE (user_id, year_month)
);
```

## Security Considerations

### Current State (Single-User)
- `DEFAULT_USER_ID = 1` hardcoded
- No authentication/authorization
- All queries filtered by user_id=1

### Future Multi-User
```python
# Add authentication middleware
from fastapi import Depends
from fastapi.security import HTTPBearer

def get_current_user(token: str = Depends(HTTPBearer())):
    # Verify JWT, return user_id
    return verify_token(token)

# Update routes
@router.get("/assets")
def list_assets(user_id: int = Depends(get_current_user)):
    return AssetService.list_assets(session, user_id)
```

### Input Validation
- Pydantic schemas validate all inputs
- SQLModel prevents SQL injection
- CSRF protection via HTMX headers
- No eval() or exec() usage

## Performance Optimizations

### 1. Database
- Indexes on frequent queries
- MonthNetworth cache for aggregations
- Batch operations where possible
- Connection pooling (SQLAlchemy)

### 2. Frontend
- HTMX for partial updates (less data transfer)
- Tailwind CDN (cached by browser)
- Minimal JavaScript
- Server-side rendering (faster first paint)

### 3. Caching Strategy
- MonthNetworth: Pre-computed totals
- Future: Redis for session/query caching

## Testing Strategy

### Unit Tests (test_assets.py, test_wealth.py)
- Service layer logic
- Edge cases (duplicates, missing data)
- Math validation (change computation)
- In-memory SQLite (fast, isolated)

### Integration Tests (test_api.py)
- Full request/response cycle
- HTMX endpoint behavior
- Template rendering
- Database persistence

### Test Fixtures (conftest.py)
```python
@pytest.fixture
def session():
    # In-memory database per test
    engine = create_engine("sqlite:///:memory:")
    with Session(engine) as session:
        yield session
```

## Deployment Considerations

### Development
```bash
uvicorn main:app --reload --port 8003
```

### Production
```bash
# Use Gunicorn with Uvicorn workers
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker

# Or Docker
FROM python:3.11-slim
COPY . /app
RUN pip install -r requirements.txt
CMD ["uvicorn", "main:app", "--host", "0.0.0.0"]
```

### Database Migration
```bash
# Development
alembic upgrade head

# Production
alembic upgrade head
# Consider backup first!
```

## Monitoring & Logging

### Current
- SQLAlchemy echo=True (dev only)
- FastAPI auto-logs requests
- Pytest captures all output

### Production Recommendations
- Use uvicorn --log-config for structured logs
- Add Sentry for error tracking
- Prometheus metrics endpoint
- Database query logging

## Code Quality

### Type Safety
- All functions type-annotated
- Pydantic validation at boundaries
- SQLModel prevents type mismatches

### Code Organization
- Layered architecture
- Single responsibility
- Dependency injection
- Pure functions where possible

### Documentation
- Docstrings on all public methods
- README with architecture overview
- Inline comments for complex logic

## Extension Points

### Adding New Features
1. **New Model**: Add to `models.py`, create migration
2. **New Service**: Add to `services/`, inject session
3. **New Route**: Add to `routes/`, use service layer
4. **New Template**: Add to `templates/`, extend base.html
5. **New Tests**: Add to `tests/`, use fixtures

### Example: Adding Budget Tracking
```python
# models.py
class Budget(SQLModel, table=True):
    id: int
    user_id: int
    category: str
    amount: Decimal
    month: str

# services/budget.py
class BudgetService:
    @staticmethod
    def create_budget(session, user_id, category, amount, month):
        ...

# routes/budget.py
@router.get("/budgets")
def list_budgets(session: Session = Depends(get_session)):
    ...
```

## Conclusion

This architecture provides:
- ✅ Clear separation of concerns
- ✅ Type safety throughout
- ✅ Easy testing
- ✅ Maintainable codebase
- ✅ Extensibility
- ✅ Performance

The layered approach allows independent testing and modification of each component while maintaining clean boundaries between concerns.
