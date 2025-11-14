#!/usr/bin/env python3
"""
Calculate Tool (MCP)
====================

Mathematical utilities exposed via MCP FastMCP over stdio.

Tools:
- calculate(expression)
- percentage_calculator(value, percentage, operation="of")
- unit_converter(value, from_unit, to_unit, unit_type="length")

This file follows the same structure and conventions as other tools in
codex-container/MCP (see time-tool.py, tool-recommender.py, etc.).
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, Optional

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("calculate")
logger = logging.getLogger("calculate_mcp")


# ------------------------------
# Helpers
# ------------------------------
_ALLOWED_NAMES: Dict[str, Any] = {
    # Builtins (safe subset)
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "pow": pow,
    # Math module
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "pi": math.pi,
    "e": math.e,
}


def _convert_temperature(value: float, from_unit: str, to_unit: str) -> float:
    """Convert temperature between Celsius, Fahrenheit, and Kelvin."""
    fu = from_unit.strip().lower()
    tu = to_unit.strip().lower()

    # Normalize to Celsius
    if fu in ("fahrenheit", "f"):
        celsius = (value - 32) * 5.0 / 9.0
    elif fu in ("kelvin", "k"):
        celsius = value - 273.15
    elif fu in ("celsius", "c"):
        celsius = value
    else:
        raise ValueError(f"Unknown temperature unit: {from_unit}")

    # Celsius to target
    if tu in ("fahrenheit", "f"):
        return (celsius * 9.0 / 5.0) + 32
    if tu in ("kelvin", "k"):
        return celsius + 273.15
    if tu in ("celsius", "c"):
        return celsius
    raise ValueError(f"Unknown temperature unit: {to_unit}")


# ------------------------------
# Tools
# ------------------------------
@mcp.tool()
async def calculate(expression: str) -> Dict[str, Any]:
    """Perform basic arithmetic calculations safely.

    Allows: + - * / ** % // parentheses, and common math functions
    from a restricted environment. Example inputs: "25 * 31",
    "sqrt(16) + 5", "sin(pi/2)".
    """
    try:
        expr = (expression or "").strip()
        if not expr:
            return {"success": False, "error": "Empty expression"}

        result = eval(expr, {"__builtins__": {}}, _ALLOWED_NAMES)
        logger.info("Calculated: %s = %s", expr, result)
        return {
            "success": True,
            "expression": expr,
            "result": result,
            "result_type": type(result).__name__,
        }
    except Exception as e:  # pragma: no cover
        logger.error("Error calculating '%s': %s", expression, e)
        return {
            "success": False,
            "expression": expression,
            "error": str(e),
            "error_type": type(e).__name__,
        }


@mcp.tool()
async def percentage_calculator(
    value: float,
    percentage: float,
    operation: str = "of",
) -> Dict[str, Any]:
    """Calculate percentages with different operations.

    operation: one of "of", "increase", "decrease", "change".
    - of: X% of Y
    - increase: Y increased by X%
    - decrease: Y decreased by X%
    - change: percentage change from value→percentage
    """
    try:
        op = (operation or "of").strip().lower()
        if op == "of":
            result = (percentage / 100.0) * value
            description = f"{percentage}% of {value}"
        elif op == "increase":
            result = value * (1.0 + percentage / 100.0)
            description = f"{value} increased by {percentage}%"
        elif op == "decrease":
            result = value * (1.0 - percentage / 100.0)
            description = f"{value} decreased by {percentage}%"
        elif op == "change":
            if value == 0:
                return {"success": False, "error": "Cannot calculate percentage change from zero"}
            result = ((percentage - value) / value) * 100.0
            description = f"Percentage change from {value} to {percentage}"
        else:
            return {
                "success": False,
                "error": "Unknown operation. Use 'of', 'increase', 'decrease', or 'change'",
            }

        logger.info("Percentage: %s = %s", description, result)
        return {
            "success": True,
            "operation": op,
            "input_value": value,
            "percentage": percentage,
            "result": result,
            "description": description,
        }
    except Exception as e:  # pragma: no cover
        logger.error("Error in percentage calculation: %s", e)
        return {
            "success": False,
            "error": str(e),
            "operation": operation,
            "input_value": value,
            "percentage": percentage,
        }


@mcp.tool()
async def unit_converter(
    value: float,
    from_unit: str,
    to_unit: str,
    unit_type: str = "length",
) -> Dict[str, Any]:
    """Convert between units of measurement.

    unit_type: one of "length", "weight", "volume", "temperature".
    """
    try:
        utype = (unit_type or "length").strip().lower()
        if utype == "temperature":
            result = _convert_temperature(value, from_unit, to_unit)
            desc = f"{value} {from_unit} = {result} {to_unit}"
            return {
                "success": True,
                "original_value": value,
                "from_unit": from_unit,
                "to_unit": to_unit,
                "unit_type": utype,
                "result": result,
                "description": desc,
            }

        conversions = {
            "length": {
                "base": "meters",
                "factors": {
                    "mm": 0.001,
                    "millimeters": 0.001,
                    "cm": 0.01,
                    "centimeters": 0.01,
                    "m": 1.0,
                    "meters": 1.0,
                    "km": 1000.0,
                    "kilometers": 1000.0,
                    "in": 0.0254,
                    "inches": 0.0254,
                    "ft": 0.3048,
                    "feet": 0.3048,
                    "yd": 0.9144,
                    "yards": 0.9144,
                    "mi": 1609.34,
                    "miles": 1609.34,
                },
            },
            "weight": {
                "base": "grams",
                "factors": {
                    "mg": 0.001,
                    "milligrams": 0.001,
                    "g": 1.0,
                    "grams": 1.0,
                    "kg": 1000.0,
                    "kilograms": 1000.0,
                    "oz": 28.3495,
                    "ounces": 28.3495,
                    "lb": 453.592,
                    "pounds": 453.592,
                },
            },
            "volume": {
                "base": "liters",
                "factors": {
                    "ml": 0.001,
                    "milliliters": 0.001,
                    "l": 1.0,
                    "liters": 1.0,
                    "gal": 3.78541,
                    "gallons": 3.78541,
                    "qt": 0.946353,
                    "quarts": 0.946353,
                    "pt": 0.473176,
                    "pints": 0.473176,
                    "cup": 0.236588,
                    "cups": 0.236588,
                    "fl_oz": 0.0295735,
                    "fluid_ounces": 0.0295735,
                },
            },
        }

        if utype not in conversions:
            return {"success": False, "error": f"Unsupported unit type: {unit_type}"}

        conv = conversions[utype]
        f = conv["factors"].get(from_unit.strip().lower())
        t = conv["factors"].get(to_unit.strip().lower())
        if f is None:
            return {"success": False, "error": f"Unknown {utype} unit: {from_unit}"}
        if t is None:
            return {"success": False, "error": f"Unknown {utype} unit: {to_unit}"}

        base_value = value * f
        result = base_value / t
        desc = f"{value} {from_unit} = {result} {to_unit}"
        logger.info("Unit conversion: %s", desc)
        return {
            "success": True,
            "original_value": value,
            "from_unit": from_unit,
            "to_unit": to_unit,
            "unit_type": utype,
            "result": result,
            "description": desc,
        }
    except Exception as e:  # pragma: no cover
        logger.error("Error in unit conversion: %s", e)
        return {
            "success": False,
            "error": str(e),
            "original_value": value,
            "from_unit": from_unit,
            "to_unit": to_unit,
            "unit_type": unit_type,
        }


if __name__ == "__main__":
    mcp.run(transport="stdio")
