"""
Service layer for Atomic Habits tracking
"""
from datetime import date, timedelta, datetime
from typing import Optional, List
from sqlmodel import Session, select, func, and_, col
from collections import defaultdict

from models import LifeAspect, Habit, HabitLog


class HabitsService:
    """Service for managing life aspects, habits, and daily logs"""
    
    # ─── Life Aspects CRUD ───────────────────────────────────────
    
    @staticmethod
    def list_aspects(session: Session, user_id: int) -> list[LifeAspect]:
        """List all life aspects for a user, ordered by sort_order"""
        return list(session.exec(
            select(LifeAspect)
            .where(LifeAspect.user_id == user_id)
            .order_by(LifeAspect.sort_order, LifeAspect.name)
        ).all())
    
    @staticmethod
    def get_aspect(session: Session, user_id: int, aspect_id: int) -> Optional[LifeAspect]:
        """Get a single life aspect"""
        return session.exec(
            select(LifeAspect)
            .where(LifeAspect.user_id == user_id)
            .where(LifeAspect.id == aspect_id)
        ).first()
    
    @staticmethod
    def create_aspect(session: Session, user_id: int, name: str, icon: str = "📌", color: str = "#3B82F6", sort_order: int = 0) -> LifeAspect:
        """Create a new life aspect"""
        aspect = LifeAspect(
            user_id=user_id,
            name=name,
            icon=icon,
            color=color,
            sort_order=sort_order
        )
        session.add(aspect)
        session.commit()
        session.refresh(aspect)
        return aspect
    
    @staticmethod
    def update_aspect(session: Session, user_id: int, aspect_id: int, **kwargs) -> Optional[LifeAspect]:
        """Update a life aspect"""
        aspect = HabitsService.get_aspect(session, user_id, aspect_id)
        if not aspect:
            return None
        for key, value in kwargs.items():
            if hasattr(aspect, key):
                setattr(aspect, key, value)
        aspect.updated_at = datetime.utcnow()
        session.add(aspect)
        session.commit()
        session.refresh(aspect)
        return aspect
    
    @staticmethod
    def delete_aspect(session: Session, user_id: int, aspect_id: int) -> bool:
        """Delete a life aspect and all its habits"""
        aspect = HabitsService.get_aspect(session, user_id, aspect_id)
        if not aspect:
            return False
        session.delete(aspect)
        session.commit()
        return True
    
    # ─── Habits CRUD ─────────────────────────────────────────────
    
    @staticmethod
    def list_habits(session: Session, user_id: int, aspect_id: Optional[int] = None, active_only: bool = True) -> list[Habit]:
        """List habits, optionally filtered by aspect"""
        stmt = select(Habit).where(Habit.user_id == user_id)
        if aspect_id is not None:
            stmt = stmt.where(Habit.aspect_id == aspect_id)
        if active_only:
            stmt = stmt.where(Habit.is_active == True)
        stmt = stmt.order_by(Habit.aspect_id, Habit.name)
        return list(session.exec(stmt).all())
    
    @staticmethod
    def get_habit(session: Session, user_id: int, habit_id: int) -> Optional[Habit]:
        """Get a single habit"""
        return session.exec(
            select(Habit)
            .where(Habit.user_id == user_id)
            .where(Habit.id == habit_id)
        ).first()
    
    @staticmethod
    def create_habit(session: Session, user_id: int, aspect_id: int, name: str,
                     description: str = None, is_recurring: bool = True,
                     target_per_week: int = 7) -> Habit:
        """Create a new habit"""
        habit = Habit(
            user_id=user_id,
            aspect_id=aspect_id,
            name=name,
            description=description,
            is_recurring=is_recurring,
            target_per_week=target_per_week
        )
        session.add(habit)
        session.commit()
        session.refresh(habit)
        return habit
    
    @staticmethod
    def update_habit(session: Session, user_id: int, habit_id: int, **kwargs) -> Optional[Habit]:
        """Update a habit"""
        habit = HabitsService.get_habit(session, user_id, habit_id)
        if not habit:
            return None
        for key, value in kwargs.items():
            if hasattr(habit, key):
                setattr(habit, key, value)
        habit.updated_at = datetime.utcnow()
        session.add(habit)
        session.commit()
        session.refresh(habit)
        return habit
    
    @staticmethod
    def delete_habit(session: Session, user_id: int, habit_id: int) -> bool:
        """Delete a habit and all its logs"""
        habit = HabitsService.get_habit(session, user_id, habit_id)
        if not habit:
            return False
        session.delete(habit)
        session.commit()
        return True
    
    # ─── Habit Logs ──────────────────────────────────────────────
    
    @staticmethod
    def toggle_habit(session: Session, user_id: int, habit_id: int, log_date: date) -> dict:
        """Toggle a habit for a specific date. Returns the new state."""
        existing = session.exec(
            select(HabitLog)
            .where(HabitLog.user_id == user_id)
            .where(HabitLog.habit_id == habit_id)
            .where(HabitLog.log_date == log_date)
        ).first()
        
        if existing:
            session.delete(existing)
            session.commit()
            return {"completed": False, "log_id": None}
        else:
            log = HabitLog(
                user_id=user_id,
                habit_id=habit_id,
                log_date=log_date,
                completed=True
            )
            session.add(log)
            session.commit()
            session.refresh(log)
            return {"completed": True, "log_id": log.id}
    
    @staticmethod
    def get_logs_for_date(session: Session, user_id: int, log_date: date) -> dict[int, HabitLog]:
        """Get all habit logs for a specific date, keyed by habit_id"""
        logs = session.exec(
            select(HabitLog)
            .where(HabitLog.user_id == user_id)
            .where(HabitLog.log_date == log_date)
        ).all()
        return {log.habit_id: log for log in logs}
    
    # ─── Daily View ──────────────────────────────────────────────
    
    @staticmethod
    def get_daily_view(session: Session, user_id: int, view_date: date) -> dict:
        """
        Get the full daily view data: aspects -> habits -> completion status
        """
        aspects = HabitsService.list_aspects(session, user_id)
        habits = HabitsService.list_habits(session, user_id, active_only=True)
        logs = HabitsService.get_logs_for_date(session, user_id, view_date)
        
        # Group habits by aspect
        habits_by_aspect = defaultdict(list)
        for habit in habits:
            # For one-off tasks, only show them on the date they were created or logged
            if not habit.is_recurring:
                # Show one-off tasks that were created today or have a log for today
                created_date = habit.created_at.date() if habit.created_at else None
                if created_date != view_date and habit.id not in logs:
                    continue
            
            habits_by_aspect[habit.aspect_id].append({
                "habit": habit,
                "completed": habit.id in logs,
                "log": logs.get(habit.id)
            })
        
        # Build the daily view with scores
        total_habits = 0
        total_completed = 0
        aspect_views = []
        
        for aspect in aspects:
            aspect_habits = habits_by_aspect.get(aspect.id, [])
            completed_count = sum(1 for h in aspect_habits if h["completed"])
            aspect_total = len(aspect_habits)
            total_habits += aspect_total
            total_completed += completed_count
            
            aspect_views.append({
                "aspect": aspect,
                "habits": aspect_habits,
                "completed_count": completed_count,
                "total_count": aspect_total,
                "score": round((completed_count / aspect_total * 100) if aspect_total > 0 else 0, 1)
            })
        
        daily_score = round((total_completed / total_habits * 100) if total_habits > 0 else 0, 1)
        
        return {
            "date": view_date,
            "aspects": aspect_views,
            "total_habits": total_habits,
            "total_completed": total_completed,
            "daily_score": daily_score
        }
    
    # ─── Streaks ─────────────────────────────────────────────────
    
    @staticmethod
    def get_streak(session: Session, user_id: int, habit_id: int, as_of: date = None) -> dict:
        """Calculate current and longest streak for a habit"""
        if as_of is None:
            as_of = date.today()
        
        # Get all completed log dates for this habit, sorted descending
        logs = session.exec(
            select(HabitLog.log_date)
            .where(HabitLog.user_id == user_id)
            .where(HabitLog.habit_id == habit_id)
            .where(HabitLog.completed == True)
            .order_by(HabitLog.log_date.desc())
        ).all()
        
        if not logs:
            return {"current_streak": 0, "longest_streak": 0, "total_completions": 0}
        
        log_dates = set(logs)
        
        # Current streak: count consecutive days backwards from as_of
        current_streak = 0
        check_date = as_of
        while check_date in log_dates:
            current_streak += 1
            check_date -= timedelta(days=1)
        
        # Longest streak
        sorted_dates = sorted(log_dates)
        longest_streak = 0
        streak = 1
        for i in range(1, len(sorted_dates)):
            if sorted_dates[i] - sorted_dates[i-1] == timedelta(days=1):
                streak += 1
            else:
                longest_streak = max(longest_streak, streak)
                streak = 1
        longest_streak = max(longest_streak, streak)
        
        return {
            "current_streak": current_streak,
            "longest_streak": longest_streak,
            "total_completions": len(log_dates)
        }
    
    # ─── Weekly Summary ──────────────────────────────────────────
    
    @staticmethod
    def get_weekly_summary(session: Session, user_id: int, week_start: date = None) -> dict:
        """Get summary for a week (Mon-Sun)"""
        if week_start is None:
            today = date.today()
            week_start = today - timedelta(days=today.weekday())  # Monday
        
        week_end = week_start + timedelta(days=6)
        
        habits = HabitsService.list_habits(session, user_id, active_only=True)
        
        # Get logs for the entire week
        logs = session.exec(
            select(HabitLog)
            .where(HabitLog.user_id == user_id)
            .where(HabitLog.log_date >= week_start)
            .where(HabitLog.log_date <= week_end)
            .where(HabitLog.completed == True)
        ).all()
        
        # Count completions per habit
        completions_per_habit = defaultdict(int)
        for log in logs:
            completions_per_habit[log.habit_id] += 1
        
        # Build habit summaries
        habit_summaries = []
        total_target = 0
        total_actual = 0
        
        for habit in habits:
            if not habit.is_recurring:
                continue
            actual = completions_per_habit.get(habit.id, 0)
            target = habit.target_per_week
            total_target += target
            total_actual += actual
            
            habit_summaries.append({
                "habit": habit,
                "target": target,
                "actual": actual,
                "met": actual >= target,
                "progress_pct": round(min((actual / target * 100) if target > 0 else 0, 100), 1)
            })
        
        return {
            "week_start": week_start,
            "week_end": week_end,
            "habits": habit_summaries,
            "total_target": total_target,
            "total_actual": total_actual,
            "overall_pct": round((total_actual / total_target * 100) if total_target > 0 else 0, 1)
        }
    
    # ─── Heatmap Data ────────────────────────────────────────────
    
    @staticmethod
    def get_heatmap_data(session: Session, user_id: int, months: int = 6) -> dict:
        """
        Get daily completion rate for the heatmap, last N months.
        Returns dict of date -> score (0-100).
        """
        today = date.today()
        start_date = today - timedelta(days=months * 30)
        
        # Get total active habits count over time (approximate: current count)
        habits = HabitsService.list_habits(session, user_id, active_only=True)
        recurring_habits = [h for h in habits if h.is_recurring]
        total_habits = len(recurring_habits)
        
        if total_habits == 0:
            return {"start_date": start_date, "end_date": today, "data": {}}
        
        # Get all logs in range
        logs = session.exec(
            select(HabitLog.log_date, func.count(HabitLog.id))
            .where(HabitLog.user_id == user_id)
            .where(HabitLog.log_date >= start_date)
            .where(HabitLog.completed == True)
            .group_by(HabitLog.log_date)
        ).all()
        
        data = {}
        for log_date, count in logs:
            score = round(min((count / total_habits * 100), 100), 1)
            data[log_date.isoformat()] = score
        
        return {
            "start_date": start_date,
            "end_date": today,
            "data": data,
            "total_habits": total_habits
        }
    
    # ─── Progress Chart Data ─────────────────────────────────────
    
    @staticmethod
    def get_progress_chart_data(session: Session, user_id: int, days: int = 30) -> dict:
        """
        Get daily scores for the last N days for a line chart.
        """
        today = date.today()
        start_date = today - timedelta(days=days - 1)
        
        habits = HabitsService.list_habits(session, user_id, active_only=True)
        recurring_habits = [h for h in habits if h.is_recurring]
        total_habits = len(recurring_habits)
        
        # Get all logs in range
        logs = session.exec(
            select(HabitLog.log_date, func.count(HabitLog.id))
            .where(HabitLog.user_id == user_id)
            .where(HabitLog.log_date >= start_date)
            .where(HabitLog.completed == True)
            .group_by(HabitLog.log_date)
        ).all()
        
        log_counts = {log_date: count for log_date, count in logs}
        
        labels = []
        scores = []
        current = start_date
        while current <= today:
            labels.append(current.strftime("%b %d"))
            count = log_counts.get(current, 0)
            score = round((count / total_habits * 100) if total_habits > 0 else 0, 1)
            scores.append(score)
            current += timedelta(days=1)
        
        return {
            "labels": labels,
            "scores": scores
        }
    
    # ─── Overall Habit Score ─────────────────────────────────────
    
    @staticmethod
    def get_overall_score(session: Session, user_id: int, days: int = 30) -> dict:
        """
        Calculate an overall habit score over the last N days.
        Score = (total completions) / (total possible completions) * 100
        """
        today = date.today()
        start_date = today - timedelta(days=days - 1)
        
        habits = HabitsService.list_habits(session, user_id, active_only=True)
        recurring_habits = [h for h in habits if h.is_recurring]
        
        if not recurring_habits:
            return {"score": 0, "total_possible": 0, "total_actual": 0, "days": days}
        
        # Total possible = sum(target_per_week / 7 * days) for each habits
        total_possible = 0
        for habit in recurring_habits:
            total_possible += round(habit.target_per_week / 7 * days)
        
        # Total actual completions in range
        habit_ids = [h.id for h in recurring_habits]
        total_actual = session.exec(
            select(func.count(HabitLog.id))
            .where(HabitLog.user_id == user_id)
            .where(col(HabitLog.habit_id).in_(habit_ids))
            .where(HabitLog.log_date >= start_date)
            .where(HabitLog.completed == True)
        ).one()
        
        score = round((total_actual / total_possible * 100) if total_possible > 0 else 0, 1)
        
        return {
            "score": score,
            "total_possible": total_possible,
            "total_actual": total_actual,
            "days": days
        }
    
    # ─── Seed Default Aspects ────────────────────────────────────
    
    @staticmethod
    def seed_defaults(session: Session, user_id: int) -> list[LifeAspect]:
        """
        Create default life aspects if none exist.
        Returns list of created aspects.
        """
        existing = HabitsService.list_aspects(session, user_id)
        if existing:
            return existing
        
        defaults = [
            {"name": "Business", "icon": "💼", "color": "#3B82F6", "sort_order": 1},
            {"name": "Self Development", "icon": "📚", "color": "#8B5CF6", "sort_order": 2},
            {"name": "Deen", "icon": "🕌", "color": "#10B981", "sort_order": 3},
            {"name": "Health", "icon": "💪", "color": "#EF4444", "sort_order": 4},
        ]
        
        created = []
        for d in defaults:
            aspect = HabitsService.create_aspect(session, user_id, **d)
            created.append(aspect)
        
        return created
