"""Lakeflow community connector for the Google Maps Platform Solar API.

The Solar API is a *lookup* API, not a collection API.  It exposes three
single-resource GET endpoints, all keyed by a caller-supplied location:

| Table               | Endpoint                        | Ingestion | Cursor |
|---------------------|---------------------------------|-----------|--------|
| ``building_insights`` | ``buildingInsights:findClosest`` | snapshot | —      |
| ``data_layers``       | ``dataLayers:get``               | snapshot | —      |
| ``geo_tiff``          | ``geoTiff:get``                  | snapshot | —      |

Consequences that shape this implementation:

* **No pagination.**  Every call returns exactly one resource — there is no
  page token, ``pageSize`` or ``nextPageToken`` anywhere in the API.
* **No incremental cursor.**  Nothing accepts an ``updatedSince`` filter and
  no response carries a modification timestamp, so all three tables are
  ``snapshot`` and ``read_table`` returns an empty offset.
* **The location is an input, not a discovery result.**  There is no way to
  enumerate "all buildings"; the caller must supply the lat/lng to query via
  table options.  See "Table options" below.
* **``geo_tiff`` is chained under ``data_layers``.**  Its asset ids live
  inside the signed URLs returned by ``dataLayers:get`` and expire ~1 hour
  later, so each ``geo_tiff`` read re-runs ``dataLayers:get`` for its
  location and immediately downloads the referenced rasters.

Partitioning
------------
The connector implements :class:`SupportsPartition` (batch partitioning only,
no ``SupportsPartitionedStream``).  There is no time-range filter and no
cursor to split a stream on, so partitioned *streaming* is meaningless here.
What does parallelise well is the location fan-out: when the user asks for
many locations, each location is an independent, equally-sized unit of work,
so ``get_partitions`` emits one partition per location and
``read_partition`` performs that location's API calls on an executor.  For
``geo_tiff`` this also keeps the ``dataLayers:get`` call and its GeoTIFF
downloads inside a single task, which matters because the signed URLs expire.

Authentication
--------------
Connection options:

* ``api_key`` (required) — Google Maps Platform API key, sent as the ``key``
  query parameter on every request.
* ``base_url`` (optional) — defaults to ``https://solar.googleapis.com``.

Table options
-------------
Location (required; may also be given at connection level as a default for
every table):

* ``locations`` — one or more ``"<lat>,<lng>"`` pairs separated by ``;``,
  e.g. ``"37.4450,-122.1390;40.7128,-74.0060"``.  Takes precedence.
* ``latitude`` / ``longitude`` — a single location.  ``location.latitude`` /
  ``location.longitude`` are accepted as aliases (matching the API's own
  parameter names).

``building_insights``: ``requiredQuality`` (default ``HIGH``),
``exactQualityRequired``, ``experiments``, ``additionalInsights``.

``data_layers`` and ``geo_tiff``: ``radiusMeters`` (default ``100``),
``view`` (default ``FULL_LAYERS``), ``requiredQuality``, ``pixelSizeMeters``,
``exactQualityRequired``, ``experiments``.

``geo_tiff`` additionally accepts ``layer_types`` (comma-separated subset of
``dsm,rgb,mask,annual_flux,monthly_flux,hourly_shade``),
``max_assets_per_location`` (default ``20``), and ``asset_ids`` (comma-
separated ids fetched directly, bypassing the ``dataLayers:get`` chain).

``skip_not_found`` (default ``true``) makes a ``NOT_FOUND`` response for a
location yield zero rows instead of failing the read — Google returns 404
wherever it has no imagery coverage, which is normal for a multi-location
read.
"""

import time
from datetime import datetime, timezone
from typing import Any, Iterator, Sequence
from urllib.parse import parse_qs, quote, urlsplit

import requests
from requests.exceptions import RequestException
from pyspark.sql.types import StructType

from databricks.labs.community_connector.interface import (
    LakeflowConnect,
    SupportsPartition,
)
from databricks.labs.community_connector.sources.google_maps_solar.google_maps_solar_schemas import (
    DEFAULT_BASE_URL,
    DEFAULT_TIMEOUT,
    GEO_TIFF_ARRAY_FIELD,
    GEO_TIFF_ARRAY_LAYER,
    GEO_TIFF_LAYER_TYPES,
    GEO_TIFF_SCALAR_LAYERS,
    GEO_TIFF_TIMEOUT,
    INITIAL_BACKOFF,
    MAX_RETRIES,
    PATH_BUILDING_INSIGHTS,
    PATH_DATA_LAYERS,
    PATH_GEO_TIFF,
    RETRIABLE_STATUS_CODES,
    TABLE_BUILDING_INSIGHTS,
    TABLE_DATA_LAYERS,
    TABLE_GEO_TIFF,
    TABLE_METADATA,
    TABLE_SCHEMAS,
    TABLES,
)

_TRUTHY = {"true", "t", "yes", "y", "1"}


class GoogleMapsSolarLakeflowConnect(LakeflowConnect, SupportsPartition):
    """LakeflowConnect implementation for the Google Maps Platform Solar API."""

    def __init__(self, options: dict[str, str]) -> None:
        super().__init__(options)
        self._api_key = options.get("api_key") or options.get("key")
        if not self._api_key:
            raise ValueError(
                "Google Maps Solar connector requires 'api_key' in options "
                "(a Google Maps Platform API key with the Solar API enabled)"
            )
        self._base_url = (options.get("base_url") or DEFAULT_BASE_URL).rstrip("/")

    # ----- LakeflowConnect ------------------------------------------------

    def list_tables(self) -> list[str]:
        """Static table list — the Solar API has no discovery endpoint."""
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
        metadata = dict(TABLE_METADATA[table_name])
        metadata["primary_keys"] = list(metadata["primary_keys"])
        return metadata

    def read_table(
        self, table_name: str, start_offset: dict, table_options: dict[str, str]
    ) -> tuple[Iterator[dict], dict]:
        """Single-driver snapshot read across every configured location.

        All three tables are full-refresh, so the returned offset is always
        empty: there is nothing to checkpoint and nothing to resume from.
        """
        self._validate_table(table_name)
        locations = self._resolve_locations(table_options)

        records: list[dict] = []
        for latitude, longitude in locations:
            records.extend(
                self._read_location(table_name, latitude, longitude, table_options)
            )
        return iter(records), {}

    # ----- SupportsPartition ----------------------------------------------

    def get_partitions(
        self, table_name: str, table_options: dict[str, str]
    ) -> Sequence[dict]:
        """One partition per configured location.

        Each location costs the same number of API calls, so the partitions
        are naturally balanced.  Descriptors carry only primitives so Spark
        can ship them to executors as JSON.
        """
        self._validate_table(table_name)
        return [
            {"latitude": latitude, "longitude": longitude}
            for latitude, longitude in self._resolve_locations(table_options)
        ]

    def read_partition(
        self, table_name: str, partition: dict, table_options: dict[str, str]
    ) -> Iterator[dict]:
        """Read one location's records.  Runs on a Spark executor.

        Self-contained: the HTTP calls are issued with ``requests`` directly
        (no cached ``Session``) and every credential comes from
        ``self.options``, so no driver-side state is required.
        """
        self._validate_table(table_name)
        latitude = float(partition["latitude"])
        longitude = float(partition["longitude"])
        return iter(
            self._read_location(table_name, latitude, longitude, table_options)
        )

    # ----- per-table readers ----------------------------------------------

    def _read_location(
        self,
        table_name: str,
        latitude: float,
        longitude: float,
        table_options: dict[str, str],
    ) -> list[dict]:
        if table_name == TABLE_BUILDING_INSIGHTS:
            return self._read_building_insights(latitude, longitude, table_options)
        if table_name == TABLE_DATA_LAYERS:
            return self._read_data_layers(latitude, longitude, table_options)
        return self._read_geo_tiff(latitude, longitude, table_options)

    def _read_building_insights(
        self, latitude: float, longitude: float, table_options: dict[str, str]
    ) -> list[dict]:
        params = self._location_params(latitude, longitude)
        self._add_quality_params(params, table_options)
        _add_repeated(params, "additionalInsights", table_options.get("additionalInsights"))

        payload = self._get_json(
            PATH_BUILDING_INSIGHTS, params, table_options, DEFAULT_TIMEOUT
        )
        if payload is None:
            return []
        # ``detectedArrays`` is absent unless additionalInsights was requested;
        # a StructType field that is missing must be None, never {}.
        payload.setdefault("detectedArrays", None)
        return [payload]

    def _read_data_layers(
        self, latitude: float, longitude: float, table_options: dict[str, str]
    ) -> list[dict]:
        radius = self._radius_meters(table_options)
        payload = self._fetch_data_layers(latitude, longitude, radius, table_options)
        if payload is None:
            return []

        # The response carries no identifier of its own — the request
        # parameters are the row's only stable identity.
        payload["query_latitude"] = latitude
        payload["query_longitude"] = longitude
        payload["query_radius_meters"] = radius
        return [payload]

    def _read_geo_tiff(
        self, latitude: float, longitude: float, table_options: dict[str, str]
    ) -> list[dict]:
        """Resolve this location's GeoTIFF assets, then download each one.

        The signed URLs minted by ``dataLayers:get`` expire ~1 hour later, so
        the resolve and the downloads deliberately happen back to back inside
        one unit of work rather than across pipeline stages.
        """
        wanted = self._wanted_layer_types(table_options)
        max_assets = int(table_options.get("max_assets_per_location", "20"))

        assets = self._explicit_assets(table_options, wanted)
        if assets is None:
            radius = self._radius_meters(table_options)
            payload = self._fetch_data_layers(
                latitude, longitude, radius, table_options
            )
            if payload is None:
                return []
            assets = self._assets_from_data_layers(payload, wanted)

        records = []
        for layer_type, month_index, url_value in assets[:max_assets]:
            record = self._download_geo_tiff(
                layer_type, month_index, url_value, latitude, longitude, table_options
            )
            if record is not None:
                records.append(record)
        return records

    # ----- geo_tiff helpers -----------------------------------------------

    @staticmethod
    def _wanted_layer_types(table_options: dict[str, str]) -> set:
        raw = table_options.get("layer_types")
        if not raw:
            return set(GEO_TIFF_LAYER_TYPES)
        wanted = {part.strip() for part in raw.split(",") if part.strip()}
        unknown = wanted - set(GEO_TIFF_LAYER_TYPES)
        if unknown:
            raise ValueError(
                f"Unknown layer_types {sorted(unknown)}; "
                f"expected a subset of {GEO_TIFF_LAYER_TYPES}"
            )
        return wanted

    @staticmethod
    def _explicit_assets(
        table_options: dict[str, str], wanted: set
    ) -> list[tuple] | None:
        """Assets from the ``asset_ids`` option, or None to chain via data_layers."""
        raw = table_options.get("asset_ids")
        if not raw:
            return None
        layer_type = table_options.get("layer_type") or "dsm"
        if layer_type not in wanted:
            return []
        return [
            (layer_type, None, part.strip())
            for part in raw.split(",")
            if part.strip()
        ]

    @staticmethod
    def _assets_from_data_layers(payload: dict, wanted: set) -> list[tuple]:
        """Flatten a dataLayers response into ``(layer_type, month_index, url)``.

        ``monthlyFluxUrl`` and ``hourlyShadeUrls`` are omitted by the API for
        narrow ``view`` settings or ``radiusMeters > 175``, so every field is
        treated as optional.
        """
        assets: list[tuple] = []
        for field_name, layer_type in GEO_TIFF_SCALAR_LAYERS.items():
            if layer_type not in wanted:
                continue
            url_value = payload.get(field_name)
            if url_value:
                assets.append((layer_type, None, url_value))

        if GEO_TIFF_ARRAY_LAYER in wanted:
            hourly = payload.get(GEO_TIFF_ARRAY_FIELD) or []
            if isinstance(hourly, list):
                for index, url_value in enumerate(hourly):
                    if url_value:
                        # 1-based month index, Jan..Dec.
                        assets.append((GEO_TIFF_ARRAY_LAYER, index + 1, url_value))
        return assets

    def _download_geo_tiff(
        self,
        layer_type: str,
        month_index: int | None,
        url_value: str,
        latitude: float,
        longitude: float,
        table_options: dict[str, str],
    ) -> dict | None:
        request_url, params, asset_id, source_url = self._geo_tiff_target(url_value)
        params["key"] = self._api_key

        resp = self._request_with_retry(request_url, params, GEO_TIFF_TIMEOUT)
        if resp.status_code == 404 and self._skip_not_found(table_options):
            return None
        if resp.status_code != 200:
            raise RuntimeError(
                f"geoTiff:get failed for asset {asset_id!r}: "
                f"HTTP {resp.status_code} {resp.text[:200]}"
            )

        # Plain REST returns the raster bytes as the response body — there is
        # no JSON ``{contentType, data}`` envelope at the wire level (that
        # shape only exists inside Google's generated client libraries).
        return {
            "asset_id": asset_id,
            "layer_type": layer_type,
            "month_index": month_index,
            "content_type": resp.headers.get("Content-Type"),
            "data": resp.content,
            "source_url": source_url,
            "query_latitude": latitude,
            "query_longitude": longitude,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

    def _geo_tiff_target(self, url_value: str) -> tuple[str, dict, str, str]:
        """Resolve a dataLayers URL field into a fetchable request.

        Live responses hand back a fully-formed signed URL, which is used
        verbatim (only ``key`` is appended).  Anything that is not an
        absolute URL is treated as a bare asset id and turned into a
        ``geoTiff:get?id=...`` request — that is what makes the table
        readable both from the ``asset_ids`` option and against the
        in-process source simulator.
        """
        text = str(url_value)
        if text.lower().startswith(("http://", "https://")):
            query = parse_qs(urlsplit(text).query)
            asset_id = (query.get("id") or [text])[0]
            return text, {}, asset_id, text

        asset_id = text
        request_url = f"{self._base_url}{PATH_GEO_TIFF}"
        source_url = f"{request_url}?id={quote(asset_id, safe='')}"
        return request_url, {"id": asset_id}, asset_id, source_url

    # ----- shared request helpers -----------------------------------------

    def _fetch_data_layers(
        self,
        latitude: float,
        longitude: float,
        radius: float,
        table_options: dict[str, str],
    ) -> dict | None:
        params = self._location_params(latitude, longitude)
        params["radiusMeters"] = radius
        params["view"] = table_options.get("view", "FULL_LAYERS")
        if "pixelSizeMeters" in table_options:
            params["pixelSizeMeters"] = table_options["pixelSizeMeters"]
        self._add_quality_params(params, table_options)
        return self._get_json(PATH_DATA_LAYERS, params, table_options, DEFAULT_TIMEOUT)

    def _get_json(
        self,
        path: str,
        params: dict,
        table_options: dict[str, str],
        timeout: int,
    ) -> dict | None:
        """GET a JSON endpoint.  Returns None for a skippable ``NOT_FOUND``."""
        params = dict(params)
        params["key"] = self._api_key
        url = f"{self._base_url}{path}"

        resp = self._request_with_retry(url, params, timeout)
        if resp.status_code == 404 and self._skip_not_found(table_options):
            # Google returns NOT_FOUND wherever it has no coverage.  Such
            # requests are not billed but do count against the QPM quota.
            return None
        if resp.status_code != 200:
            raise RuntimeError(
                f"GET {path} failed: HTTP {resp.status_code} {resp.text[:300]}"
            )
        return _drop_empty_objects(_as_object(resp.json())) or None

    def _request_with_retry(
        self, url: str, params: dict, timeout: int
    ) -> requests.Response:
        """GET with exponential backoff on 429/5xx.

        A fresh ``requests.get`` is used per call rather than a cached
        ``Session`` so the connector instance stays picklable when Spark
        ships it to executors for partitioned reads.
        """
        backoff = INITIAL_BACKOFF
        resp = None
        last_exc: RequestException | None = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = requests.get(url, params=params, timeout=timeout)
            except RequestException as exc:
                last_exc = exc
            else:
                if resp.status_code not in RETRIABLE_STATUS_CODES:
                    return resp
            if attempt < MAX_RETRIES - 1:
                sleep_for = backoff
                if resp is not None:
                    retry_after = (resp.headers.get("Retry-After") or "").strip()
                    if retry_after:
                        try:
                            sleep_for = max(sleep_for, float(retry_after))
                        except ValueError:
                            pass
                time.sleep(sleep_for)
                backoff *= 2

        if resp is not None:
            return resp
        raise RuntimeError(f"GET {url} failed after {MAX_RETRIES} attempts: {last_exc}")

    # ----- option plumbing -------------------------------------------------

    def _validate_table(self, table_name: str) -> None:
        if table_name not in TABLES:
            raise ValueError(
                f"Table '{table_name}' is not supported. Supported tables: {TABLES}"
            )

    def _option(self, table_options: dict[str, str], *names: str) -> str | None:
        """First non-empty value among *names*, table options winning."""
        for source in (table_options or {}, self.options or {}):
            for name in names:
                value = source.get(name)
                if value not in (None, ""):
                    return value
        return None

    def _resolve_locations(
        self, table_options: dict[str, str]
    ) -> list[tuple[float, float]]:
        """Parse the configured query location(s).

        There is no discovery endpoint, so a location is mandatory input.  A
        missing one is a configuration error, not an empty result — defaulting
        it would silently ingest data about the wrong building.
        """
        raw = self._option(table_options, "locations")
        if raw:
            locations = []
            for chunk in str(raw).replace("\n", ";").split(";"):
                chunk = chunk.strip()
                if not chunk:
                    continue
                parts = chunk.split(",")
                if len(parts) != 2:
                    raise ValueError(
                        f"Invalid entry {chunk!r} in 'locations'; expected "
                        "'<latitude>,<longitude>' pairs separated by ';'"
                    )
                locations.append((float(parts[0]), float(parts[1])))
            if locations:
                return locations

        latitude = self._option(table_options, "latitude", "location.latitude")
        longitude = self._option(table_options, "longitude", "location.longitude")
        if latitude is None or longitude is None:
            raise ValueError(
                "The Solar API is a location lookup with no discovery endpoint, "
                "so a query location is required. Set table option 'locations' "
                "(e.g. '37.4450,-122.1390') or both 'latitude' and 'longitude'."
            )
        return [(float(latitude), float(longitude))]

    @staticmethod
    def _location_params(latitude: float, longitude: float) -> dict:
        return {
            "location.latitude": latitude,
            "location.longitude": longitude,
        }

    def _radius_meters(self, table_options: dict[str, str]) -> float:
        return float(self._option(table_options, "radiusMeters") or 100)

    def _add_quality_params(
        self, params: dict, table_options: dict[str, str]
    ) -> None:
        params["requiredQuality"] = (
            self._option(table_options, "requiredQuality") or "HIGH"
        )
        exact = self._option(table_options, "exactQualityRequired")
        if exact is not None:
            params["exactQualityRequired"] = str(exact).lower() in _TRUTHY
        _add_repeated(params, "experiments", self._option(table_options, "experiments"))

    def _skip_not_found(self, table_options: dict[str, str]) -> bool:
        value = self._option(table_options, "skip_not_found")
        if value is None:
            return True
        return str(value).lower() in _TRUTHY


# ----- module-level helpers -----------------------------------------------


def _add_repeated(params: dict, name: str, raw: str | None) -> None:
    """Attach a repeated enum query param (``experiments[]``-style)."""
    if not raw:
        return
    values = [part.strip() for part in str(raw).split(",") if part.strip()]
    if values:
        params[name] = values


def _as_object(payload: Any) -> dict:
    """Normalise a single-resource response body to a dict.

    Each Solar API endpoint returns one object.  The in-process source
    simulator may serve a corpus array for the same URL, so a list is
    tolerated by taking its first element rather than failing the read.
    """
    if isinstance(payload, list):
        first = payload[0] if payload else {}
        return dict(first) if isinstance(first, dict) else {}
    if isinstance(payload, dict):
        return dict(payload)
    return {}


def _drop_empty_objects(value: Any) -> Any:
    """Recursively replace empty JSON objects with ``None``.

    The framework's StructType parser rejects ``{}`` outright and requires
    ``None`` for an absent struct.  Google normally omits empty messages
    entirely, but proto-to-JSON transcoding can emit ``{}`` for a present-
    but-empty message (e.g. a region with no ``leasingSavings``), so this
    normalises the payload once at the boundary.
    """
    if isinstance(value, dict):
        cleaned = {key: _drop_empty_objects(val) for key, val in value.items()}
        return cleaned or None
    if isinstance(value, list):
        return [_drop_empty_objects(item) for item in value]
    return value
