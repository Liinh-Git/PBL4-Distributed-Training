"""Synchronization subpackage — strategy pattern for training sync.

Owns admission/update-ready decisions but NOT:
- Checkpoint cadence (that's CheckpointPolicy)
- Transport handling
- Model writes
"""
