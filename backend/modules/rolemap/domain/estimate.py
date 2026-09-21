"""How many roles a set of postings can turn into, known before any clustering.

The cost shown before a first role map has to come from the api, which runs no
local ML (technical boundaries: embeddings and clustering live in the crawler
and the worker). So the estimate is a ceiling rather than a prediction: every
cluster needs at least ``MIN_POSTINGS_FOR_A_ROLE`` members, which bounds how
many there can be, and the user is never charged more than they were shown.
"""

from __future__ import annotations

# Below this, there is nothing to cluster and no role worth naming.
MIN_POSTINGS_FOR_A_ROLE = 3


def max_role_count(posting_count: int) -> int:
    """The most clusters ``posting_count`` postings can form."""
    if posting_count < 0:
        raise ValueError("posting_count cannot be negative")
    return posting_count // MIN_POSTINGS_FOR_A_ROLE
