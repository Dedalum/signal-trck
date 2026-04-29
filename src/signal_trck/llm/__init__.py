"""Provider-agnostic LLM wrapper using the ``instructor`` library.

The grounding mechanism (``candidate_id`` selection + server-side validation)
is **provider-independent** — see plan §"AI grounding strategy". Validation
happens regardless of provider's native structured-output guarantees.
"""

from signal_trck.llm.analysis import (
    AIAnchor,
    AIDrawing,
    ChartAnalysis,
    GroundingError,
)
from signal_trck.llm.client import (
    DEFAULT_MODELS,
    SUPPORTED_PROVIDERS,
    LLMClient,
    Provider,
    build_client,
    resolve_model,
)
from signal_trck.llm.pipeline import (
    AnalysisResult,
    PipelineError,
    analyze_chart,
)

__all__ = [
    "DEFAULT_MODELS",
    "SUPPORTED_PROVIDERS",
    "AIAnchor",
    "AIDrawing",
    "AnalysisResult",
    "ChartAnalysis",
    "GroundingError",
    "LLMClient",
    "PipelineError",
    "Provider",
    "analyze_chart",
    "build_client",
    "resolve_model",
]
