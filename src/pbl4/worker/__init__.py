"""Worker — distributed training worker process.

Reference: Canonical Worker Architecture (Google Drive)

Workers perform:
- forward pass
- loss computation
- backward pass
- gradient export
- send gradient to Runtime via DTP/1
- receive updated parameters from Runtime via DTP/1
- load parameters

Workers do NOT call optimizer.step() on the canonical distributed model.
Logical worker rank is assigned by Runtime during registration.
Worker-0 connects using the exact same DTP/1 TCP path as all other workers.

Console entrypoint: pbl4.worker.entrypoint:main
"""

from __future__ import annotations
