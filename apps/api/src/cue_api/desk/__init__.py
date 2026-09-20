"""Desk UI adapter (D): serves hemadassani/cue-desk-ui's contract on the team stack.

Read-only translation of A's control snapshot and readiness plus a feed of C's
decisions and captions into the desk's WebSocket messages. Takes and mode changes
go through A's own routes from the page, so the compositor stays the only
renderer and acknowledger.
"""
