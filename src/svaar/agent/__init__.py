"""Shared chat/voice agent, channel transports, memory, dedupe, and outbox delivery.

All proposed tool calls must pass through actions. This package must not import
voice; application composition will inject a structurally compatible turn runner.
"""
