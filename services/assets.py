"""
Service layer for asset management
"""
from datetime import datetime
from typing import Optional
from sqlmodel import Session, select, or_
from models import Asset
from utils import normalize_slug


class AssetService:
    """Service class for asset operations"""
    
    @staticmethod
    def create_asset(session: Session, user_id: int, name: str) -> Asset:
        """
        Create a new asset for the user
        
        Args:
            session: Database session
            user_id: User ID
            name: Asset name
            
        Returns:
            Created Asset object
            
        Raises:
            ValueError: If asset name already exists (case-insensitive)
        """
        slug = normalize_slug(name)
        
        # Check for duplicate slug for this user
        existing = session.exec(
            select(Asset)
            .where(Asset.user_id == user_id)
            .where(Asset.slug == slug)
        ).first()
        
        if existing:
            raise ValueError(f"Asset '{name}' already exists for this user")
        
        asset = Asset(
            user_id=user_id,
            name=name.strip(),
            slug=slug,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        session.add(asset)
        session.commit()
        session.refresh(asset)
        
        return asset
    
    @staticmethod
    def list_assets(session: Session, user_id: int, query: Optional[str] = None) -> list[Asset]:
        """
        List all assets for a user, optionally filtered by search query
        
        Args:
            session: Database session
            user_id: User ID
            query: Optional search string to filter by name
            
        Returns:
            List of Asset objects
        """
        statement = select(Asset).where(Asset.user_id == user_id)
        
        if query:
            search_term = f"%{query.lower()}%"
            statement = statement.where(
                or_(
                    Asset.name.ilike(search_term),
                    Asset.slug.ilike(search_term)
                )
            )
        
        statement = statement.order_by(Asset.name)
        assets = session.exec(statement).all()
        
        return list(assets)
    
    @staticmethod
    def get_asset(session: Session, user_id: int, asset_id: int) -> Optional[Asset]:
        """
        Get a specific asset by ID
        
        Args:
            session: Database session
            user_id: User ID
            asset_id: Asset ID
            
        Returns:
            Asset object or None if not found
        """
        asset = session.exec(
            select(Asset)
            .where(Asset.id == asset_id)
            .where(Asset.user_id == user_id)
        ).first()
        
        return asset
    
    @staticmethod
    def rename_asset(session: Session, user_id: int, asset_id: int, new_name: str) -> Asset:
        """
        Rename an existing asset
        
        Args:
            session: Database session
            user_id: User ID
            asset_id: Asset ID
            new_name: New asset name
            
        Returns:
            Updated Asset object
            
        Raises:
            ValueError: If asset not found or new name conflicts with existing asset
        """
        asset = AssetService.get_asset(session, user_id, asset_id)
        
        if not asset:
            raise ValueError(f"Asset with ID {asset_id} not found")
        
        new_slug = normalize_slug(new_name)
        
        # Check if new slug conflicts with another asset
        if new_slug != asset.slug:
            existing = session.exec(
                select(Asset)
                .where(Asset.user_id == user_id)
                .where(Asset.slug == new_slug)
                .where(Asset.id != asset_id)
            ).first()
            
            if existing:
                raise ValueError(f"Asset '{new_name}' already exists for this user")
        
        asset.name = new_name.strip()
        asset.slug = new_slug
        asset.updated_at = datetime.utcnow()
        
        session.add(asset)
        session.commit()
        session.refresh(asset)
        
        return asset
    
    @staticmethod
    def delete_asset(session: Session, user_id: int, asset_id: int) -> bool:
        """
        Delete an asset (hard delete with cascade to valuations)
        
        Args:
            session: Database session
            user_id: User ID
            asset_id: Asset ID
            
        Returns:
            True if deleted, False if not found
        """
        asset = AssetService.get_asset(session, user_id, asset_id)
        
        if not asset:
            return False
        
        session.delete(asset)
        session.commit()
        
        return True
