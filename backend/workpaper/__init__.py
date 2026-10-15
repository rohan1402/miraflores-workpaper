"""MiraFlores tax workpaper backend.

Three layers:
  1. packet.py   the packet as delivered, read-only.
  2. events.py   the append-only log of what people did.
  3. project.py  current state = project(packet, events). The checker reads that state.
"""
