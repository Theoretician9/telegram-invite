from sqlalchemy import Column, String, Integer, DateTime, JSON
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class InviteLog(Base):
    __tablename__ = "invite_logs"

    id = Column(Integer, primary_key=True)
    task_id = Column(String(36), unique=True, nullable=False)
    target = Column(String(255), nullable=False)
    message = Column(String(4096), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    progress = Column(Integer, default=0)
    total = Column(Integer, default=0)
    success = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    error = Column(String(1024))
    metadata = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    async def get_by_task_id(cls, task_id: str):
        # This will be implemented with actual database session
        pass

    async def save(self):
        # This will be implemented with actual database session
        pass 