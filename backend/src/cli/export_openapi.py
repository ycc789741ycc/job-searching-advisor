"""Prints the OpenAPI document.

The API contract is the client/server boundary: `make gen-client` turns this
into the TypeScript client, and CI fails when the checked-in client drifts.
"""

from __future__ import annotations

import json

from api.main import create_app


def main() -> None:
    print(json.dumps(create_app().openapi(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
