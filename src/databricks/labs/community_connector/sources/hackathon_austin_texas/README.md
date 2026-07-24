# Lakeflow Hackathon Austin Texas Community Connector

This documentation describes how to configure and use the **Hackathon Austin Texas** Lakeflow community connector to ingest data from the **City of Austin, Texas Open Data Portal** (`data.austintexas.gov`) into Databricks.

The portal is a **Socrata Open Data API (SODA)** deployment. Each supported table maps to a public Socrata dataset served at `/resource/{4x4}.json`, where `{4x4}` is the dataset's stable Socrata ID (for example `dpvb-c5fy`). All data is public: no login, OAuth flow, or per-dataset credential is required.


## Prerequisites

- **Network access**: The environment running the connector must be able to reach `https://data.austintexas.gov`.
- **Socrata app token (optional, recommended)**: A free Socrata app token used to lift the connector out of the shared, per-IP rate limit. The connector reads **public** data without any token, but anonymous requests are throttled at a lower shared rate and are more likely to receive `429 Too Many Requests`. Supplying a token gives requests their own pool and is effectively unthrottled for legitimate use.
- **Lakeflow / Databricks environment**: A workspace where you can register a Lakeflow community connector and run ingestion pipelines.

No account, password, or API key is required to run this connector against the public City of Austin datasets.


## Setup

### Required Connection Parameters

Provide the following **connection-level** options when configuring the connector. All connection parameters are **optional** — the connector works out of the box against the public portal with no configuration.

| Name       | Type   | Required | Description                                                                                                                                                                      | Example                        |
|------------|--------|----------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------|
| `app_token`| string | no       | Socrata app token, sent as the `X-App-Token` HTTP header. Not required for public data, but lifts the connector out of the shared per-IP rate limit. Stored as a secret.         | `abcd1234EXAMPLETOKEN5678`     |
| `base_url` | string | no       | Base URL for the Socrata portal. Defaults to `https://data.austintexas.gov`. Only override if the City of Austin moves or changes its portal URL.                               | `https://data.austintexas.gov` |
| `page_size`| string | no       | Rows fetched per page during pagination. Defaults to `1000`; Socrata caps a single page at `50000`. Larger values reduce request overhead; smaller values give finer progress. | `5000`                         |

This connector supports table-specific options (see [Table Configurations](#table-configurations)). Because those options are provided per table, the `externalOptionsAllowList` connection option is **required** and must list every allowed option name:

| Name                        | Type   | Required | Description                                                                                                                         | Value                          |
|-----------------------------|--------|----------|-----------------------------------------------------------------------------------------------------------------------------------|--------------------------------|
| `externalOptionsAllowList`  | string | yes      | Comma-separated list of table-specific option names allowed to pass through to the connector.                                      | `window_days,lookback_minutes` |

The full, definitive list of supported table-specific options for `externalOptionsAllowList` is:
`window_days,lookback_minutes`

> **Note**: Table-specific options such as `window_days` and `lookback_minutes` are **not** connection parameters. They are provided per table via `table_configuration` in the pipeline specification. These option names must be included in `externalOptionsAllowList` for the connection to allow them.

### Obtaining a Socrata App Token (optional)

An app token is not required, but is recommended for any regular or high-volume ingestion to avoid throttling:

1. Register a free account at `https://data.austintexas.gov` (any Socrata / Tyler Data & Insights account works — app tokens are account-scoped, not dataset-scoped).
2. Open your account's **Developer Settings**.
3. Create a new **App Token**.
4. Copy the generated token string and store it securely. Use it as the `app_token` connection option.

The app token is a single long-lived static string. There is no `client_id` / `client_secret` / `refresh_token` exchange for this source.

### Create a Unity Catalog Connection

A Unity Catalog connection for this connector can be created in two ways via the UI:

1. Follow the **Lakeflow Community Connector** UI flow from the **Add Data** page.
2. Select any existing Lakeflow Community Connector connection for this source or create a new one. Optionally set `app_token` for elevated rate limits.
3. Set `externalOptionsAllowList` to `window_days,lookback_minutes` (required for this connector to pass table-specific options).

The connection can also be created using the standard Unity Catalog API.


## Supported Objects

The connector exposes a **static list** of seven curated City of Austin datasets. Use the exact table names (case-sensitive) shown below:

- `transportation_and_mobility`
- `green_building_ratings_aggregate`
- `solar_program_current_incentive_levels_and_available_capacity`
- `green_building_energy_code_compliance`
- `green_building_developer_agreements`
- `coa_energy_codes_timeline`
- `discount_monthly_new_enrollment_by_zip`

### Object summary, primary keys, and ingestion mode

All seven tables are ingested as **`cdc`** (incremental upserts, no delete feed). Every Socrata dataset exposes three system fields that the connector surfaces under colon-free Spark column names:

- `:id` → `system_id`
- `:created_at` → `system_created_at`
- `:updated_at` → `system_updated_at`

`system_updated_at` is the **universal incremental cursor** for every table (see [Incremental Sync](#incremental-sync-strategy)). Where a dataset has no reliable single-column natural key, the connector falls back to the Socrata surrogate `system_id`.

| Table                                                            | Socrata 4x4 | Description                                                                                       | Ingestion Type | Primary Key      | Incremental Cursor |
|-----------------------------------------------------------------|-------------|--------------------------------------------------------------------------------------------------|----------------|------------------|--------------------|
| `transportation_and_mobility`                                   | `28ys-ieqv` | Catalog of datasets published by Austin Transportation and Public Works (one row per dataset)     | `cdc`          | `id`             | `system_updated_at`|
| `green_building_ratings_aggregate`                              | `dpvb-c5fy` | Austin Energy Green Building rating and resource-savings rollups, per building class per fiscal year | `cdc`        | `system_id`      | `system_updated_at`|
| `solar_program_current_incentive_levels_and_available_capacity` | `vxq2-zjmn` | Austin Energy Solar Rebate Program incentive tiers and available capacity                        | `cdc`          | `program`        | `system_updated_at`|
| `green_building_energy_code_compliance`                         | `i7vh-fpaj` | Permit counts and estimated energy-code savings, per fiscal year                                 | `cdc`          | `fiscal_year`    | `system_updated_at`|
| `green_building_developer_agreements`                           | `63mb-dbmj` | Developer / PUD agreements requiring a Green Building rating (geospatial)                         | `cdc`          | `gis_id`         | `system_updated_at`|
| `coa_energy_codes_timeline`                                     | `xn7p-rafv` | Historical timeline of City Council energy-code adoptions                                         | `cdc`          | `system_id`      | `system_updated_at`|
| `discount_monthly_new_enrollment_by_zip`                        | `guem-bnpv` | Austin Energy Customer Assistance Program new discount enrollments by ZIP, FY 2024 (wide/pivoted) | `cdc`         | `zip_code`       | `system_updated_at`|

> **Delete handling**: Socrata's public REST API exposes no delete feed or tombstone records, so none of these tables support delete synchronization (`cdc_with_deletes`). If a row is removed at the source, the only way to detect it via the API is a periodic full-table reconciliation. If hard-delete detection is required, schedule a periodic full reload alongside the incremental reads.

> **Small, slow-changing datasets**: Most of these datasets are small (roughly 9–506 rows) and update infrequently (`Annually`, `As Needed`, or `Historical`). Incremental `cdc` is correct and cheap here, but a periodic full reload is an equally reasonable strategy for these low-volume reference tables.

### Schema highlights

The full schema for each table is static and defined by the connector. A few columns warrant attention:

- **System columns** (`system_id`, `system_created_at`, `system_updated_at`) are prepended to every table.
- **URL fields** arrive as a nested `{"url": "..."}` struct and are preserved as a single-field struct rather than flattened:
  - `transportation_and_mobility.dataset_url`
  - `green_building_developer_agreements.ordinance_`
- **Geometry**: `green_building_developer_agreements` is a geospatial dataset. Its GeoJSON MultiPolygon boundary is serialized to a JSON string in the `the_geom_json` column (rather than a fragile nested struct).
- **Numeric-looking text**: `green_building_ratings_aggregate.pv_generation_mwh_` is typed as text in the source despite looking numeric, and is preserved as a string.
- **Sparse columns**: Socrata omits a key entirely for a row when the value is blank (rather than emitting `null`). Missing keys map to `NULL`; this is handled by the connector and framework.
- **Wide / pivoted schema**: `discount_monthly_new_enrollment_by_zip` has one column per fiscal-year month (`oct_23` … `sep_24`) instead of one row per (ZIP, month).


## Table Configurations

### Source & Destination

These are set directly under each `table` object in the pipeline spec:

| Option | Required | Description |
|---|---|---|
| `source_table` | Yes | Table name in the source system (one of the seven names above) |
| `destination_catalog` | No | Target catalog (defaults to pipeline's default) |
| `destination_schema` | No | Target schema (defaults to pipeline's default) |
| `destination_table` | No | Target table name (defaults to `source_table`) |

### Common `table_configuration` options

These are set inside the `table_configuration` map alongside any source-specific options:

| Option | Required | Description |
|---|---|---|
| `scd_type` | No | `SCD_TYPE_1` (default) or `SCD_TYPE_2`. Only applicable to tables with CDC or SNAPSHOT ingestion mode. |
| `primary_keys` | No | List of columns to override the connector's default primary keys |
| `sequence_by` | No | Column used to order records for SCD Type 2 change tracking |
| `cluster_by` | No | List of columns to cluster the destination Delta table by (Liquid Clustering). Consumed by the pipeline; not forwarded to the source. |

### Source-specific `table_configuration` options

Both source-specific options are optional and tune how the incremental time range is split into partitions. Every option name used here must be present in the connection's `externalOptionsAllowList`.

| Option             | Type    | Required | Default | Applies to | Description |
|--------------------|---------|----------|---------|------------|-------------|
| `window_days`      | integer | No       | `1`     | All tables | Number of days of `system_updated_at` covered by each partition window. Smaller values increase the number of parallel partitions; larger values reduce per-partition overhead. Minimum `1`. |
| `lookback_minutes` | integer | No       | `0`     | All tables | Minutes to backtrack from each incremental window's start, to re-scan recently changed rows and catch out-of-order or delayed updates. Minimum `0`. |


## Data Type Mapping

Socrata returns all row values as JSON strings (or nested objects for URL and geometry fields). The connector coerces each value to the Spark type declared in its static schema:

| Socrata `dataTypeName`         | Wire form (JSON)                         | Spark Type      | Notes |
|--------------------------------|------------------------------------------|-----------------|-------|
| `text`                         | string, e.g. `"Commercial"`              | `StringType`    | Default for free-text, categorical, and ID-like fields. |
| `number`                       | numeric **string**, e.g. `"1477"`        | `LongType` or `DoubleType` | Integers map to `LongType`, decimals to `DoubleType`. The connector parses the string form to the declared numeric type. |
| `calendar_date`                | ISO-like string, e.g. `"2024-10-01T00:00:00.000"` | `TimestampType` | Naive/local — no timezone offset in the source. |
| `floating_timestamp`           | same wire format as `calendar_date`      | `TimestampType` | Used for audit-style timestamps such as `updatedat`. |
| `fixed_timestamp` (system)     | UTC timestamp string                     | `TimestampType` | The `:created_at` / `:updated_at` system fields → `system_created_at` / `system_updated_at`. |
| `checkbox`                     | JSON `true` / `false`                    | `BooleanType`   | e.g. `is_public`. |
| `url`                          | `{"url": "..."}` struct (or plain string) | struct `{url: string}` | Preserved as a single-field struct, not flattened. |
| `multipolygon` (geo)           | GeoJSON object                           | `StringType`    | Serialized to a JSON string in `the_geom_json`. |

Additional behaviors:

- **Missing keys map to `NULL`**: sparse rows omit blank fields entirely; the connector treats absent keys as null rather than erroring.
- **Numbers as strings**: because Socrata's `/resource/{4x4}.json` endpoint returns numbers as JSON strings, all numeric columns are explicitly coerced by the connector.


## How to Run

### Step 1: Clone/Copy the Source Connector Code

Follow the Lakeflow Community Connector UI, which guides you through setting up a pipeline using the selected source connector code. This typically places the connector code under a project path Lakeflow can load.

### Step 2: Configure Your Pipeline

1. Update the `pipeline_spec` in the main pipeline file (e.g., `ingest.py`).
2. Reference a Unity Catalog connection that uses this connector, and list one or more tables to ingest. Add source-specific options (`window_days`, `lookback_minutes`) under `table_configuration` where you want to tune partitioning.

Example `pipeline_spec` snippet:

```json
{
  "pipeline_spec": {
    "connection_name": "hackathon_austin_texas_connection",
    "object": [
      {
        "table": {
          "source_table": "transportation_and_mobility",
          "table_configuration": {
            "window_days": "7",
            "lookback_minutes": "60"
          }
        }
      },
      {
        "table": {
          "source_table": "green_building_ratings_aggregate"
        }
      },
      {
        "table": {
          "source_table": "solar_program_current_incentive_levels_and_available_capacity"
        }
      }
    ]
  }
}
```

- `connection_name` must point to the UC connection configured for this connector (optionally with an `app_token`) and with `externalOptionsAllowList` set to `window_days,lookback_minutes`.
- For each `table`, `source_table` must be one of the seven supported table names above.
- `window_days` and `lookback_minutes` are optional; omit them to use the defaults.

3. (Optional) Customize the source connector code if needed for special use cases.

### Incremental Sync Strategy

All seven tables sync incrementally using the Socrata `:updated_at` system field (surfaced as `system_updated_at`) as a change-data-capture cursor:

- **Cursor filter**: each read fetches rows in a `(since, until]` window using a Socrata `$where` filter on `:updated_at`, ordered by `:updated_at`.
- **Stable high-water mark**: the connector freezes a snapshot cursor at the start of each run, so a run reads everything up to that point and then terminates cleanly. A later run picks up anything that arrived afterward.
- **Partitioned reads**: because Socrata supports range queries on `:updated_at`, the incremental range is split into independent time windows (`window_days` wide) that executors read in parallel. Use `lookback_minutes` to widen each window's start and re-scan recently changed rows for out-of-order or delayed updates.
- **First run (backfill)**: the initial run has no stored cursor and collapses into a single open-ended window that reads all historical rows, rather than fanning out into thousands of daily windows back to the epoch.

### Step 3: Run and Schedule the Pipeline

Run the pipeline using your standard Lakeflow / Databricks orchestration (a scheduled job or workflow).

- On the **first run**, the connector backfills all rows for each table in a single window.
- On **subsequent runs**, only rows whose `system_updated_at` advanced past the stored cursor are read (plus any `lookback_minutes` re-scan window).

#### Best Practices

- **Start small**: begin by syncing one or two tables (e.g. `transportation_and_mobility`, `green_building_ratings_aggregate`) to validate configuration and data shape.
- **Use incremental sync**: rely on the built-in `system_updated_at` cursor to minimize API calls; these datasets change infrequently.
- **Set appropriate schedules**: most of these datasets update `Annually`, `As Needed`, or are `Historical`. Daily or weekly schedules are typically more than sufficient.
- **Supply an app token for regular ingestion**: while public data reads without one, an `app_token` avoids the shared per-IP throttle and reduces `429` responses.
- **Tune `window_days` for large tables**: for the larger catalog table (`transportation_and_mobility`), a wider `window_days` reduces overhead; the small reference tables need no tuning.

#### Troubleshooting

**Common issues:**

- **`429 Too Many Requests` (rate limiting)**: You are hitting the shared anonymous per-IP throttle. Configure an `app_token` on the connection, and/or widen your schedule interval. The connector automatically retries transient failures (`429`, `500`, `502`, `503`, `504`) with exponential backoff, honoring the `Retry-After` header when present.
- **Table not supported error**: `source_table` must exactly match one of the seven case-sensitive names listed under [Supported Objects](#supported-objects).
- **Table-specific option ignored**: ensure `window_days` and `lookback_minutes` are included in the connection's `externalOptionsAllowList`; options not on the allowlist are not passed through to the connector.
- **Missing / null columns**: Socrata omits blank fields from row payloads, so sparse datasets (e.g. `green_building_ratings_aggregate`, `coa_energy_codes_timeline`) legitimately produce `NULL` values. This is expected, not an error.
- **Geometry as a string**: `green_building_developer_agreements` exposes its boundary as a GeoJSON string in `the_geom_json`. Parse it downstream if you need structured geometry.


## References

- Connector implementation: `src/databricks/labs/community_connector/sources/hackathon_austin_texas/hackathon_austin_texas.py`
- Connector schemas and metadata: `src/databricks/labs/community_connector/sources/hackathon_austin_texas/hackathon_austin_texas_schemas.py`
- Connector API documentation: `src/databricks/labs/community_connector/sources/hackathon_austin_texas/hackathon_austin_texas_api_doc.md`
- City of Austin Open Data Portal: `https://data.austintexas.gov`
- Socrata SODA API documentation:
  - App tokens: `https://dev.socrata.com/docs/app-tokens.html`
  - System fields (`:id`, `:created_at`, `:updated_at`): `https://dev.socrata.com/docs/system-fields`
  - Paging (`$limit` / `$offset`): `https://dev.socrata.com/docs/queries/offset.html`
