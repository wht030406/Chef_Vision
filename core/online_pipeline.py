"""
Online temperature pipeline interface stub.

This module is intentionally disabled by default. It documents the near-real-time
entry point shape without changing the current offline TrackFood.py pipeline.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

try:
    import final_temperature as _final_temperature
except ImportError:  # pragma: no cover - supports package-style imports.
    from . import final_temperature as _final_temperature


ENABLE_ONLINE_PIPELINE_STUB = False


@dataclass
class OnlineTemperaturePipeline:
    """Minimal stateful shell for a future near-real-time temperature pipeline."""

    enabled: bool = ENABLE_ONLINE_PIPELINE_STUB
    last_final_temp: float = float("nan")
    frame_index: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def process_frame(self, rgb_frame, ir_frame, timestamp_s: Optional[float] = None):
        """
        Placeholder frame-level API.

        The current project still uses the offline chunk-based SAM2 pipeline.
        This method exists only to define the future online interface shape.
        """
        return {
            "enabled": self.enabled,
            "status": "disabled" if not self.enabled else "not_implemented",
            "frame_index": self.frame_index,
            "timestamp_s": timestamp_s,
            "final_temp": float("nan"),
            "source": "none",
            "reason": "online_pipeline_stub_only",
            "mask": None,
        }

    def process_temperature_candidates(
        self,
        *,
        sam2_temp,
        ir_temp,
        inverse_temp,
        roi_temp,
        forward_valid,
        timestamp_s: Optional[float] = None,
    ):
        """
        Standardize final-temperature output from already computed candidates.

        This helper reuses the same final-temperature decision rule as the
        offline pipeline, but it is not called unless a future caller imports
        and uses this stub explicitly.
        """
        if not self.enabled:
            return {
                "enabled": False,
                "status": "disabled",
                "frame_index": self.frame_index,
                "timestamp_s": timestamp_s,
                "final_temp": float("nan"),
                "source": "none",
                "reason": "online_pipeline_disabled",
            }

        decision = _final_temperature.select_final_temperature(
            sam2_temp,
            ir_temp,
            inverse_temp,
            roi_temp,
            forward_valid=forward_valid,
            previous_final_temp=self.last_final_temp,
        )
        self.frame_index += 1
        if _final_temperature.is_valid_temperature(decision["final_temp"]):
            self.last_final_temp = decision["final_temp"]
        return {
            "enabled": True,
            "status": "ok",
            "frame_index": self.frame_index - 1,
            "timestamp_s": timestamp_s,
            **decision,
        }
