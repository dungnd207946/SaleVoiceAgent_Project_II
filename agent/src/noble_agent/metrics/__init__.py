"""Metrics package — in-session latency collection.

Usage:
  from noble_agent.metrics import MetricsCollector, Timer
"""

from noble_agent.metrics.collector import LatencyRecord, MetricsCollector, Timer

__all__ = ["MetricsCollector", "Timer", "LatencyRecord"]
