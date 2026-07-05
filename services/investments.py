"""
Investment CRUD service
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional, List
from sqlmodel import Session, select
from models import Investment, InvestmentCadence


class InvestmentService:
    """Service for investment CRUD operations"""
    
    @staticmethod
    def create_investment(
        session: Session,
        user_id: int,
        name: str,
        total_investment_value: Decimal,
        **kwargs
    ) -> Investment:
        """Create a new investment"""
        # Check for duplicate name (case-insensitive)
        existing = session.exec(
            select(Investment)
            .where(Investment.user_id == user_id)
            .where(Investment.name.ilike(name))
        ).first()
        
        if existing:
            raise ValueError(f"Investment '{name}' already exists")
        
        investment = Investment(
            user_id=user_id,
            name=name,
            total_investment_value=total_investment_value,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            **kwargs
        )
        
        session.add(investment)
        session.commit()
        session.refresh(investment)
        
        return investment
    
    @staticmethod
    def get_investment(session: Session, user_id: int, investment_id: int) -> Optional[Investment]:
        """Get investment by ID"""
        return session.exec(
            select(Investment)
            .where(Investment.id == investment_id)
            .where(Investment.user_id == user_id)
        ).first()
    
    @staticmethod
    def list_investments(session: Session, user_id: int) -> List[Investment]:
        """List all investments for user"""
        return session.exec(
            select(Investment)
            .where(Investment.user_id == user_id)
            .order_by(Investment.name)
        ).all()
    
    @staticmethod
    def update_investment(
        session: Session,
        user_id: int,
        investment_id: int,
        **updates
    ) -> Optional[Investment]:
        """Update an investment"""
        investment = InvestmentService.get_investment(session, user_id, investment_id)
        if not investment:
            return None
        
        # Check for name conflict if name is being updated
        if "name" in updates and updates["name"] != investment.name:
            existing = session.exec(
                select(Investment)
                .where(Investment.user_id == user_id)
                .where(Investment.name.ilike(updates["name"]))
                .where(Investment.id != investment_id)
            ).first()
            
            if existing:
                raise ValueError(f"Investment '{updates['name']}' already exists")
        
        # Update fields
        for key, value in updates.items():
            if hasattr(investment, key):
                setattr(investment, key, value)
        
        investment.updated_at = datetime.utcnow()
        
        session.add(investment)
        session.commit()
        session.refresh(investment)
        
        return investment
    
    @staticmethod
    def delete_investment(session: Session, user_id: int, investment_id: int) -> bool:
        """Delete an investment"""
        investment = InvestmentService.get_investment(session, user_id, investment_id)
        if not investment:
            return False
        
        session.delete(investment)
        session.commit()
        
        return True
