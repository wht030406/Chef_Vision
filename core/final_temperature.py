import math


def is_valid_temperature(value):
    """Return True when a temperature value can be used for output."""
    if value is None:
        return False
    try:
        return not math.isnan(float(value))
    except (TypeError, ValueError):
        return False


def select_final_temperature(
    sam2_temp,
    ir_temp,
    inverse_temp,
    roi_temp,
    *,
    forward_valid,
    previous_final_temp=None,
):
    """Choose the final temperature from the available strategy outputs."""
    if forward_valid and is_valid_temperature(sam2_temp):
        return {
            "final_temp": float(sam2_temp),
            "source": "sam2_forward",
            "reason": "forward_valid",
        }
    if is_valid_temperature(ir_temp):
        return {
            "final_temp": float(ir_temp),
            "source": "ir",
            "reason": "forward_invalid_or_empty_use_ir",
        }
    if is_valid_temperature(inverse_temp):
        return {
            "final_temp": float(inverse_temp),
            "source": "inverse",
            "reason": "forward_and_ir_invalid_use_inverse",
        }
    if is_valid_temperature(roi_temp):
        return {
            "final_temp": float(roi_temp),
            "source": "roi",
            "reason": "forward_ir_inverse_invalid_use_roi",
        }
    if is_valid_temperature(previous_final_temp):
        return {
            "final_temp": float(previous_final_temp),
            "source": "hold",
            "reason": "all_sources_invalid_hold_previous",
        }
    return {
        "final_temp": float("nan"),
        "source": "none",
        "reason": "all_sources_invalid",
    }
