"""External evaluation harness for the Music Tagger MVP (Evaluation Plan v0.1).

This package is *outside* the engine and application (CONTRACTS.md §4): it
consumes event logs, hand-check decisions, and safety evidence, and computes
the plan-v0.1 metrics. It never writes audio files and never influences
engine or application behaviour.
"""

__version__ = "0.1.0"
