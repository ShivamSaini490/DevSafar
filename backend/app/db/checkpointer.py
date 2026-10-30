
"""LangGraph checkpointer policy for the current vertical slice.

TODO: A later module may add a short-retention PostgreSQL checkpointer for saved chats
only. Temporary chats must never create checkpoints. This module intentionally exposes
no checkpointer and the graph is compiled with ``checkpointer=None``.
"""

CHECKPOINTER_ENABLED = False
