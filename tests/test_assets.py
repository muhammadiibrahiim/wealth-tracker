"""
Tests for asset service and CRUD operations
"""
import pytest
from sqlmodel import Session
from services.assets import AssetService


def test_create_asset(session: Session):
    """Test creating a new asset"""
    asset = AssetService.create_asset(session, user_id=1, name="Test Asset")
    
    assert asset.id is not None
    assert asset.name == "Test Asset"
    assert asset.slug == "test-asset"
    assert asset.user_id == 1


def test_create_duplicate_asset_fails(session: Session):
    """Test that creating duplicate asset (case-insensitive) fails"""
    AssetService.create_asset(session, user_id=1, name="Test Asset")
    
    with pytest.raises(ValueError, match="already exists"):
        AssetService.create_asset(session, user_id=1, name="test asset")
    
    with pytest.raises(ValueError, match="already exists"):
        AssetService.create_asset(session, user_id=1, name="TEST ASSET")


def test_list_assets(session: Session):
    """Test listing assets"""
    AssetService.create_asset(session, user_id=1, name="Asset 1")
    AssetService.create_asset(session, user_id=1, name="Asset 2")
    AssetService.create_asset(session, user_id=2, name="Other User Asset")
    
    assets = AssetService.list_assets(session, user_id=1)
    
    assert len(assets) == 2
    assert assets[0].name == "Asset 1"
    assert assets[1].name == "Asset 2"


def test_list_assets_with_search(session: Session):
    """Test searching assets by name"""
    AssetService.create_asset(session, user_id=1, name="Savings Account")
    AssetService.create_asset(session, user_id=1, name="Investment Portfolio")
    AssetService.create_asset(session, user_id=1, name="Real Estate")
    
    results = AssetService.list_assets(session, user_id=1, query="invest")
    
    assert len(results) == 1
    assert results[0].name == "Investment Portfolio"


def test_rename_asset(session: Session):
    """Test renaming an asset"""
    asset = AssetService.create_asset(session, user_id=1, name="Old Name")
    
    updated = AssetService.rename_asset(session, user_id=1, asset_id=asset.id, new_name="New Name")
    
    assert updated.id == asset.id
    assert updated.name == "New Name"
    assert updated.slug == "new-name"


def test_rename_asset_to_existing_name_fails(session: Session):
    """Test that renaming to existing asset name fails"""
    AssetService.create_asset(session, user_id=1, name="Asset 1")
    asset2 = AssetService.create_asset(session, user_id=1, name="Asset 2")
    
    with pytest.raises(ValueError, match="already exists"):
        AssetService.rename_asset(session, user_id=1, asset_id=asset2.id, new_name="Asset 1")


def test_delete_asset(session: Session):
    """Test deleting an asset"""
    asset = AssetService.create_asset(session, user_id=1, name="Test Asset")
    
    deleted = AssetService.delete_asset(session, user_id=1, asset_id=asset.id)
    
    assert deleted is True
    
    # Verify asset is gone
    assets = AssetService.list_assets(session, user_id=1)
    assert len(assets) == 0


def test_delete_nonexistent_asset(session: Session):
    """Test deleting non-existent asset returns False"""
    deleted = AssetService.delete_asset(session, user_id=1, asset_id=999)
    
    assert deleted is False


def test_asset_uniqueness_per_user(session: Session):
    """Test that asset names are unique per user but not across users"""
    AssetService.create_asset(session, user_id=1, name="Savings")
    AssetService.create_asset(session, user_id=2, name="Savings")  # Should succeed
    
    user1_assets = AssetService.list_assets(session, user_id=1)
    user2_assets = AssetService.list_assets(session, user_id=2)
    
    assert len(user1_assets) == 1
    assert len(user2_assets) == 1
