from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class InviteLog(Base):
    __tablename__ = "invite_logs"

    id = Column(Integer, primary_key=True)
    target = Column(String(255), nullable=False)
    message = Column(String(1000))
    status = Column(String(50), default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    @classmethod
    async def get_by_task_id(cls, task_id: str):
        # This will be implemented with actual database session
        pass

    async def save(self):
        # This will be implemented with actual database session
        pass 