"""
Tests for inline editing in month detail page
"""
import pytest
from decimal import Decimal
from fastapi.testclient import TestClient
from sqlmodel import Session

from main import app
from services.assets import AssetService
from services.wealth import WealthService


@pytest.fixture
def client():
    """Test client fixture"""
    return TestClient(app)


def test_edit_negative_valuation(client: TestClient):
    """Test editing to a negative value (liability)"""
    # Create test data
    client.post("/wealth/assets", data={"asset_name": "Credit Card"})
    client.post(
        "/wealth/entries/add_row",
        data={
            "month": "2024-01",
            "asset_id": "1",
            "value": "0.00"
        },
        headers={"HX-Request": "true"}
    )
    
    # Update to negative value
    response = client.post(
        "/wealth/entries/2024-01/update/1",
        data={"value": "-5000.00"},
        headers={"HX-Request": "true"}
    )
    assert response.status_code == 200
    # Check for negative value (might be formatted with minus or parentheses)
    content = response.content.decode()
    assert "-5000" in content or "-5,000" in content or "(5000)" in content or "(5,000)" in content


def test_edit_nonexistent_asset(client: TestClient):
    """Test editing a non-existent asset returns 404"""
    response = client.get("/wealth/entries/2024-01/edit/999")
    assert response.status_code == 404


def test_delete_asset_valuation(client: TestClient):
    """Test deleting an asset valuation from a month"""
    # Create test data
    client.post("/wealth/assets", data={"asset_name": "Temporary Asset"})
    client.post(
        "/wealth/entries/add_row",
        data={
            "month": "2024-03",
            "asset_id": "1",
            "value": "500.00"
        },
        headers={"HX-Request": "true"}
    )
    
    # Delete the valuation
    response = client.delete(
        "/wealth/entries/2024-03/delete/1",
        headers={"HX-Request": "true"}
    )
    assert response.status_code == 200
    # Response should be empty (removes the row)
    assert response.content == b""


def test_delete_nonexistent_valuation(client: TestClient):
    """Test deleting a non-existent valuation returns error"""
    response = client.delete("/wealth/entries/2024-01/delete/999")
    # Should return 404 or 400 (both are acceptable for not found)
    assert response.status_code in [400, 404]
