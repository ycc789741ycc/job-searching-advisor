"""The paging contract every repository's ``get_list`` follows.

``page`` is 1-based. ``page_size=None`` returns every match, and then ``page``
must be 1. Anything else is a caller mistake, reported as a typed error rather
than an empty page.
"""

from __future__ import annotations

from kernel.errors import ValidationError


def check_page(page: int, page_size: int | None) -> None:
    if page < 1:
        raise ValidationError("page starts at 1", page=page)
    if page_size is None:
        if page != 1:
            raise ValidationError("an unpaged list has only page 1", page=page)
        return
    if page_size < 1:
        raise ValidationError("page_size must be at least 1", page_size=page_size)


def offset_of(page: int, page_size: int) -> int:
    return (page - 1) * page_size
