"""Single tool dispatch boundary for both chat and voice.

Own argument validation, scoped authorization, mission/channel restrictions,
configured risk tiers, and execution audit. Feature handlers must never bypass
this boundary; model confidence never grants permission to execute.
"""
