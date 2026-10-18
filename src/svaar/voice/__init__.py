"""Bolna transport, outbound call missions, turn handling, and authenticated callbacks.

Bolna's function-mode wrapper exposes only ask_svaar, never business tools.
All business tool execution belongs to actions through the shared turn runner.
"""
