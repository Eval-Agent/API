"""
Backwards-compatibility shim.
All symbols have moved to their domain modules.
Import from here or directly from models.rubric / models.paper / models.evaluation.
"""
from models.rubric import *       # noqa: F401, F403
from models.paper import *        # noqa: F401, F403
from models.evaluation import *   # noqa: F401, F403