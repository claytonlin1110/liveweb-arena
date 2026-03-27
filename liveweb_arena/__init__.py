"""LiveWeb Arena - Real-time web interaction evaluation for LLM browser agents"""

__version__ = "0.1.0"

# Core components
from .core.models import BrowserObservation, BrowserAction, CompositeTask, TrajectoryStep
from .core.browser import BrowserEngine, BrowserSession
from .plugins.base import BasePlugin, SubTask, ValidationResult

__all__ = [
    "__version__",
    # Models
    "BrowserObservation",
    "BrowserAction",
    "CompositeTask",
    "TrajectoryStep",
    # Browser
    "BrowserEngine",
    "BrowserSession",
    # Plugins
    "BasePlugin",
    "SubTask",
    "ValidationResult",
]
