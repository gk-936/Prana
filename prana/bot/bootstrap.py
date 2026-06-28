"""Wires framework components for PRANA's bot at startup."""
from __future__ import annotations

from framework.ai.factory import build_provider
from framework.config.settings import FrameworkSettings
from framework.messaging.registry import MessagingRegistry
from framework.messaging.whatsapp import WhatsAppChannel
from framework.persistence.sqlite import SQLiteUserRepository, SQLiteCheckinRepository
from framework.tools.base import ToolRegistry
from prana.ai_tools.risk import risk_tool
from prana.ai_tools.checkin import record_checkin_tool
from prana.config import DATABASE_URL

settings = FrameworkSettings()


def build_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(risk_tool)
    reg.register(record_checkin_tool)
    return reg


def build_provider_chain():
    return build_provider(settings)


def build_messaging() -> MessagingRegistry:
    reg = MessagingRegistry()
    reg.add(WhatsAppChannel(settings.whatsapp_access_token, settings.whatsapp_phone_number_id))
    return reg


def build_repo() -> SQLiteUserRepository:
    return SQLiteUserRepository(DATABASE_URL)


def build_checkin_repo() -> SQLiteCheckinRepository:
    return SQLiteCheckinRepository(DATABASE_URL)
