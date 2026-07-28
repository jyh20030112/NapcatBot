"""NapcatBot pipeline latency benchmark.

Measures end-to-end message processing time across four scenarios:
- new_topic: first message creating a brand-new topic
- existing_topic: message classified into a pre-existing topic
- reply_to_inherit: reply message inheriting topic via fast path (no topic LLM)
- first_message: first message in a fresh group (no group profile)

Usage:
    python -m app.benchmark [--iterations N] [--scenarios ...] [--output PATH]
"""
