"""LiveWeb Arena - Real-time web interaction evaluation for LLM browser agents"""

__version__ = "0.1.0"

# Core components
from .core.models import BrowserObservation, BrowserAction, CompositeTask, TrajectoryStep
from .plugins.base import BasePlugin, SubTask, ValidationResult

# Optional browser layer (depends on playwright). Keep submodules usable for
# tooling that doesn't require browser execution (e.g., template registry).
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
