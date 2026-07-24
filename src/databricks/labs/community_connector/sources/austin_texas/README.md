# Lakeflow Austin, Texas Community Connector

This documentation provides setup instructions and reference information for the **Austin, Texas** source connector, which ingests data from the City of Austin open data portal (`data.austintexas.gov`) into Databricks.

The portal runs on the **Socrata** open-data platform and exposes datasets through the generic **Socrata Open Data API (SODA)**. This connector's scope is a single dataset — "Green Building Ratings Aggregate" — surfaced as the table `green_building_ratings_aggregate`.

## Prerequisites

- **Network access**: The environment running the connector must be able to reach `https://data.austintexas.gov` over HTTPS.
- **Socrata application token (optional)**: The Green Building Ratings Aggregate dataset is public, so no credentials are required to read it. You may optionally supply a free Socrata application token to raise rate limits and avoid shared throttling (see below).
- **Lakeflow / Databricks environment**: A workspace where you can register a Lakeflow community connector and run ingestion pipelines.

## Setup

### Required Connection Parameters

Provide the following **connection-level** options when configuring the connector.

| Name        | Type   | Required | Description                                                                                                                                           | Example                  |
|-------------|--------|----------|-----------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------|
| `app_token` | string | No       | Optional Socrata application token. When provided, it is sent as the `X-App-Token` header to raise rate limits. The dataset is public and readable without it. | `abcd1234EXAMPLETOKEN`   |

No credentials are required to read this connector's public dataset. If `app_token` is omitted, requests still succeed but share the anonymous per-IP throttling pool with any other traffic from the same IP address.

This connector supports one table-specific option, `page_size`, which is passed per table rather than as a connection parameter. Because a table-specific option exists, the `externalOptionsAllowList` connection option is **required** and must be set to:

`page_size`

### Obtaining a Socrata Application Token (optional)

A Socrata application token is free and is only needed if you want dedicated, effectively unthrottled access instead of sharing the anonymous per-IP quota.

1. Register a free account at the Tyler Data & Insights / Socrata developer portal.
2. Sign in and create a new application under your account's developer / API keys settings.
3. Copy the generated **application token**.
4. Supply it to the connector as the `app_token` connection option.

No OAuth flow, client secret exchange, or refresh token is involved — the app token is a single static value sent as an HTTP header on every request. Always use the connector over HTTPS so the token is never sent in cleartext.

### Create a Unity Catalog Connection

A Unity Catalog connection for this connector can be created in two ways via the UI:

1. Follow the **Lakeflow Community Connector** UI flow from the **Add Data** page.
2. Select any existing Lakeflow Community Connector connection for this source or create a new one.
3. Set `externalOptionsAllowList` to `page_size` (required for this connector to pass the table-specific `page_size` option). Optionally set `app_token` if you have one.

The connection can also be created using the standard Unity Catalog API.

## Supported Objects

The Austin, Texas connector exposes a **static, single-table** scope:

- `green_building_ratings_aggregate`

This table is backed by the Socrata "Green Building Ratings Aggregate" dataset (resource id `dpvb-c5fy`), published by Austin Energy Green Building. It aggregates sustainability program performance and estimated savings by fiscal year and building class since Fiscal Year 2007. The dataset is small (roughly 57 rows) and updated by the publisher on an annual cadence.

### Object summary, primary keys, and ingestion mode

| Table                              | Description                                                                | Ingestion Type | Primary Key                    | Incremental Cursor |
|------------------------------------|----------------------------------------------------------------------------|----------------|--------------------------------|--------------------|
| `green_building_ratings_aggregate` | Green building program metrics and estimated savings by fiscal year & class | `snapshot`     | `["fiscal_year", "class"]`     | n/a                |

**Ingestion notes:**

- The source dataset declares no per-row identifier column, so the connector uses the composite business key **(`fiscal_year`, `class`)**, which uniquely identifies every aggregate row.
- Ingestion is **snapshot**: the full dataset is re-read on every sync. There is no reliable per-row updated-at cursor, and the publisher may revise historical fiscal-year rows in place, so a full re-read is the safest way to capture corrections and reflect any row removals.
- The source does not expose a deleted-records feed, so delete synchronization (`cdc_with_deletes`) is not available; deletions are captured naturally by the full snapshot replacing the prior contents.

### Columns requiring attention

- `fiscal_year` is stored as **text** in the source (e.g. `"2024"`), not a number. It is part of the primary key.
- `pv_generation_mwh_` is typed as **text** in the source metadata even though its values look numeric (e.g. `"226.025"`). It is surfaced as a string; cast it downstream if you need a numeric type. Note the trailing underscore in the column name.
- `_of_rated_projects_outside_of_ae_service_area` legitimately begins with a leading underscore — this is a Socrata-generated field name derived from a display label starting with `#`, not a typo.
- Rows may omit columns entirely when a cell is empty; the connector's schema is the authoritative superset of all 22 columns, and missing values surface as `null`.

## Table Configurations

### Source & Destination

These are set directly under each `table` object in the pipeline spec:

| Option | Required | Description |
|---|---|---|
| `source_table` | Yes | Table name in the source system (`green_building_ratings_aggregate`) |
| `destination_catalog` | No | Target catalog (defaults to pipeline's default) |
| `destination_schema` | No | Target schema (defaults to pipeline's default) |
| `destination_table` | No | Target table name (defaults to `source_table`) |

### Common `table_configuration` options

These are set inside the `table_configuration` map alongside any source-specific options:

| Option | Required | Description |
|---|---|---|
| `scd_type` | No | `SCD_TYPE_1` (default) or `SCD_TYPE_2`. Applicable to this table because it uses SNAPSHOT ingestion. |
| `primary_keys` | No | List of columns to override the connector's default primary keys (`fiscal_year`, `class`) |
| `sequence_by` | No | Column used to order records for SCD Type 2 change tracking |
| `cluster_by` | No | List of columns to cluster the destination Delta table by (Liquid Clustering). Consumed by the pipeline; not forwarded to the source. |

### Source-specific `table_configuration` options

| Option | Required | Description |
|---|---|---|
| `page_size` | No | Number of rows requested per page from the SODA API. Defaults to `1000`. The dataset is tiny, so one page normally fetches everything; this option exists for defensive paging if the row count grows. Must be included in the connection's `externalOptionsAllowList`. |

## Data Type Mapping

Socrata serializes values in the JSON row payload as strings, which the connector maps to logical/Spark types as follows:

| Source Socrata Type | Observed JSON Representation                                   | Databricks Type   | Notes |
|---------------------|---------------------------------------------------------------|-------------------|-------|
| `text`              | JSON string, e.g. `"Commercial"`, `"2024"`                    | `string`          | Includes `class`, `fiscal_year`, and `pv_generation_mwh_`. |
| `number`            | JSON string holding an arbitrary-precision decimal, e.g. `"2543.30"` | `double`          | Socrata emits numbers as strings to avoid precision loss; the connector coerces them to `double`. |
| `calendar_date`     | JSON string, floating timestamp, e.g. `"2006-10-01T00:00:00.000"` | `timestamp`       | No timezone offset — treat as a naive (local) calendar date-time, not UTC. |

Empty cells are omitted from a row's JSON entirely (rather than sent as `null`); all non-key columns are nullable and missing values surface as `null`.

## How to Run

### Step 1: Clone/Copy the Source Connector Code

Follow the Lakeflow Community Connector UI, which will guide you through setting up a pipeline using the selected source connector code.

### Step 2: Configure Your Pipeline

1. Update the `pipeline_spec` in the main pipeline file (e.g., `ingest.py`).
2. Reference the Unity Catalog connection for this connector and add the `green_building_ratings_aggregate` table. Optionally set `page_size` under `table_configuration`.

```json
{
  "pipeline_spec": {
    "connection_name": "austin_texas_connection",
    "object": [
      {
        "table": {
          "source_table": "green_building_ratings_aggregate",
          "table_configuration": {
            "page_size": "1000"
          }
        }
      }
    ]
  }
}
```

- `connection_name` must point to the UC connection configured for this connector (with `externalOptionsAllowList` set to `page_size`, and optionally `app_token`).
- `source_table` must be `green_building_ratings_aggregate`.
- `page_size` is optional and defaults to `1000`.

3. (Optional) Customize the source connector code if needed for special use cases.

### Step 3: Run and Schedule the Pipeline

#### Best Practices

- **Match the source cadence**: The dataset is published on an annual cadence, so frequent syncs add little value. A schedule such as daily or weekly is more than sufficient to capture updates and in-place corrections.
- **Snapshot semantics**: Every sync re-reads the full dataset. This is cheap given the table's small size and ensures retroactive corrections and any row removals are reflected.
- **Supply an app token for heavier use**: If you run many Socrata connectors from the same network, an `app_token` moves you off the shared anonymous per-IP quota and reduces the chance of throttling.

#### Troubleshooting

**Common Issues:**

- **Rate limiting (`429 Too Many Requests`)**: Without an app token, requests share a per-IP throttling pool with all other traffic from your IP. Supply an `app_token` to get a dedicated quota. The connector retries `429` and `5xx` responses with exponential backoff, honoring a `Retry-After` header when present.
- **Empty or missing columns in rows**: This is expected — Socrata omits empty cells from the JSON payload. The connector's static schema is the authoritative set of columns; absent values appear as `null`.
- **Unexpected string values in numeric-looking columns**: `pv_generation_mwh_` is typed as text in the source and is intentionally surfaced as a string. Cast it downstream if you need a number.
- **`fiscal_year` treated as text**: `fiscal_year` is a string in the source. Compare and join on it as a string, not an integer.

## References

- Connector implementation: `src/databricks/labs/community_connector/sources/austin_texas/austin_texas.py`
- Connector schema and constants: `src/databricks/labs/community_connector/sources/austin_texas/austin_texas_schemas.py`
- Connector API research doc: `src/databricks/labs/community_connector/sources/austin_texas/austin_texas_api_doc.md`
- Dataset landing page: `https://data.austintexas.gov/resource/dpvb-c5fy.json`
- Socrata developer documentation:
  - `https://dev.socrata.com/docs/endpoints.html`
  - `https://dev.socrata.com/docs/app-tokens.html`
  - `https://dev.socrata.com/foundry/data.austintexas.gov/dpvb-c5fy`
