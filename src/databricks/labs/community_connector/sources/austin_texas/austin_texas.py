"""Community connector for the City of Austin, Texas open-data portal.

The portal (``data.austintexas.gov``) runs on Socrata and exposes datasets
through the generic Socrata Open Data API (SODA). This connector's scope is a
single dataset — "Green Building Ratings Aggregate" (resource id
``dpvb-c5fy``) — surfaced as the table ``green_building_ratings_aggregate``.

Ingestion is ``snapshot``: the dataset is tiny (~57 rows), has no per-row
updated-at cursor, and can be revised in place by the publisher, so a full
re-read on each sync is both cheap and the safest way to reflect corrections
and deletions.

Auth is an optional Socrata Application Token sent as the ``X-App-Token``
header. Public datasets like this one are readable without a token (subject to
shared per-IP throttling), so the connector works with no credentials — which
is what simulate-mode testing relies on.
"""

import time
from typing import Iterator, Optional

import requests
from pyspark.sql.types import StructType

from databricks.labs.community_connector.interface import LakeflowConnect
from databricks.labs.community_connector.sources.austin_texas.austin_texas_schemas import (
    BASE_URL,
    DEFAULT_PAGE_SIZE,
    GREEN_BUILDING_METADATA,
    GREEN_BUILDING_SCHEMA,
    INITIAL_BACKOFF,
    MAX_RETRIES,
    REQUEST_TIMEOUT,
    RESOURCE_ID,
    RETRIABLE_STATUS_CODES,
    SNAPSHOT_ORDER,
    TABLE_NAME,
)


class AustinTexasLakeflowConnect(LakeflowConnect):
    """LakeflowConnect implementation for the Austin, Texas Socrata portal."""

    def __init__(self, options: dict[str, str]) -> None:
        super().__init__(options)
        # Socrata app token is optional: public datasets are readable without
        # it. When absent the connector simply omits the ``X-App-Token`` header
        # and shares the anonymous per-IP throttling pool.
        self._app_token = options.get("app_token") or options.get("X-App-Token")

    # ----- HTTP plumbing --------------------------------------------------

    @property
    def _resource_url(self) -> str:
        return f"{BASE_URL}/resource/{RESOURCE_ID}.json"

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._app_token:
            headers["X-App-Token"] = self._app_token
        return headers

    def _request_with_retry(self, params: dict[str, str]) -> requests.Response:
        """GET the SODA resource, retrying on 429/5xx with exponential backoff.

        Honors a ``Retry-After`` header when present, otherwise falls back to
        the connector's own doubling backoff schedule.
        """
        backoff = INITIAL_BACKOFF
        resp = None
        for attempt in range(MAX_RETRIES):
            resp = requests.get(
                self._resource_url,
                params=params,
                headers=self._headers(),
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code not in RETRIABLE_STATUS_CODES:
                return resp

            if attempt < MAX_RETRIES - 1:
                time.sleep(self._retry_delay(resp, backoff))
                backoff *= 2

        return resp

    @staticmethod
    def _retry_delay(resp: requests.Response, backoff: float) -> float:
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except (TypeError, ValueError):
                pass
        return backoff

    # ----- LakeflowConnect interface -------------------------------------

    def list_tables(self) -> list[str]:
        """Static single-table scope for this connector."""
        return [TABLE_NAME]

    def get_table_schema(self, table_name: str, table_options: dict[str, str]) -> StructType:
        self._validate_table(table_name)
        return GREEN_BUILDING_SCHEMA

    def read_table_metadata(self, table_name: str, table_options: dict[str, str]) -> dict:
        self._validate_table(table_name)
        return dict(GREEN_BUILDING_METADATA)

    def read_table(
        self, table_name: str, start_offset: dict, table_options: dict[str, str]
    ) -> tuple[Iterator[dict], dict]:
        """Full-snapshot read.

        Pages through the SODA resource with ``$limit``/``$offset`` under a
        stable ``$order`` and returns every row in a single batch. The dataset
        is small enough that one page normally suffices; paging is defensive
        against future growth. Returns an empty offset (``{}``) because
        snapshot reads are not checkpointed.
        """
        self._validate_table(table_name)

        page_size = int(table_options.get("page_size", str(DEFAULT_PAGE_SIZE)))

        records: list[dict] = []
        offset = 0
        while True:
            params = {
                "$limit": str(page_size),
                "$offset": str(offset),
                "$order": SNAPSHOT_ORDER,
            }
            resp = self._request_with_retry(params)
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Failed to read '{table_name}' from Socrata "
                    f"(status {resp.status_code}): {resp.text}"
                )

            batch = resp.json()
            if not isinstance(batch, list):
                raise RuntimeError(
                    f"Unexpected SODA response for '{table_name}': expected a JSON "
                    f"array, got {type(batch).__name__}"
                )

            records.extend(batch)

            # A short (or empty) page means we have reached the end.
            if len(batch) < page_size:
                break
            offset += page_size

        return iter(records), {}

    # ----- helpers --------------------------------------------------------

    def _validate_table(self, table_name: str) -> None:
        supported = self.list_tables()
        if table_name not in supported:
            raise ValueError(
                f"Table '{table_name}' is not supported. Supported tables: {supported}"
            )
