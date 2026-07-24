"""Lakeflow community connector for the City of Austin, Texas Open Data Portal.

The portal (``data.austintexas.gov``) is a Socrata SODA deployment.  Each of
the seven connector tables maps to a Socrata dataset (``4x4`` id) served at
``/resource/{4x4}.json`` with standard SODA query params (``$select``,
``$where``, ``$order``, ``$limit``, ``$offset``).  Authentication is an
optional ``X-App-Token`` header — public datasets read fine anonymously but at
a lower shared rate limit, so a token is sent when configured.

Incremental strategy: every Socrata dataset exposes the ``:updated_at`` system
field.  The connector selects it (renamed ``system_updated_at``) and uses it as
a CDC cursor, filtering with ``$where=:updated_at > since AND :updated_at <= until``.

Partitioned stream: because Socrata supports range queries on ``:updated_at``,
the connector implements ``SupportsPartitionedStream``.  ``latest_offset``
returns an init-time snapshot cursor (guaranteeing Trigger.AvailableNow
termination), and ``get_partitions`` splits the ``(start, end]`` range into
independent time windows that executors read in parallel.  The first run
(cursor at/around the epoch) collapses to a single open-ended partition so a
full backfill does not fan out into tens of thousands of daily windows.
"""

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator, Sequence

import requests
from requests.exceptions import RequestException
from pyspark.sql.types import StructType

from databricks.labs.community_connector.interface.lakeflow_connect import (
    LakeflowConnect,
)
from databricks.labs.community_connector.interface.supports_partition import (
    SupportsPartitionedStream,
)
from databricks.labs.community_connector.sources.hackathon_austin_texas.hackathon_austin_texas_schemas import (
    COERCION_MAP,
    CURSOR_FIELD,
    DATASET_IDS,
    DEFAULT_BASE_URL,
    DEFAULT_LOOKBACK_MINUTES,
    DEFAULT_PAGE_SIZE,
    DEFAULT_TIMEOUT,
    DEFAULT_WINDOW_DAYS,
    EPOCH_ISO,
    FIRST_RUN_SENTINEL_THRESHOLD,
    INITIAL_BACKOFF,
    MAX_PAGE_SIZE,
    MAX_RETRIES,
    RETRIABLE_STATUS_CODES,
    SYSTEM_FIELD_RENAMES,
    TABLE_METADATA,
    TABLE_SCHEMAS,
    TABLES,
    URL_STRUCT_FIELDS,
)

_ERROR_BODY_LIMIT = 500


class HackathonAustinTexasLakeflowConnect(LakeflowConnect, SupportsPartitionedStream):
    """LakeflowConnect + SupportsPartitionedStream for data.austintexas.gov (Socrata)."""

    def __init__(self, options: dict[str, str]) -> None:
        super().__init__(options)

        self._base_url = (options.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
        # App token is optional: public datasets read without one, but a token
        # lifts the connector out of the shared per-IP throttle.
        self._app_token = options.get("app_token") or options.get("X-App-Token")

        try:
            self._page_size = max(
                1,
                min(MAX_PAGE_SIZE, int(options.get("page_size") or DEFAULT_PAGE_SIZE)),
            )
        except (TypeError, ValueError):
            self._page_size = DEFAULT_PAGE_SIZE

        # Freeze the high-water mark at init time so incremental reads return a
        # stable cursor across microbatches within one Trigger.AvailableNow
        # run — this is what guarantees termination.  A later trigger builds a
        # fresh instance with a newer cap and picks up anything that arrived.
        self._init_time = self._format_iso(datetime.now(timezone.utc))

    # ------------------------------------------------------------------
    # LakeflowConnect — schema / metadata
    # ------------------------------------------------------------------

    def list_tables(self) -> list[str]:
        """Static object list — a curated set of seven City of Austin datasets."""
        return list(TABLES)

    def get_table_schema(
        self, table_name: str, table_options: dict[str, str]
    ) -> StructType:
        self._validate_table(table_name)
        return TABLE_SCHEMAS[table_name]

    def read_table_metadata(
        self, table_name: str, table_options: dict[str, str]
    ) -> dict:
        self._validate_table(table_name)
        return dict(TABLE_METADATA[table_name])

    # ------------------------------------------------------------------
    # SupportsPartitionedStream
    # ------------------------------------------------------------------

    def is_partitioned(self, table_name: str) -> bool:
        return table_name in TABLES

    def latest_offset(
        self,
        table_name: str,
        table_options: dict[str, str],
        start_offset: dict | None = None,
    ) -> dict:
        """Return the high-water mark, capped at the init-time snapshot.

        Kept metadata-cheap: it returns the frozen ``_init_time`` rather than
        querying the source.  Once a stream catches up to this value,
        successive calls return it unchanged and Trigger.AvailableNow
        terminates.
        """
        self._validate_table(table_name)
        return {"cursor": self._init_time}

    def get_partitions(
        self,
        table_name: str,
        table_options: dict[str, str],
        start_offset: dict | None = None,
        end_offset: dict | None = None,
    ) -> Sequence[dict]:
        """Split the ``(start, end]`` ``:updated_at`` range into time windows."""
        self._validate_table(table_name)

        window_days = self._parse_int(
            table_options.get("window_days"), DEFAULT_WINDOW_DAYS, minimum=1
        )
        lookback_minutes = self._parse_int(
            table_options.get("lookback_minutes"),
            DEFAULT_LOOKBACK_MINUTES,
            minimum=0,
        )

        if start_offset is None and end_offset is None:
            # Batch read — cover the whole table.
            start_iso = EPOCH_ISO
            end_iso = self._init_time
        else:
            start_iso = (start_offset or {}).get("cursor") or EPOCH_ISO
            end_iso = (end_offset or {}).get("cursor") or self._init_time

        start_dt = self._parse_iso(start_iso)
        end_dt = self._parse_iso(end_iso)
        if start_dt >= end_dt:
            return []

        # First-run optimisation: a single open-ended partition for the
        # backfill instead of one window per day back to the epoch.
        if start_dt <= self._parse_iso(FIRST_RUN_SENTINEL_THRESHOLD):
            return [{"since": EPOCH_ISO, "until": end_iso}]

        if lookback_minutes > 0:
            start_iso = self._format_iso(
                start_dt - timedelta(minutes=lookback_minutes)
            )
            start_dt = self._parse_iso(start_iso)
            if start_dt >= end_dt:
                return []

        partitions: list[dict] = []
        cursor_iso = start_iso
        cursor_dt = start_dt
        while cursor_dt < end_dt:
            next_dt = cursor_dt + timedelta(days=window_days)
            if next_dt > end_dt:
                next_dt = end_dt
                next_iso = end_iso
            else:
                next_iso = self._format_iso(next_dt)
            partitions.append({"since": cursor_iso, "until": next_iso})
            cursor_iso = next_iso
            cursor_dt = next_dt

        return partitions

    def read_partition(
        self,
        table_name: str,
        partition: dict,
        table_options: dict[str, str],
    ) -> Iterator[dict]:
        """Read one ``(since, until]`` window on an executor."""
        self._validate_table(table_name)
        since = partition.get("since", EPOCH_ISO)
        until = partition.get("until", self._init_time)
        yield from self._fetch_window(table_name, since, until)

    # ------------------------------------------------------------------
    # LakeflowConnect.read_table — single-driver fallback
    # ------------------------------------------------------------------

    def read_table(
        self,
        table_name: str,
        start_offset: dict,
        table_options: dict[str, str],
    ) -> tuple[Iterator[dict], dict]:
        """Single-driver incremental read (used when partitioning is off).

        Reads everything in ``(start_cursor, init_time]`` in one batch and
        advances the offset to ``init_time`` — the next call then returns an
        empty batch with the same offset, terminating the trigger.
        """
        self._validate_table(table_name)

        since = (start_offset or {}).get("cursor") or EPOCH_ISO
        if self._parse_iso(since) >= self._parse_iso(self._init_time):
            return iter([]), start_offset or {"cursor": self._init_time}

        records = list(self._fetch_window(table_name, since, self._init_time))
        return iter(records), {"cursor": self._init_time}

    # ------------------------------------------------------------------
    # HTTP + record shaping
    # ------------------------------------------------------------------

    def _fetch_window(
        self, table_name: str, since: str, until: str
    ) -> Iterator[dict]:
        """Yield transformed records for a single ``:updated_at`` window.

        Paginates the Socrata resource with ``$offset`` / ``$limit`` until a
        short page signals the end of the window.
        """
        dataset_id = DATASET_IDS[table_name]
        where = self._build_where(since, until)

        offset = 0
        while True:
            params = {
                # ``:*,*`` selects the Socrata system fields alongside the
                # published columns so ``:updated_at`` is available as a cursor.
                "$select": ":*,*",
                "$where": where,
                "$order": ":updated_at",
                "$limit": str(self._page_size),
                "$offset": str(offset),
            }
            resp = self._request(dataset_id, params)
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Socrata request for {table_name!r} ({dataset_id}) failed: "
                    f"{resp.status_code} {self._redact(resp.text)}"
                )

            batch = resp.json()
            if not isinstance(batch, list):
                raise RuntimeError(
                    f"Unexpected Socrata response shape for {table_name!r}: "
                    f"expected a JSON array, got {type(batch).__name__}"
                )
            if not batch:
                return

            for raw in batch:
                yield self._transform_record(table_name, raw)

            if len(batch) < self._page_size:
                return
            offset += self._page_size

    def _request(self, dataset_id: str, params: dict[str, str]) -> requests.Response:
        """GET ``/resource/{4x4}.json`` with retry on transient failures.

        A fresh ``requests.get`` per call keeps the connector free of
        non-picklable state so it ships cleanly to Spark executors.
        """
        url = f"{self._base_url}/resource/{dataset_id}.json"
        headers = {"Accept": "application/json"}
        if self._app_token:
            headers["X-App-Token"] = self._app_token

        backoff = INITIAL_BACKOFF
        resp: requests.Response | None = None
        last_exc: RequestException | None = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = requests.get(
                    url, params=params, headers=headers, timeout=DEFAULT_TIMEOUT
                )
            except RequestException as exc:
                last_exc = exc
            else:
                if resp.status_code not in RETRIABLE_STATUS_CODES:
                    return resp
            if attempt < MAX_RETRIES - 1:
                sleep_for = backoff
                if resp is not None:
                    retry_after = resp.headers.get("Retry-After", "").strip()
                    if retry_after:
                        try:
                            sleep_for = max(sleep_for, float(retry_after))
                        except ValueError:
                            pass
                time.sleep(sleep_for)
                backoff *= 2

        if resp is None and last_exc is not None:
            raise RuntimeError(
                f"Socrata request failed after {MAX_RETRIES} attempts "
                f"for {dataset_id}: {last_exc}"
            ) from last_exc
        return resp

    def _transform_record(self, table_name: str, raw: Any) -> dict:
        """Normalise a raw Socrata row into the shape declared by the schema.

        * Rename the three system fields (``:id`` etc.) to their colon-free
          Spark column names (tolerant of an already-renamed simulator row).
        * Serialise ``the_geom`` (GeoJSON) to ``the_geom_json``.
        * Normalise URL fields to a ``{"url": ...}`` struct.
        * Coerce Socrata's string-encoded numbers to their declared type.
        """
        if not isinstance(raw, dict):
            return {}
        record = dict(raw)

        for wire_name, spark_name in SYSTEM_FIELD_RENAMES.items():
            if wire_name in record:
                record[spark_name] = record.pop(wire_name)

        if "the_geom" in record:
            geom = record.pop("the_geom")
            record["the_geom_json"] = (
                geom if isinstance(geom, str) else self._json_or_none(geom)
            )

        for url_field in URL_STRUCT_FIELDS.get(table_name, []):
            value = record.get(url_field)
            if isinstance(value, str):
                record[url_field] = {"url": value}

        for field_name, kind in COERCION_MAP.get(table_name, {}).items():
            if field_name in record:
                if kind == "long":
                    record[field_name] = self._coerce_long(record[field_name])
                else:
                    record[field_name] = self._coerce_double(record[field_name])

        return record

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _validate_table(self, table_name: str) -> None:
        if table_name not in TABLES:
            raise ValueError(
                f"Table '{table_name}' is not supported. Supported tables: {TABLES}"
            )

    def _build_where(self, since: str, until: str) -> str:
        """Build the SoQL ``$where`` clause over ``:updated_at``.

        The first run (``since`` at/before the epoch) has no lower bound so it
        catches every historical row.  Non-first windows use an exclusive lower
        bound so back-to-back windows are disjoint — a boundary row belongs to
        exactly one window.
        """
        until_lit = self._soql_literal(until)
        if self._parse_iso(since) <= self._parse_iso(EPOCH_ISO):
            return f":updated_at <= '{until_lit}'"
        since_lit = self._soql_literal(since)
        return f":updated_at > '{since_lit}' AND :updated_at <= '{until_lit}'"

    @staticmethod
    def _soql_literal(iso_ts: str) -> str:
        """Render an ISO timestamp as a Socrata floating-timestamp literal."""
        dt = HackathonAustinTexasLakeflowConnect._parse_iso(iso_ts)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]

    @staticmethod
    def _parse_int(value: Any, default: int, *, minimum: int = 0) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed >= minimum else default

    @staticmethod
    def _parse_iso(iso_ts: str) -> datetime:
        """Parse an ISO timestamp, tolerating a trailing ``Z`` and naive values."""
        text = (iso_ts or EPOCH_ISO).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"Invalid ISO timestamp {iso_ts!r}") from exc
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @staticmethod
    def _format_iso(dt: datetime) -> str:
        """Format a datetime as ``YYYY-MM-DDTHH:MM:SS.mmmZ`` (UTC)."""
        dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"

    @staticmethod
    def _redact(text: str) -> str:
        if not text:
            return ""
        flat = text.replace("\r", " ").replace("\n", " ")
        if len(flat) <= _ERROR_BODY_LIMIT:
            return flat
        return flat[:_ERROR_BODY_LIMIT] + "...[truncated]"

    @staticmethod
    def _json_or_none(value: Any) -> str | None:
        if value is None:
            return None
        try:
            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_long(value: Any) -> int | None:
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_double(value: Any) -> float | None:
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
