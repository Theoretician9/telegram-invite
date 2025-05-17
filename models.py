from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class Account(Base):
    __tablename__ = 'accounts'
    id = Column(Integer, primary_key=True)
    name = Column(String(64), unique=True, nullable=False)
    api_id = Column(String(32), nullable=False)
    api_hash = Column(String(64), nullable=False)
    session_string = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)
    last_used = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    comment = Column(String(255))
    channel_limits = relationship('AccountChannelLimit', back_populates='account')
    invite_logs = relationship('InviteLog', back_populates='account')

class AccountChannelLimit(Base):
    __tablename__ = 'account_channel_limits'
    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=False)
    channel_username = Column(String(128), nullable=False)
    invites_left = Column(Integer, default=200)
    last_invited_at = Column(DateTime)
    account = relationship('Account', back_populates='channel_limits')

class InviteLog(Base):
    __tablename__ = 'invite_logs'
    id = Column(Integer, primary_key=True)
    task_id = Column(String(64))
    account_id = Column(Integer, ForeignKey('accounts.id'))
    channel_username = Column(String(128))
    phone = Column(String(64))
    status = Column(String(32))
    reason = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    account = relationship('Account', back_populates='invite_logs') 