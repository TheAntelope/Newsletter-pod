"""Broadcast-loop workstream: machine-generated podcasts posted to X.

Phase 0 = generate-once endpoint that produces audio + waveform video to GCS
from a hand-written topic brief. No X posting, no scheduler, no feedback
ingestion yet — those layer on top as later phases.
"""
