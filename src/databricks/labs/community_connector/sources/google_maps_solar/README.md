# Lakeflow Google Maps Solar Community Connector

This documentation provides setup instructions and reference information for the **Google Maps Solar** source connector, which ingests solar-potential data and geospatial raster layers from the [Google Maps Platform Solar API](https://developers.google.com/maps/documentation/solar/overview) (`https://solar.googleapis.com`, REST `v1`) into Databricks.

> **Read this first — the Solar API is a lookup API, not a collection API.**
> There is no endpoint that enumerates "all buildings". Every read is keyed by a location (latitude/longitude) that **you** supply as a table option. If no location is configured, the read fails with a configuration error rather than returning an empty table.

## Prerequisites

- **Google Cloud project** with **billing enabled**. The Solar API is a pay-as-you-go Google Maps Platform product and will not serve requests from a project without billing.
- **Solar API enabled** on that project (Google Cloud Console → **APIs & Services** → **Library** → "Solar API" → **Enable**).
- **API key** created in that project (**APIs & Services** → **Credentials** → **Create Credentials** → **API key**). Restricting the key to the Solar API is strongly recommended.
- **Query locations**: a list of latitude/longitude pairs for the buildings or areas you want data about. Google's imagery coverage is not global — locations outside covered regions return no data.
- **Network access**: the environment running the pipeline must be able to reach `https://solar.googleapis.com` and the signed `googleusercontent`-style download URLs the API returns for raster assets.
- **Lakeflow / Databricks environment**: a workspace where you can register a Lakeflow community connector and run ingestion pipelines.

## Setup

### Required Connection Parameters

To configure the connector, provide the following parameters in your connector options:

| Name | Type | Required | Description | Example |
|---|---|---|---|---|
| `api_key` | string | Yes | Google Maps Platform API key with the Solar API enabled. Sent as the `key` query parameter on every request. | `AIzaSy...` |
| `base_url` | string | No | Base URL for the Solar API. Defaults to `https://solar.googleapis.com`. Override only when routing through a proxy or a custom endpoint. | `https://solar-proxy.mycompany.com` |
| `externalOptionsAllowList` | string | Yes | Comma-separated list of table-specific option names allowed to pass through to the connector. This connector **requires** table-specific options (at minimum a query location), so this parameter must be set. | See the definitive list below. |

The full, definitive value for `externalOptionsAllowList` is:

```
locations,latitude,longitude,location.latitude,location.longitude,skip_not_found,requiredQuality,exactQualityRequired,experiments,additionalInsights,radiusMeters,view,pixelSizeMeters,layer_types,max_assets_per_location,asset_ids,layer_type
```

> **Note**: This connector uses **API key** authentication — there is no OAuth app to register, no browser sign-in, and no redirect URI to configure.

Several of the options above may also be supplied as **connection-level defaults** so you do not have to repeat them on every table. When the same option is set in both places, the table-level value wins. The options that support this are:

`locations`, `latitude`, `longitude`, `location.latitude`, `location.longitude`, `radiusMeters`, `requiredQuality`, `exactQualityRequired`, `experiments`, `skip_not_found`.

All other table-specific options (`view`, `pixelSizeMeters`, `additionalInsights`, `layer_types`, `max_assets_per_location`, `asset_ids`, `layer_type`) are read **per table only** and must be set under `table_configuration`.

### Obtaining the Required Parameters

**API key (`api_key`)**

1. Sign in to the [Google Cloud Console](https://console.cloud.google.com) and select (or create) a project.
2. Enable **billing** on the project. Solar API requests are rejected without it.
3. Go to **APIs & Services → Library**, search for **Solar API**, and click **Enable**.
4. Go to **APIs & Services → Credentials → Create Credentials → API key**.
5. Click **Edit API key** and, under **API restrictions**, restrict it to the **Solar API**. Application restrictions by IP are also recommended where your pipeline egress IPs are known.
6. Copy the generated key and store it securely. Use it as the `api_key` connection option.

**Query locations**

Collect the latitude/longitude of each address or site you want to analyze. If you only have street addresses, geocode them first (for example with the Google Geocoding API) and feed the resulting coordinates into the `locations` option. Coordinates are plain decimal degrees, e.g. `37.4450,-122.1390`.

**Base URL (`base_url`)** — leave unset unless your organization requires egress through a proxy that fronts `solar.googleapis.com`.

### Create a Unity Catalog Connection

A Unity Catalog connection for this connector can be created in two ways via the UI:

1. Follow the **Lakeflow Community Connector** UI flow from the **Add Data** page.
2. Select any existing Lakeflow Community Connector connection for this source or create a new one, supplying `api_key` (and optionally `base_url`).
3. Set `externalOptionsAllowList` to:
   `locations,latitude,longitude,location.latitude,location.longitude,skip_not_found,requiredQuality,exactQualityRequired,experiments,additionalInsights,radiusMeters,view,pixelSizeMeters,layer_types,max_assets_per_location,asset_ids,layer_type`

The connection can also be created using the standard Unity Catalog API.

## Supported Objects

The connector exposes a **static list** of three tables (the Solar API has no discovery endpoint). Use these names exactly as written, in lower snake case:

- `building_insights`
- `data_layers`
- `geo_tiff`

| Table | Description | Ingestion Type | Primary Key | Incremental Cursor |
|---|---|---|---|---|
| `building_insights` | Solar potential of the single building **closest** to each configured location: roof segments, sunshine quantiles, panel configurations, and financial analyses. | `snapshot` | `name` | n/a |
| `data_layers` | Metadata plus signed URLs for the downloadable raster layers (DSM, RGB, mask, annual flux, monthly flux, hourly shade) covering an area around each configured location. | `snapshot` | `query_latitude`, `query_longitude`, `query_radius_meters` (composite) | n/a |
| `geo_tiff` | The raw GeoTIFF raster bytes for each asset referenced by a `data_layers` result. One row per raster file. | `snapshot` | `asset_id` | n/a |

**Why everything is `snapshot`**: no Solar API endpoint accepts an "updated since" filter, and no response carries a record-modification timestamp or revision number. `imageryDate` and `imageryProcessedDate` describe the underlying *imagery*, not the record, and cannot be used as a server-side filter. Each pipeline run therefore re-reads the full result for every configured location. There is no delete feed, so delete synchronization is not supported for any table.

### Columns that need attention

**`building_insights`**

- `name` — the stable Google building resource id (e.g. `buildings/ChIJ...`) and the primary key. Two nearby query locations can resolve to the **same** building, which is expected: the lookup returns the *nearest known* building, which is not necessarily the building at the exact point you queried (querying a point in a parking lot may return the adjacent building).
- `solarPotential` — a deep nested struct holding `roofSegmentStats`, `solarPanels`, `solarPanelConfigs`, and `financialAnalyses` arrays. Nested objects are preserved as structs rather than flattened.
- `detectedArrays` — `null` unless you request `additionalInsights=DETECTED_ARRAYS`.
- Money-valued fields (inside `financialAnalyses`) are structs of `currencyCode` / `units` / `nanos`. Combine `units + nanos/1e9` for a decimal amount.
- Region-dependent incentive fields (`stateIncentive`, `utilityIncentive`, `lifetimeSrecTotal`, `leasingSavings`) are `null` where the corresponding program does not exist.

**`data_layers`**

- `query_latitude`, `query_longitude`, `query_radius_meters` are **connector-derived**: the API response carries no identifier of its own, so the request parameters are the row's only stable identity.
- `dsmUrl`, `rgbUrl`, `maskUrl`, `annualFluxUrl`, `monthlyFluxUrl`, `hourlyShadeUrls` are **signed URLs that expire roughly one hour** after the response is produced. Treat them as short-lived pointers, not durable links.
- `monthlyFluxUrl` and `hourlyShadeUrls` are `null` / empty when `radiusMeters > 175` or when a narrower `view` is requested. Always code downstream logic to treat them as optional.

**`geo_tiff`**

- `data` is a **binary column** holding the raw GeoTIFF file bytes (stored as bytes rather than base64 to avoid ~33% size inflation). Individual rasters can be several megabytes; see [Best Practices](#best-practices) before ingesting many locations.
- `layer_type` is connector-derived and is one of `dsm`, `rgb`, `mask`, `annual_flux`, `monthly_flux`, `hourly_shade`.
- `month_index` is `1`–`12` for `hourly_shade` rows only (one raster per month, January through December) and `null` for every other layer type.
- `asset_id` is the primary key but is **ephemeral** — it is derived from a signed URL that expires about an hour after it is minted, so every pipeline run produces new `asset_id` values for the same underlying rasters. See the note under [Special `table_configuration` options](#special-table_configuration-options) for how to get a stable key instead.
- `fetched_at` records when the connector downloaded the asset. Google's policy allows caching downloaded rasters for up to 30 days, after which they should be treated as stale and refreshed.
- Reading `geo_tiff` automatically resolves the current asset URLs for each location first, then downloads them immediately, so you do **not** need to ingest `data_layers` beforehand or paste URLs by hand. Both steps happen inside a single unit of work, which is what keeps the downloads inside the one-hour URL validity window.

## Table Configurations

### Source & Destination

These are set directly under each `table` object in the pipeline spec:

| Option | Required | Description |
|---|---|---|
| `source_table` | Yes | Table name in the source system |
| `destination_catalog` | No | Target catalog (defaults to pipeline's default) |
| `destination_schema` | No | Target schema (defaults to pipeline's default) |
| `destination_table` | No | Target table name (defaults to `source_table`) |

### Common `table_configuration` options

These are set inside the `table_configuration` map alongside any source-specific options:

| Option | Required | Description |
|---|---|---|
| `scd_type` | No | `SCD_TYPE_1` (default) or `SCD_TYPE_2`. Only applicable to tables with CDC or SNAPSHOT ingestion mode; APPEND_ONLY tables do not support this option. All three Solar tables are SNAPSHOT, so both values are available. |
| `primary_keys` | No | List of columns to override the connector's default primary keys |
| `sequence_by` | No | Column used to order records for SCD Type 2 change tracking |
| `cluster_by` | No | List of columns to cluster the destination Delta table by (Liquid Clustering). Consumed by the pipeline; not forwarded to the source. |

### Special `table_configuration` options

#### Location options (required for every table)

Every table needs at least one query location. Supply it either as a list or as a single pair. These may also be set once at the connection level as a default for all tables.

| Option | Type | Required | Description | Example |
|---|---|---|---|---|
| `locations` | string | Yes (or use `latitude`/`longitude`) | One or more `<lat>,<lng>` pairs separated by `;`. Takes precedence over `latitude`/`longitude`. Newlines are accepted in place of `;`. | `37.4450,-122.1390;40.7128,-74.0060` |
| `latitude` | number | Yes (if `locations` is not set) | Latitude of a single query point. `location.latitude` is accepted as an alias. | `37.4450` |
| `longitude` | number | Yes (if `locations` is not set) | Longitude of a single query point. `location.longitude` is accepted as an alias. | `-122.1390` |

#### Options shared by all tables

| Option | Type | Default | Description |
|---|---|---|---|
| `requiredQuality` | string | `HIGH` | Minimum acceptable imagery quality: `HIGH`, `MEDIUM`, `LOW`, or `BASE`. `BASE` is only available when `experiments` includes `EXPANDED_COVERAGE`. |
| `exactQualityRequired` | boolean | `false` | When `true`, only imagery of exactly `requiredQuality` is returned. When `false`, imagery of that quality **or better** is returned. |
| `experiments` | string | (unset) | Comma-separated pre-GA opt-ins. Currently only `EXPANDED_COVERAGE`, which widens geographic coverage and unlocks the `BASE` quality tier. |
| `skip_not_found` | boolean | `true` | When `true`, a location with no Google coverage yields **zero rows** instead of failing the read. Set to `false` to make missing coverage a hard error. |

#### `building_insights` only

| Option | Type | Default | Description |
|---|---|---|---|
| `additionalInsights` | string | (unset) | Comma-separated extras. Currently only `DETECTED_ARRAYS`, which populates the `detectedArrays` column with information about rooftop solar arrays already visible in the imagery. |

#### `data_layers` and `geo_tiff`

| Option | Type | Default | Description |
|---|---|---|---|
| `radiusMeters` | number | `100` | Radius around the query point to fetch. Up to 100 m is always allowed; beyond that the API requires `radiusMeters <= pixelSizeMeters * 1000`. Above 175 m, monthly-flux and hourly-shade layers are not returned at all. |
| `view` | string | `FULL_LAYERS` | Which layers to compute: `DSM_LAYER` (DSM only), `IMAGERY_LAYERS` (DSM + RGB + mask), `IMAGERY_AND_ANNUAL_FLUX_LAYERS`, `IMAGERY_AND_ALL_FLUX_LAYERS` (adds monthly flux), or `FULL_LAYERS` (everything, including the 12 hourly-shade rasters). |
| `pixelSizeMeters` | number | `0.1` | Minimum resolution in meters per pixel. Supported values: `0.1`, `0.25`, `0.5`, `1.0`. |

#### `geo_tiff` only

| Option | Type | Default | Description |
|---|---|---|---|
| `layer_types` | string | all six | Comma-separated subset of `dsm`, `rgb`, `mask`, `annual_flux`, `monthly_flux`, `hourly_shade`. An unrecognized value fails the read with a clear error. Use this to avoid downloading rasters you do not need. |
| `max_assets_per_location` | integer | `20` | Caps how many rasters are downloaded per location. A `FULL_LAYERS` read produces up to 17 assets (5 single rasters + 12 monthly hourly-shade rasters), so the default cap does not truncate a full read. |
| `asset_ids` | string | (unset) | Comma-separated asset ids to download **directly**, bypassing the automatic resolution step. Intended for targeted re-fetches only — ids expire about an hour after they are issued. |
| `layer_type` | string | `dsm` | The `layer_type` value to record on rows produced from `asset_ids`. Ignored unless `asset_ids` is set. |

> **Recommended for `geo_tiff`**: because `asset_id` changes on every run, leaving the default primary key in place makes each run append an entirely new set of rows. If you want the destination table to hold one row per raster and update in place, override the key:
> `"primary_keys": ["query_latitude", "query_longitude", "layer_type", "month_index"]`

## Data Type Mapping

| Solar API type | Example fields | Databricks type | Notes |
|---|---|---|---|
| `string` | `name`, `postalCode`, `regionCode`, `dsmUrl` | `STRING` | Includes resource names and signed URLs. |
| enum | `imageryQuality`, `orientation`, `detectionStatus` | `STRING` | The enum's string constant is preserved (e.g. `"HIGH"`), never an integer code. |
| `number` (double) | `areaMeters2`, `yearlyEnergyDcKwh`, `pitchDegrees` | `DOUBLE` | |
| `integer` | `panelsCount`, `maxArrayPanelsCount`, `segmentIndex` | `BIGINT` | `BIGINT` is used throughout in preference to 32-bit integers to avoid overflow. |
| `boolean` | `netMeteringAllowed`, `financiallyViable`, `leasesAllowed` | `BOOLEAN` | |
| `google.type.LatLng` | `center`, `boundingBox.sw`, `boundingBox.ne` | `STRUCT<latitude: DOUBLE, longitude: DOUBLE>` | |
| `google.type.Date` | `imageryDate`, `imageryProcessedDate`, `latestCaptureDate` | `STRUCT<year: BIGINT, month: BIGINT, day: BIGINT>` | Deliberately not a `DATE`: the underlying type permits partial dates, which would fail to coerce silently. |
| `google.type.Money` | `monthlyBill`, `federalIncentive`, `savingsYear20` | `STRUCT<currencyCode: STRING, units: BIGINT, nanos: BIGINT>` | `units` arrives as a string-encoded 64-bit integer on the wire and is parsed into `BIGINT`. |
| array of scalars | `sunshineQuantiles`, `hourlyShadeUrls` | `ARRAY<DOUBLE>`, `ARRAY<STRING>` | |
| array of objects | `roofSegmentStats`, `solarPanels`, `financialAnalyses` | `ARRAY<STRUCT<...>>` | Nested structures are preserved, not flattened into side tables. |
| nested object | `solarPotential`, `financialDetails`, `detectedArrays` | `STRUCT<...>` | An absent or empty object is surfaced as `NULL`, never as an empty struct. |
| raw binary body | `geo_tiff.data` | `BINARY` | Raw GeoTIFF bytes, not base64 text. |
| HTTP timestamp (connector-derived) | `geo_tiff.fetched_at` | `TIMESTAMP` | UTC instant at which the raster was downloaded. |

## How to Run

### Step 1: Clone/Copy the Source Connector Code

Follow the Lakeflow Community Connector UI, which will guide you through setting up a pipeline using the selected source connector code.

### Step 2: Configure Your Pipeline

1. Update the `pipeline_spec` in the main pipeline file (e.g., `ingest.py`).
2. Set the query location(s) for each table under `table_configuration`, along with any layer or quality options you need.

```json
{
  "pipeline_spec": {
    "connection_name": "google_maps_solar_connection",
    "object": [
      {
        "table": {
          "source_table": "building_insights",
          "table_configuration": {
            "locations": "37.4450,-122.1390;40.7128,-74.0060",
            "requiredQuality": "HIGH",
            "additionalInsights": "DETECTED_ARRAYS"
          }
        }
      },
      {
        "table": {
          "source_table": "data_layers",
          "table_configuration": {
            "locations": "37.4450,-122.1390;40.7128,-74.0060",
            "radiusMeters": "100",
            "view": "FULL_LAYERS",
            "pixelSizeMeters": "0.5"
          }
        }
      },
      {
        "table": {
          "source_table": "geo_tiff",
          "table_configuration": {
            "locations": "37.4450,-122.1390",
            "radiusMeters": "100",
            "view": "IMAGERY_AND_ANNUAL_FLUX_LAYERS",
            "layer_types": "dsm,rgb,annual_flux",
            "max_assets_per_location": "5",
            "primary_keys": ["query_latitude", "query_longitude", "layer_type", "month_index"]
          }
        }
      }
    ]
  }
}
```

If most of your tables share the same locations and quality settings, put `locations`, `radiusMeters`, `requiredQuality`, `exactQualityRequired`, `experiments`, and `skip_not_found` on the **connection** instead and omit them per table; a table that does set them overrides the connection value.

3. (Optional) Customize the source connector code if needed for special use cases.

### Step 3: Run and Schedule the Pipeline

Run the pipeline using your standard Lakeflow / Databricks orchestration (for example, a scheduled job). Every run is a full refresh for the configured locations — there is no incremental mode to enable.

Because the underlying imagery is refreshed on Google's own irregular schedule (typically no more than a few times a year for a given area), a **daily or weekly** schedule is usually more than sufficient. Sub-daily schedules mostly re-buy the same data.

#### Best Practices

- **Start small**: validate with one location and `building_insights` only before scaling out. Confirm the returned `name` and `center` match the building you expect.
- **Every run is billed**: successful `building_insights` and `data_layers` calls are chargeable Google Maps Platform requests, and cost scales linearly with (number of locations x number of runs). Schedule conservatively and prefer weekly refreshes unless you have a reason to go faster.
- **Respect the quota**: Google enforces roughly **600 queries per minute** shared across the building-insights and data-layers endpoints. The connector retries HTTP 429 and 5xx responses up to four times with exponential backoff and honors any `Retry-After` header, but sustained overruns will still slow the pipeline. Split very large location lists across multiple pipelines or schedules rather than one enormous run.
- **Note that 404s still cost quota**: requests that return no coverage are not billed but *do* count against the queries-per-minute quota.
- **Keep `geo_tiff` narrow**: a `FULL_LAYERS` read downloads up to 17 rasters per location, each potentially several megabytes. Use `layer_types` to fetch only the layers you actually analyze, raise `pixelSizeMeters` when full resolution is not needed, and cap with `max_assets_per_location`. Ingesting hundreds of locations at `FULL_LAYERS` will produce a very large Delta table.
- **Separate `geo_tiff` from the rest**: because of its size and cost profile, it is usually worth running the binary table on its own, less frequent schedule than `building_insights`.
- **Parallelism comes from locations**: the connector splits work by location, so a run with many locations parallelizes across the cluster automatically. A single-location table will not parallelize regardless of cluster size.
- **Mind the radius interactions**: `radiusMeters > 175` silently drops monthly-flux and hourly-shade layers, and narrower `view` values drop them too. If those layers are missing, check these two options first.
- **Don't chain `geo_tiff` manually**: signed URLs expire in about an hour, so copying URLs out of a `data_layers` table into `asset_ids` for a later run will fail. Let `geo_tiff` resolve its own assets.

#### Troubleshooting

**Common Issues:**

- **"a query location is required" error on every table**: no location was configured. Set `locations` (or both `latitude` and `longitude`) either on the table or on the connection. This is intentional — the connector will not guess a default location, because doing so would silently ingest data about the wrong building.
- **Location options appear to be ignored**: confirm the option names are present in `externalOptionsAllowList` on the Unity Catalog connection. Options not on that list are stripped before reaching the connector.
- **`Invalid entry ... in 'locations'`**: each entry must be exactly `<latitude>,<longitude>`, with entries separated by `;`. Check for a stray comma or a missing coordinate.
- **HTTP 403 / `PERMISSION_DENIED` / `REQUEST_DENIED`**: the API key is wrong, the Solar API is not enabled on the key's project, billing is not enabled, or an API/IP restriction on the key is blocking the request. Verify all four in the Google Cloud Console.
- **HTTP 429**: the 600 QPM shared quota was exceeded. The connector backs off and retries automatically; if failures persist, reduce the number of locations per run or spread runs out over time.
- **Empty table for some or all locations**: Google returned `NOT_FOUND` because it has no imagery coverage there. This is normal for multi-location reads and is skipped silently by default. Set `skip_not_found` to `false` to turn it into a hard failure while you diagnose, or try `requiredQuality: "MEDIUM"` / `"LOW"`, or add `experiments: "EXPANDED_COVERAGE"` to widen coverage.
- **`detectedArrays` is always null**: it is only populated when `additionalInsights` is set to `DETECTED_ARRAYS`.
- **`monthlyFluxUrl` / `hourlyShadeUrls` are null**: either `radiusMeters` exceeds 175 or `view` is narrower than `IMAGERY_AND_ALL_FLUX_LAYERS` (monthly flux) / `FULL_LAYERS` (hourly shade).
- **`geo_tiff` returns fewer rows than expected**: check `layer_types`, `max_assets_per_location`, and the `view` / `radiusMeters` interactions above — the connector can only download layers the API actually returned.
- **`geo_tiff` table grows on every run**: expected with the default `asset_id` key, which is regenerated each run. Override `primary_keys` with `["query_latitude", "query_longitude", "layer_type", "month_index"]` for a stable, updatable key.
- **`building_insights` returns a neighboring building**: the lookup returns the *nearest known* building, not necessarily the one at the exact coordinate. Refine the coordinate toward the roof centroid of the target building.
- **Downstream jobs struggle with the binary column**: `geo_tiff.data` holds whole raster files. Read it with a GeoTIFF-aware library (for example `rasterio` or GDAL) after writing the bytes out, and avoid `SELECT *` on that table in interactive queries.

## References

- Connector implementation: `src/databricks/labs/community_connector/sources/google_maps_solar/google_maps_solar.py`
- Connector schemas: `src/databricks/labs/community_connector/sources/google_maps_solar/google_maps_solar_schemas.py`
- Connector API research notes: `src/databricks/labs/community_connector/sources/google_maps_solar/google_maps_solar_api_doc.md`
- Official Google Maps Platform Solar API documentation:
  - Overview — `https://developers.google.com/maps/documentation/solar/overview`
  - Get an API key — `https://developers.google.com/maps/documentation/solar/get-api-key`
  - Building Insights guide — `https://developers.google.com/maps/documentation/solar/building-insights`
  - Data Layers guide — `https://developers.google.com/maps/documentation/solar/data-layers`
  - REST reference: `buildingInsights.findClosest` — `https://developers.google.com/maps/documentation/solar/reference/rest/v1/buildingInsights/findClosest`
  - REST reference: `dataLayers.get` — `https://developers.google.com/maps/documentation/solar/reference/rest/v1/dataLayers/get`
  - REST reference: `geoTiff.get` — `https://developers.google.com/maps/documentation/solar/reference/rest/v1/geoTiff/get`
  - `ImageryQuality` enum — `https://developers.google.com/maps/documentation/solar/reference/rest/v1/ImageryQuality`
  - Usage and billing (600 QPM quota, SKU tiers) — `https://developers.google.com/maps/documentation/solar/usage-and-billing`
