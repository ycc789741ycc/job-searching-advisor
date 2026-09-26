"""The paging contract every repository's get_list follows."""

from __future__ import annotations

import pytest

from kernel.errors import ValidationError
from kernel.paging import check_page, offset_of


@pytest.mark.parametrize(("page", "page_size"), [(1, None), (1, 1), (3, 50)])
def test_valid_pages_pass(page: int, page_size: int | None) -> None:
    check_page(page, page_size)


@pytest.mark.parametrize(("page", "page_size"), [(0, 10), (-1, None), (2, None), (1, 0)])
def test_invalid_pages_are_a_typed_error(page: int, page_size: int | None) -> None:
    with pytest.raises(ValidationError):
        check_page(page, page_size)


def test_pages_are_one_based() -> None:
    assert offset_of(1, 20) == 0
    assert offset_of(3, 20) == 40
