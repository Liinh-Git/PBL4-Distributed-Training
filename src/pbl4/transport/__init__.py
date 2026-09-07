"""TCP transport layer.

Generic TCP connection and exact-byte I/O primitives.
Training/application framing semantics belong to protocol owners.

It is a pure transport concern and MUST NOT know about:
- Step / barrier semantics
- Worker count or synchronization policy
- Model versions or gradients
"""
