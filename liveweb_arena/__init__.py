"""LiveWeb Arena - Real-time web interaction evaluation for LLM browser agents"""

__version__ = "0.1.0"

# Core components
from .core.models import BrowserObservation, BrowserAction, CompositeTask, TrajectoryStep
from .plugins.base import BasePlugin, SubTask, ValidationResult

# Optional browser layer (depends on playwright). Keep package importable for
# non-browser utilities (e.g., redteam/reporting) in minimal environments.
try:
    from .core.browser import BrowserEngine, BrowserSession  # type: ignore
except ModuleNotFoundError:
    BrowserEngine = None  # type: ignore
    BrowserSession = None  # type: ignore

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
