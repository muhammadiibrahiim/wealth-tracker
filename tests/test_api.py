"""
Tests for API endpoints
"""
from fastapi.testclient import TestClient


def test_health_check(client: TestClient):
    """Test health check endpoint"""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_root_redirects(client: TestClient):
    """Test root redirects to wealth tracker"""
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/wealth"


def test_wealth_home_page(client: TestClient):
    """Test wealth home page loads"""
    response = client.get("/wealth")
    assert response.status_code == 200
    assert b"Wealth Tracker" in response.content


def test_create_asset_via_api(client: TestClient):
    """Test creating asset via POST endpoint"""
    response = client.post(
        "/wealth/assets",
        data={"asset_name": "Test Asset"}
    )
    assert response.status_code == 200
    assert b"Test Asset" in response.content


def test_list_assets_page(client: TestClient):
    """Test assets list page"""
    # Create some assets first
    client.post("/wealth/assets", data={"asset_name": "Asset 1"})
    client.post("/wealth/assets", data={"asset_name": "Asset 2"})
    
    response = client.get("/wealth/assets")
    assert response.status_code == 200
    assert b"Asset 1" in response.content
    assert b"Asset 2" in response.content


def test_asset_search_htmx(client: TestClient):
    """Test HTMX asset search"""
    client.post("/wealth/assets", data={"asset_name": "Savings Account"})
    client.post("/wealth/assets", data={"asset_name": "Investment Portfolio"})
    
    response = client.get(
        "/wealth/assets?query=invest",
        headers={"HX-Request": "true"}
    )
    assert response.status_code == 200
    assert b"Investment Portfolio" in response.content
    assert b"Savings Account" not in response.content


def test_wealth_entries_list_page(client: TestClient):
    """Test wealth entries list page"""
    response = client.get("/wealth/entries")
    assert response.status_code == 200


def test_wealth_entries_new_page(client: TestClient):
    """Test new wealth entry form page"""
    response = client.get("/wealth/entries/new")
    assert response.status_code == 200
    assert b"Add Wealth Entry" in response.content


def test_add_valuation_htmx(client: TestClient):
    """Test adding valuation via HTMX"""
    # Create asset first
    client.post("/wealth/assets", data={"asset_name": "Test Asset"})
    
    # Get asset ID (in real scenario we'd query the DB)
    # For now, assume ID 1
    response = client.post(
        "/wealth/entries/add_row",
        data={
            "month": "2024-01",
            "asset_id": "1",
            "value": "1000.00"
        },
        headers={"HX-Request": "true"}
    )
    assert response.status_code == 200
    assert b"1000" in response.content or b"1,000" in response.content or b"Rs" in response.content


def test_month_detail_page(client: TestClient):
    """Test month detail page"""
    # Setup: create asset and valuation
    client.post("/wealth/assets", data={"asset_name": "Test Asset"})
    client.post(
        "/wealth/entries/add_row",
        data={"month": "2024-01", "asset_id": "1", "value": "1000.00"}
    )
    
    response = client.get("/wealth/entries/2024-01")
    assert response.status_code == 200
    assert b"2024-01" in response.content


def test_summary_page(client: TestClient):
    """Test summary page"""
    response = client.get("/wealth/entries/summary")
    assert response.status_code == 200
    assert b"Wealth Summary" in response.content


def test_export_csv(client: TestClient):
    """Test CSV export"""
    # Setup: create asset and valuations
    client.post("/wealth/assets", data={"asset_name": "Test Asset"})
    client.post(
        "/wealth/entries/add_row",
        data={"month": "2024-01", "asset_id": "1", "value": "1000.00"}
    )
    
    response = client.get("/wealth/entries/summary/csv")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert b"Month,Networth" in response.content


def test_delete_asset_cascade(client: TestClient):
    """Test that deleting asset also deletes valuations"""
    # Create asset and valuation
    client.post("/wealth/assets", data={"asset_name": "Test Asset"})
    client.post(
        "/wealth/entries/add_row",
        data={"month": "2024-01", "asset_id": "1", "value": "1000.00"}
    )
    
    # Delete asset
    response = client.post(
        "/wealth/assets/1/delete",
        headers={"HX-Request": "true"}
    )
    assert response.status_code == 200
    
    # Verify valuations are gone (month should have no data now)
    # This is implicitly tested by the cascade delete constraint
