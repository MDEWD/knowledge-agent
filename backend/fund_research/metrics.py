"""Deterministic risk/return metrics; no LLM arithmetic is allowed here."""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from typing import Any, Iterable


def normalize_series(rows: Iterable[dict[str, Any]]) -> list[tuple[str, float]]:
    by_date: dict[str, float] = {}
    for row in rows:
        date = str(row.get("date", "")).replace("-", "")
        try:
            value = float(row.get("value"))
        except (TypeError, ValueError):
            continue
        if date and math.isfinite(value) and value > 0:
            by_date[date] = value
    return sorted(by_date.items())


def calculate_fund_metrics(
    fund_rows: Iterable[dict[str, Any]],
    benchmark_rows: Iterable[dict[str, Any]] | None = None,
    *,
    annual_risk_free_rate: float = 0.015,
) -> dict[str, Any]:
    fund = normalize_series(fund_rows)
    if len(fund) < 2:
        raise ValueError("at least two valid fund observations are required")

    dates = [date for date, _ in fund]
    values = [value for _, value in fund]
    returns = [right / left - 1 for left, right in zip(values, values[1:])]
    periods = len(returns)
    cumulative = values[-1] / values[0] - 1
    annualized = (1 + cumulative) ** (252 / periods) - 1
    volatility = statistics.stdev(returns) * math.sqrt(252) if len(returns) > 1 else 0.0
    sharpe = (annualized - annual_risk_free_rate) / volatility if volatility > 0 else None
    daily_rf = (1 + annual_risk_free_rate) ** (1 / 252) - 1
    downside = [min(item - daily_rf, 0.0) for item in returns]
    downside_dev = math.sqrt(sum(item * item for item in downside) / len(downside))
    sortino = (
        (statistics.mean(returns) - daily_rf) / downside_dev * math.sqrt(252)
        if downside_dev > 0 else None
    )
    drawdown = _max_drawdown(fund)
    trailing = {
        label: _trailing_return(values, sessions)
        for label, sessions in (("1m", 21), ("3m", 63), ("6m", 126), ("1y", 252))
    }

    result: dict[str, Any] = {
        "observation_count": len(fund),
        "start_date": dates[0],
        "end_date": dates[-1],
        "cumulative_return": cumulative,
        "annualized_return": annualized,
        "annualized_volatility": volatility,
        "max_drawdown": drawdown["max_drawdown"],
        "max_drawdown_peak_date": drawdown["peak_date"],
        "max_drawdown_trough_date": drawdown["trough_date"],
        "max_drawdown_recovery_date": drawdown["recovery_date"],
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "annual_risk_free_rate": annual_risk_free_rate,
        "trailing_returns": trailing,
    }

    benchmark = normalize_series(benchmark_rows or [])
    if benchmark:
        fund_map = dict(fund)
        benchmark_map = dict(benchmark)
        common = sorted(set(fund_map) & set(benchmark_map))
        if len(common) >= 2:
            fund_aligned = [fund_map[date] for date in common]
            benchmark_aligned = [benchmark_map[date] for date in common]
            fund_return = fund_aligned[-1] / fund_aligned[0] - 1
            benchmark_return = benchmark_aligned[-1] / benchmark_aligned[0] - 1
            result["benchmark"] = {
                "observation_count": len(common),
                "aligned_start_date": common[0],
                "aligned_end_date": common[-1],
                "fund_cumulative_return": fund_return,
                "benchmark_cumulative_return": benchmark_return,
                "excess_return": fund_return - benchmark_return,
            }
        else:
            result["benchmark"] = {"error": "fewer than two aligned observations"}
    return _round_numbers(result)


def _trailing_return(values: list[float], sessions: int) -> float | None:
    if len(values) <= sessions:
        return None
    return values[-1] / values[-sessions - 1] - 1


def _max_drawdown(series: list[tuple[str, float]]) -> dict[str, Any]:
    peak_value = series[0][1]
    peak_date = series[0][0]
    worst = 0.0
    worst_peak_date = peak_date
    trough_date = peak_date
    trough_index = 0
    for index, (date, value) in enumerate(series):
        if value > peak_value:
            peak_value = value
            peak_date = date
        drawdown = value / peak_value - 1
        if drawdown < worst:
            worst = drawdown
            worst_peak_date = peak_date
            trough_date = date
            trough_index = index
    recovery_date = None
    peak_target = dict(series).get(worst_peak_date)
    if peak_target is not None:
        for date, value in series[trough_index + 1:]:
            if value >= peak_target:
                recovery_date = date
                break
    return {
        "max_drawdown": worst,
        "peak_date": worst_peak_date,
        "trough_date": trough_date,
        "recovery_date": recovery_date,
    }


def _round_numbers(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 8) if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _round_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_round_numbers(item) for item in value]
    return value


def calculate_metrics_cli(metric_group: str = "all") -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", help="JSON file; stdin is used when omitted")
    parser.add_argument("--risk-free-rate", type=float, default=0.015)
    args = parser.parse_args()
    raw = open(args.input, encoding="utf-8").read() if args.input else sys.stdin.read()
    payload = json.loads(raw)
    result = calculate_fund_metrics(
        payload.get("fund", []), payload.get("benchmark", []),
        annual_risk_free_rate=args.risk_free_rate,
    )
    if metric_group == "returns":
        keys = {"cumulative_return", "annualized_return", "trailing_returns", "benchmark"}
        result = {key: value for key, value in result.items() if key in keys}
    elif metric_group == "drawdown":
        keys = {key for key in result if "drawdown" in key}
        result = {key: value for key, value in result.items() if key in keys}
    print(json.dumps(result, ensure_ascii=False, indent=2))


__all__ = ["calculate_fund_metrics", "calculate_metrics_cli", "normalize_series"]
