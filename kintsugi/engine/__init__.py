"""Kintsugi Engine — the living core of autonomous agents.

The engine provides the primitives that make agents feel alive:
  - Pulse: wake → check → act → report → sleep (the heartbeat)
  - Shadow Fork: test modifications in isolation before committing
  - Drift Detection: monitor behavior against ethical baseline
  - Evolution: managed self-modification with verification
"""
from kintsugi.engine.pulse import Pulse, CheckResult, PulseAction, CycleReport
