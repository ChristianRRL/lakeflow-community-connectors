"""Microsoft SharePoint (Microsoft Graph API) Lakeflow Community Connector.

Implements ``LakeflowConnect`` + ``SupportsPartition``.

Tables
------
    lists       GET /sites/{site-id}/lists                       (snapshot)
    list_items  GET /sites/{site-id}/lists/{list-id}/items       (cdc_with_deletes)

Why ``SupportsPartition`` and not ``SupportsPartitionedStream``
--------------------------------------------------------------
SharePoint's incremental change tracking is the Graph **delta** endpoint
(``.../items/delta``), whose cursor is an *opaque delta token* embedded in the
``@odata.deltaLink`` URL.  That token is produced by *reading* the feed, so it
can only be checkpointed by the reader that returned it — i.e. via the offset
that ``read_table`` returns.  The partitioned-*stream* model derives the next
offset from ``latest_offset`` (a cheap, read-free driver call) and never lets
``read_partition`` write back an offset, so delta tokens cannot round-trip
through it.

Therefore streaming stays on the single-driver path (``read_table`` /
``read_table_deletes``), which carries per-list delta links in its offset, and
``SupportsPartition`` is used purely to parallelise **batch** (full-refresh)
reads: ``get_partitions`` shards ``list_items`` by list so each list's items
are read in parallel on a separate Spark executor.

Delta semantics
---------------
* ``read_table`` walks the delta feed per list and yields non-deleted items
  (upserts).  It keeps a per-list resume URL (``@odata.nextLink`` while paging,
  ``@odata.deltaLink`` once drained) in the returned offset.
* ``read_table_deletes`` walks an *independent* delta chain (its own offset)
  and yields items carrying the ``deleted`` facet as delete tombstones.
* Graph rotates ``@odata.deltaLink`` on every call even when nothing changed,
  so a naive "did the link change?" check never terminates.  Following the
  microsoft_teams pattern: when a list already had a resume link and this walk
  produced no records, its prior link is kept unchanged, so once every list is
  drained the offset stops moving and Trigger.AvailableNow converges.
* A stale delta token yields ``410 Gone``; the walk restarts that list's chain
  tokenless (a fresh full enumeration), per Graph guidance.
"""

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Iterator

import requests
from pyspark.sql.types import StructType

from databricks.labs.community_connector.interface.lakeflow_connect import LakeflowConnect
from databricks.labs.community_connector.interface.supports_partition import SupportsPartition
from databricks.labs.community_connector.sources.microsoft_sharepoint.microsoft_sharepoint_schemas import (
    DEFAULT_MAX_PAGES,
    DEFAULT_TOP,
    GRAPH_BASE_URL,
    GRAPH_SCOPE,
    INITIAL_BACKOFF,
    LIST_SELECT_WITH_SYSTEM,
    LOGIN_BASE_URL,
    MAX_RETRIES,
    REQUEST_TIMEOUT,
    RETRIABLE_STATUS_CODES,
    SUPPORTED_TABLES,
    TABLE_METADATA,
    TABLE_SCHEMAS,
)

# Top-level struct-typed columns that must be coerced from an empty dict ``{}``
# to ``None`` (Spark's dict->Row conversion rejects empty structs).
_STRUCT_COLUMNS = (
    "contentType",
    "createdBy",
    "lastModifiedBy",
    "parentReference",
    "sharepointIds",
    "list",
    "deleted",
)


class GraphHTTPError(RuntimeError):
    """Raised for a non-retriable / exhausted Microsoft Graph HTTP error."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"Graph request failed ({status_code}): {message}")
        self.status_code = status_code


class MicrosoftGraphClient:
    """HTTP client for Microsoft Graph with OAuth 2.0 client-credentials auth.

    Holds only picklable state (credential strings + a cached token string), so
    an instance ships cleanly to Spark executors for partitioned reads.
    """

    def __init__(self, tenant_id: str, client_id: str, client_secret: str) -> None:
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = GRAPH_BASE_URL
        self._access_token: str | None = None
        self._token_expiry: datetime | None = None

    def get_access_token(self) -> str:
        """Acquire (and cache) an app-only access token via client credentials."""
        if not self.tenant_id or not self.client_id or not self.client_secret:
            raise ValueError(
                "Missing required options: tenant_id, client_id and client_secret "
                "are required for the Microsoft SharePoint connector."
            )

        if (
            self._access_token
            and self._token_expiry
            and datetime.now(timezone.utc) < self._token_expiry
        ):
            return self._access_token

        token_url = f"{LOGIN_BASE_URL}/{self.tenant_id}/oauth2/v2.0/token"
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": GRAPH_SCOPE,
            "grant_type": "client_credentials",
        }

        try:
            response = requests.post(token_url, data=data, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            raise RuntimeError(f"Token acquisition request failed: {exc}") from exc

        if response.status_code != 200:
            raise RuntimeError(
                f"Token acquisition failed ({response.status_code}): "
                f"{response.text[:500]}"
            )

        token_data = response.json()
        self._access_token = token_data["access_token"]
        expires_in = int(token_data.get("expires_in", 3600))
        # Refresh 5 minutes early to avoid using a token that expires mid-request.
        self._token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 300)
        return self._access_token

    def get_json(self, url: str, params: dict | None = None) -> dict:
        """GET a Graph URL, retrying on 429/5xx and honouring ``Retry-After``.

        Raises :class:`GraphHTTPError` on a non-retriable status or once retries
        are exhausted so callers (e.g. delta walks) can react to specific codes
        such as ``410 Gone``.
        """
        backoff = INITIAL_BACKOFF
        for attempt in range(MAX_RETRIES):
            headers = {
                "Authorization": f"Bearer {self.get_access_token()}",
                "Accept": "application/json",
            }
            try:
                response = requests.get(
                    url, params=params, headers=headers, timeout=REQUEST_TIMEOUT
                )
            except requests.RequestException as exc:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                raise RuntimeError(f"Graph request to {url} failed: {exc}") from exc

            if response.status_code == 200:
                return response.json()

            if response.status_code == 401:
                # Token may have been revoked; drop the cache and retry once.
                self._access_token = None
                self._token_expiry = None
                if attempt < MAX_RETRIES - 1:
                    continue
                raise GraphHTTPError(401, response.text[:500])

            if response.status_code in RETRIABLE_STATUS_CODES:
                if attempt < MAX_RETRIES - 1:
                    # Honour Retry-After when present; the API requires it.
                    retry_after = response.headers.get("Retry-After")
                    wait = int(retry_after) if retry_after and retry_after.isdigit() else backoff
                    time.sleep(wait)
                    backoff *= 2
                    continue
                raise GraphHTTPError(response.status_code, response.text[:500])

            raise GraphHTTPError(response.status_code, response.text[:500])

        # Unreachable, but keeps type-checkers content.
        raise GraphHTTPError(0, f"Max retries exceeded for {url}")


def _parse_int_option(table_options: dict[str, str], key: str, default: int) -> int:
    try:
        return int(table_options.get(key, default))
    except (TypeError, ValueError):
        return default


def _is_deleted_item(item: dict) -> bool:
    """Return True when a delta item represents a deletion.

    Graph marks removed items with a ``deleted`` facet whose ``state`` is
    ``"deleted"``.  Checking the state (rather than mere presence of the facet)
    avoids misclassifying items that carry an unrelated / synthesized
    ``deleted`` sub-object.
    """
    deleted = item.get("deleted")
    return isinstance(deleted, dict) and deleted.get("state") == "deleted"


def _sanitize_structs(record: dict) -> dict:
    """Convert empty-dict struct columns to ``None`` in place and return record."""
    for key in _STRUCT_COLUMNS:
        if key in record and record[key] == {}:
            record[key] = None
    return record


class MicrosoftSharepointLakeflowConnect(LakeflowConnect, SupportsPartition):
    """LakeflowConnect implementation for Microsoft SharePoint via Graph."""

    def __init__(self, options: dict[str, str]) -> None:
        super().__init__(options)
        self._client = MicrosoftGraphClient(
            tenant_id=options.get("tenant_id"),
            client_id=options.get("client_id"),
            client_secret=options.get("client_secret"),
        )
        # Resolved site-id cache (site resolution is done once and reused).
        self._site_id_cache: str | None = None

    # ------------------------------------------------------------------
    # Interface: catalog / schema / metadata
    # ------------------------------------------------------------------

    def list_tables(self) -> list[str]:
        return list(SUPPORTED_TABLES)

    def get_table_schema(self, table_name: str, table_options: dict[str, str]) -> StructType:
        self._validate_table(table_name)
        return TABLE_SCHEMAS[table_name]

    def read_table_metadata(self, table_name: str, table_options: dict[str, str]) -> dict:
        self._validate_table(table_name)
        config = TABLE_METADATA[table_name]
        metadata = {
            "primary_keys": list(config["primary_keys"]),
            "ingestion_type": config["ingestion_type"],
        }
        if "cursor_field" in config:
            metadata["cursor_field"] = config["cursor_field"]
        return metadata

    # ------------------------------------------------------------------
    # Interface: reads (single-driver streaming path)
    # ------------------------------------------------------------------

    def read_table(
        self, table_name: str, start_offset: dict, table_options: dict[str, str]
    ) -> tuple[Iterator[dict], dict]:
        self._validate_table(table_name)
        if table_name == "lists":
            return self._read_lists(table_options)
        return self._read_list_items_delta(start_offset, table_options, deletes=False)

    def read_table_deletes(
        self, table_name: str, start_offset: dict, table_options: dict[str, str]
    ) -> tuple[Iterator[dict], dict]:
        self._validate_table(table_name)
        if table_name != "list_items":
            raise ValueError(f"Table '{table_name}' does not support deleted records")
        return self._read_list_items_delta(start_offset, table_options, deletes=True)

    # ------------------------------------------------------------------
    # Interface: SupportsPartition (batch / full-refresh parallelism)
    # ------------------------------------------------------------------

    def get_partitions(
        self, table_name: str, table_options: dict[str, str]
    ) -> list[dict]:
        """Shard a full-refresh read across executors.

        ``lists`` is a single small collection → one partition.  ``list_items``
        is sharded by list so each list's items are read in parallel.
        """
        self._validate_table(table_name)
        site_id = self._resolve_site_id(table_options)
        if table_name == "lists":
            return [{"table": "lists", "site_id": site_id}]

        list_ids = self._resolve_list_ids(site_id, table_options)
        return [
            {"table": "list_items", "site_id": site_id, "list_id": list_id}
            for list_id in list_ids
        ]

    def read_partition(
        self, table_name: str, partition: dict, table_options: dict[str, str]
    ) -> Iterator[dict]:
        """Read one partition's records on a Spark executor."""
        site_id = partition["site_id"]
        if table_name == "lists":
            return iter(self._fetch_lists(site_id, table_options, with_site=True))
        list_id = partition["list_id"]
        return iter(self._fetch_list_items_full(site_id, list_id, table_options))

    # ------------------------------------------------------------------
    # Site / list resolution
    # ------------------------------------------------------------------

    def _resolve_site_id(self, table_options: dict[str, str]) -> str:
        """Resolve the Graph ``site-id`` from options, caching the result.

        Precedence: an explicit ``site_id`` (opaque composite Graph id) wins;
        otherwise a human-friendly ``site_url`` is resolved via colon-syntax
        addressing; otherwise the tenant root site is used.
        """
        explicit = table_options.get("site_id") or self.options.get("site_id")
        if explicit:
            return explicit
        if self._site_id_cache:
            return self._site_id_cache

        site_url = table_options.get("site_url") or self.options.get("site_url")
        if site_url:
            url = f"{self._client.base_url}/sites/{site_url}"
        else:
            url = f"{self._client.base_url}/sites/root"

        data = self._client.get_json(url)
        site_id = data.get("id")
        if not site_id:
            raise RuntimeError(
                f"Could not resolve a site-id from {url}; response had no 'id'."
            )
        self._site_id_cache = site_id
        return site_id

    def _resolve_list_ids(self, site_id: str, table_options: dict[str, str]) -> list[str]:
        """Return the list-ids to read: an explicit ``list_id`` or all lists."""
        explicit = table_options.get("list_id")
        if explicit:
            return [explicit]
        lists = self._fetch_lists(site_id, table_options, with_site=False)
        return [row["id"] for row in lists if row.get("id")]

    # ------------------------------------------------------------------
    # lists reads
    # ------------------------------------------------------------------

    def _read_lists(
        self, table_options: dict[str, str]
    ) -> tuple[Iterator[dict], dict]:
        site_id = self._resolve_site_id(table_options)
        records = self._fetch_lists(site_id, table_options, with_site=True)
        # snapshot table: no incremental offset.
        return iter(records), {}

    def _fetch_lists(
        self, site_id: str, table_options: dict[str, str], with_site: bool
    ) -> list[dict]:
        """Page through ``/sites/{site-id}/lists`` and return cleaned rows.

        ``include_system=true`` surfaces the normally hidden system lists by
        adding ``system`` to ``$select`` (Graph hides them by default).
        """
        include_system = table_options.get("include_system", "").lower() == "true"
        max_pages = _parse_int_option(table_options, "max_pages_per_batch", DEFAULT_MAX_PAGES)
        top = _parse_int_option(table_options, "top", DEFAULT_TOP)

        url: str | None = f"{self._client.base_url}/sites/{site_id}/lists"
        params: dict | None = {"$top": top}
        if include_system:
            params["$select"] = LIST_SELECT_WITH_SYSTEM

        records: list[dict] = []
        pages = 0
        while url and pages < max_pages:
            data = self._client.get_json(url, params=params)
            params = None  # nextLink already encodes query params
            for raw in data.get("value", []):
                record = _sanitize_structs(dict(raw))
                if with_site:
                    record["site_id"] = site_id
                records.append(record)
            url = data.get("@odata.nextLink")
            pages += 1
        return records

    # ------------------------------------------------------------------
    # list_items reads
    # ------------------------------------------------------------------

    def _build_item_record(self, item: dict, site_id: str, list_id: str) -> dict:
        """Project a raw Graph listItem into a connector record.

        The dynamic ``fields`` facet is serialised to a JSON string so the
        framework can load it into the ``VariantType`` column.
        """
        record = _sanitize_structs(dict(item))
        fields = record.get("fields")
        record["fields"] = json.dumps(fields) if fields else None
        record["list_id"] = list_id
        record["site_id"] = site_id
        return record

    def _fetch_list_items_full(
        self, site_id: str, list_id: str, table_options: dict[str, str]
    ) -> list[dict]:
        """Full (non-delta) read of a list's items with field values expanded."""
        max_pages = _parse_int_option(table_options, "max_pages_per_batch", DEFAULT_MAX_PAGES)
        top = _parse_int_option(table_options, "top", DEFAULT_TOP)

        url: str | None = (
            f"{self._client.base_url}/sites/{site_id}/lists/{list_id}/items"
        )
        # $expand=fields is REQUIRED — column values are absent otherwise.
        params: dict | None = {"$expand": "fields", "$top": top}

        records: list[dict] = []
        pages = 0
        while url and pages < max_pages:
            data = self._client.get_json(url, params=params)
            params = None
            for item in data.get("value", []):
                records.append(self._build_item_record(item, site_id, list_id))
            url = data.get("@odata.nextLink")
            pages += 1
        return records

    def _read_list_items_delta(
        self, start_offset: dict, table_options: dict[str, str], deletes: bool
    ) -> tuple[Iterator[dict], dict]:
        """Incremental delta read across every in-scope list.

        Yields upserts (``deletes=False``) or delete tombstones
        (``deletes=True``).  Each list keeps its own resume link inside the
        ``links`` offset map; when a list produces no records its prior link is
        kept unchanged so Trigger.AvailableNow converges.
        """
        site_id = self._resolve_site_id(table_options)
        list_ids = self._resolve_list_ids(site_id, table_options)
        max_pages = _parse_int_option(table_options, "max_pages_per_batch", DEFAULT_MAX_PAGES)

        prior_links = (
            start_offset.get("links", {})
            if start_offset and isinstance(start_offset, dict)
            else {}
        )
        new_links = dict(prior_links)

        records: list[dict] = []
        for list_id in list_ids:
            key = f"{site_id}/{list_id}"
            prior_url = prior_links.get(key)
            recs, end_url = self._walk_list_delta(
                site_id, list_id, prior_url, max_pages, deletes
            )
            records.extend(recs)
            # Graph rotates the deltaLink even with no changes; keep the prior
            # link when this list yielded nothing so the offset can stabilise.
            if prior_url is not None and not recs:
                new_links[key] = prior_url
            elif end_url:
                new_links[key] = end_url

        end_offset = {"links": new_links} if new_links else {}
        if start_offset and end_offset == start_offset:
            return iter([]), start_offset
        return iter(records), end_offset

    def _walk_list_delta(
        self,
        site_id: str,
        list_id: str,
        start_url: str | None,
        max_pages: int,
        deletes: bool,
    ) -> tuple[list[dict], str | None]:
        """Walk one list's delta feed; return (records, resume_url).

        ``resume_url`` is the ``@odata.deltaLink`` once the feed is drained, or
        the ``@odata.nextLink`` if paging stopped early at ``max_pages``.
        Handles a stale token (``410 Gone``) by restarting the chain tokenless.
        """
        if start_url:
            url: str | None = start_url
            params: dict | None = None
        else:
            url = f"{self._client.base_url}/sites/{site_id}/lists/{list_id}/items/delta"
            params = {"$expand": "fields"}

        records: list[dict] = []
        resume_url = start_url
        pages = 0
        while url and pages < max_pages:
            try:
                data = self._client.get_json(url, params=params)
            except GraphHTTPError as exc:
                if exc.status_code == 410 and start_url is not None:
                    # Stale delta token — restart this list from scratch.
                    return self._walk_list_delta(site_id, list_id, None, max_pages, deletes)
                raise
            params = None  # nextLink / deltaLink already encode query params

            for item in data.get("value", []):
                if deletes == _is_deleted_item(item):
                    records.append(self._build_item_record(item, site_id, list_id))

            delta_link = data.get("@odata.deltaLink")
            if delta_link:
                resume_url = delta_link
                break
            next_link = data.get("@odata.nextLink")
            if next_link:
                resume_url = next_link
                url = next_link
                pages += 1
                continue
            # Feed drained but the response carried no deltaLink (e.g. the
            # in-process simulator emits ``@odata.deltaLink: null``).  Fall
            # back to a stable sentinel — the tokenless delta URL — so the
            # offset advances on the first productive read and then compares
            # equal on the next read, letting Trigger.AvailableNow converge.
            resume_url = (
                f"{self._client.base_url}/sites/{site_id}/lists/{list_id}/items/delta"
            )
            break

        return records, resume_url

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _validate_table(self, table_name: str) -> None:
        if table_name not in TABLE_SCHEMAS:
            raise ValueError(
                f"Table '{table_name}' is not supported. "
                f"Supported tables: {SUPPORTED_TABLES}"
            )
