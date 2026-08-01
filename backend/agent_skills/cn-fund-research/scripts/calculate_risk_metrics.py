"""CLI wrapper for the complete deterministic risk metric set."""
from fund_research.metrics import calculate_metrics_cli


if __name__ == "__main__":
    calculate_metrics_cli(metric_group="all")
