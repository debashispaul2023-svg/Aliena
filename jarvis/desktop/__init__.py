"""Desktop automation package. Desktop OS only. Fail closed on Termux/Android."""

from jarvis.desktop.automation import DesktopAction, DesktopAutomation
from jarvis.desktop.engine import DesktopAutomationEngine

__all__ = ["DesktopAction", "DesktopAutomation", "DesktopAutomationEngine"]
