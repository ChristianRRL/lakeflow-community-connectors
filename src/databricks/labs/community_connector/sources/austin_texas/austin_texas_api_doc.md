# **Austin, Texas (data.austintexas.gov / Socrata SODA API) API Documentation**

## **Overview**

The City of Austin, Texas open data portal (`data.austintexas.gov`) runs on the **Socrata** open-data platform (Tyler Technologies Data & Insights). All datasets are exposed through the generic **Socrata Open Data API (SODA)**, using the **Socrata Query Language (SoQL)** for filtering, projection, and ordering. Socrata's SODA API is generic across all Socrata-hosted portals (e.g. `data.austintexas.gov`, `data.cityofchicago.org`, `data.cityofnewyork.us`) — the base URL host changes per portal, but authentication, pagination, and query semantics are identical.

This connector scope is a **single table**: `green_building_ratings_aggregate`, backed by the Socrata dataset with resource id **`dpvb-c5fy`** ("Green Building Ratings Aggregate"), published by Austin Energy Green Building.

## **Base URL Structure**

- **Portal (domain) base URL:** `https://data.austintexas.gov`
- **SODA resource (row-data) endpoint (SODA v2.1, JSON):**
  `https://data.austintexas.gov/resource/{four-by-four}.json`
  - For this connector: `https://data.austintexas.gov/resource/dpvb-c5fy.json`
  - The `{four-by-four}` (e.g. `dpvb-c5fy`) is Socrata's permanent dataset resource identifier — stable across dataset renames/edits, and the correct identifier to hard-code in the connector (not the human-readable dataset name/slug, which can change).
  - CSV export is also available at the same path with `.csv` instead of `.json`; this connector uses JSON only.
- **Dataset metadata endpoint (SODA v1 "views" API — dataset/column metadata, not row data):**
  `https://data.austintexas.gov/api/views/{four-by-four}.json`
  - For this connector: `https://data.austintexas.gov/api/views/dpvb-c5fy.json`
  - Returns the dataset's column definitions (`columns[].fieldName`, `name`, `dataTypeName`), `rowsUpdatedAt`, `createdAt`, `attribution`, `license`, and update-frequency metadata. Useful for a one-time/periodic schema-discovery call, but not part of the row-data read path.
- **Human-facing foundry/docs page for this dataset:** `https://dev.socrata.com/foundry/data.austintexas.gov/dpvb-c5fy` — a documentation landing page (not an API endpoint) that links into the generic SODA developer docs at `https://dev.socrata.com/docs/`.

## **Authorization**

- **Preferred method: Socrata Application Token via `X-App-Token` HTTP header.**
  - Header form: `X-App-Token: {app_token}` (preferred over the query-string form).
  - Alternate (query-param) form exists for compatibility: `?$$app_token={app_token}` (SODA 2.x/2.1) or `?app_token={app_token}` (legacy SODA 1.0). The connector should use the header form.
  - App tokens are obtained by registering a free Socrata/Tyler Data & Insights account and creating an application; they are portal-specific credential-adjacent tokens (not OAuth), tied to a developer account, and free to obtain — this connector should require the user to supply one as connection config (e.g. `app_token`), stored and sent as the `X-App-Token` header on every request.
  - All requests should use HTTPS (not HTTP) so the token is not sent in cleartext.
- **Unauthenticated access is permitted** for public/open datasets like this one — `data.austintexas.gov` does not require a logged-in user or dataset-specific API key to read public data. However:
  - Without a token, requests are throttled **per source IP address**, sharing a quota pool with any other traffic from that IP (e.g. other users/services on the same NAT/network) — this can cause unpredictable throttling unrelated to the connector's own usage.
  - With a valid app token, Socrata currently states it does **not** throttle token-bearing requests "unless those requests are determined to be abusive or malicious" — throttling shifts from a shared IP-based pool to a per-application allowance.
  - **Recommendation:** always send an app token even though the dataset is public, to get a dedicated (effectively unthrottled under normal use) quota rather than sharing the anonymous IP pool.
- No OAuth flow, refresh tokens, or client secret exchange is involved — this deviates from the generic connector template's OAuth note (which assumes a refresh-token flow); it is a single static bearer-like token sent as a header on every request.
- Example authenticated request:
  ```
  GET https://data.austintexas.gov/resource/dpvb-c5fy.json?$limit=50
  X-App-Token: <YOUR_APP_TOKEN>
  Accept: application/json
  ```
- Example unauthenticated request (works, but subject to shared-IP throttling):
  ```
  GET https://data.austintexas.gov/resource/dpvb-c5fy.json?$limit=50
  Accept: application/json
  ```

## **Object List**

- This connector's scope is **static and single-table**: `green_building_ratings_aggregate` → Socrata resource id `dpvb-c5fy`.
- More generally, `data.austintexas.gov` (like all Socrata portals) exposes an arbitrarily large, changing catalog of independent datasets, each identified by its own four-by-four resource id; there is no "tables under a parent object" nesting — every dataset is a flat, independent resource.
- The catalog of all datasets on the portal **is** retrievable via API (Socrata's Discovery API, `https://api.us.socrata.com/api/catalog/v1?domains=data.austintexas.gov`), but this is out of scope for this connector since the table set is fixed to `dpvb-c5fy`. Documented here only for completeness/future extension.
- No further object discovery is required for this connector's implementation; the single dataset id is hard-coded.

## **Object Schema**

Schema is retrieved via the dataset metadata endpoint `GET https://data.austintexas.gov/api/views/dpvb-c5fy.json`, which returns (among other fields) a `columns` array with each column's `fieldName` (the JSON key used in row data), `name` (human display label), and `dataTypeName` (Socrata logical type). This was cross-checked against a live sample of row data from `GET https://data.austintexas.gov/resource/dpvb-c5fy.json?$limit=5`.

**Dataset:** Green Building Ratings Aggregate (Austin Energy Green Building) — evaluates sustainability of single-family, multifamily, and commercial building projects on a 1–5 star scale (energy, water, materials, site, indoor environmental quality, community impact, innovation) and aggregates program performance/savings by fiscal year and building class since Fiscal Year 2007.

- **Row count (as of research):** 57 rows (19 fiscal years × 3 building classes; small, slow-growing reference/aggregate table)
- **Update frequency (per portal metadata):** Annually
- **Attribution:** Austin Energy Green Building
- **License:** Public Domain

| fieldName (JSON key) | Display Name | Socrata `dataTypeName` | Notes |
|---|---|---|---|
| `class` | Class | `text` | Building class: observed values `Commercial`, `Multifamily`, `Single Family` |
| `fiscal_year` | Fiscal Year | `text` | e.g. `"2007"`..`"2025"` — stored as text, not number, in the source |
| `number_of_projects_aegb_rated` | # of Projects Rated | `number` | Count of AEGB-rated projects |
| `number_of_projects_leed_reported` | # of Projects LEED Reported | `number` | Count of LEED-reported projects |
| `total_square_footage_aegb_rated_projects` | Projects (sq.ft.) | `number` | Total rated project square footage |
| `number_of_residential_units_aegb_rated` | # of Residential Units | `number` | Count of rated residential units |
| `number_of_smart_housing_units_aegb_rated` | # of Rated Units in S.M.A.R.T. developments | `number` | Count of rated S.M.A.R.T.-program housing units |
| `estimated_energy_savings_mbtu` | Energy Savings (MBTU) | `number` | Energy savings, millions of BTU |
| `estimated_demand_savings_kw` | Demand Savings (kW) | `number` | Demand savings, kilowatts |
| `estimated_electric_energy_savings_kwh` | Electric Savings (MWh) | `number` | Despite the `fieldName` suffix `_kwh`, the display label is "(MWh)" — verify units against source documentation before downstream use; do not assume from field name alone |
| `pv_generation_mwh_` | PV Generation (MWh) | `text` | **Typed as `text` in the source metadata**, not `number`, even though values observed so far are numeric strings (e.g. `"226.025"`, `"0"`) — quirk, see Known Quirks |
| `gas_savings_ccf` | Gas Savings (CCF) | `number` | Gas savings, hundred cubic feet |
| `indoor_potable_water_reduction_gallons` | Indoor Potable Water Reduction (1000 gallons) | `number` | In thousands of gallons per display label |
| `irrigation_potable_water_reduction_gallons_month_of_july` | Irrigation Potable Water Reduction (1000 gallons) | `number` | In thousands of gallons per display label |
| `process_portable_water_reduction_1000_gallons_` | Process Portable Water Reduction (1000 gallons) | `number` | Sparsely populated in earlier fiscal years (see sample data) |
| `construction_waste_diverted_from_landfill_tons` | Construction Waste Diverted from Landfill (tons) | `number` | |
| `number_of_aegb_rated_residential_units_outside_ae_service` | # of Rated Residential Units outside AE Service | `number` | |
| `number_of_aegb_rated_units_in_s_m_a_r_t_developments_outside_ae_service` | # of Rated Units in S.M.A.R.T. developments outside AE Service | `number` | |
| `projects_sq_ft_outside_ae_service` | Projects (sq.ft.) outside AE Service | `number` | |
| `_of_rated_projects_outside_of_ae_service_area` | # of Rated Projects Outside of AE Service Area | `number` | Note leading underscore in `fieldName` — Socrata auto-generates field names from display labels starting with `#`, which get sanitized to a leading `_`; this is a legitimate JSON key, not a typo |
| `start_date` | Start Date | `calendar_date` | Fiscal year start date, e.g. `"2006-10-01T00:00:00.000"` (floating timestamp, no timezone offset) |
| `end_date` | End Date | `calendar_date` | Fiscal year end date, e.g. `"2007-09-30T00:00:00.000"` |

**Total: 22 columns.**

Example schema-lookup request/response (truncated):
```
GET https://data.austintexas.gov/api/views/dpvb-c5fy.json
```
```json
{
  "id": "dpvb-c5fy",
  "name": "Green Building Ratings Aggregate",
  "attribution": "Austin Energy Green Building",
  "createdAt": 1474291930,
  "rowsUpdatedAt": 1762805034,
  "viewType": "tabular",
  "publicationStage": "published",
  "columns": [
    {"id": 587072726, "fieldName": "class", "name": "Class", "dataTypeName": "text"},
    {"id": 587072727, "fieldName": "fiscal_year", "name": "Fiscal Year", "dataTypeName": "text"},
    {"id": 587072736, "fieldName": "pv_generation_mwh_", "name": "PV Generation (MWh)", "dataTypeName": "text"}
  ]
}
```

## **Get Object Primary Keys**

- This dataset has **no declared row-identifier column** — the metadata's `rowIdentifierColumnId` is absent (confirmed via `GET /api/views/dpvb-c5fy.json`), and no column carries an `isSystemPrimaryKey`-style flag. This is common for small, publisher-curated "aggregate"/summary datasets on Socrata, as opposed to per-transaction datasets.
- Socrata internally tracks an opaque system row id (conventionally exposed as `:id` on some legacy SODA1/SODA2 endpoints), but it is **not** exposed in the standard `/resource/{id}.json` row payload for this dataset and should not be relied upon.
- **Recommended composite business key: (`fiscal_year`, `class`)** — every observed combination of fiscal year and building class is unique (19 fiscal years × 3 classes = 57 rows, matching the dataset's total row count), and this pair is stable across re-publications of the dataset (annual updates append new fiscal-year rows and occasionally revise values for existing fiscal-year/class rows in place, but do not appear to duplicate the pair).
- No API call is needed to obtain this key — it is a static, research-derived fact about this specific dataset's structure, not a generic Socrata platform feature.

## **Object's ingestion type**

- **Type: `snapshot`.**
- Rationale:
  - The dataset has no reliable per-row `updated_at`/`modified` field — only a whole-dataset-level `rowsUpdatedAt` timestamp is exposed via the metadata endpoint, not per-row.
  - The table is small (57 rows) and grows slowly (3 rows/year, on an annual publisher cadence), so a full snapshot read on every sync is cheap and avoids relying on an unverified incremental cursor.
  - Historical fiscal-year rows can be **revised in place** by the publisher (values corrected retroactively), which a naive append-only/cursor-based incremental strategy on `fiscal_year` would miss; a full snapshot captures such corrections.
  - No delete-tracking mechanism exists (Socrata SODA does not expose a tombstone/deleted-records feed for this dataset), so `cdc_with_deletes` is not achievable; a snapshot approach is the safest way to reflect row removals if the publisher ever removes a row.
- If a future iteration wants best-effort incremental behavior, `fiscal_year` combined with `$order=fiscal_year DESC` could be used as an append-oriented cursor for new fiscal years, but this would **not** capture in-place corrections to prior years — not recommended as the primary strategy given the dataset's small size.

## **Read API for Data Retrieval**

- **Method:** `GET` (recommended for this dataset given its small size; SODA3 also supports `POST` for very long/complex SoQL queries, not needed here).
- **Endpoint:** `https://data.austintexas.gov/resource/dpvb-c5fy.json`
- **Response format:** JSON array of row objects (see Object Schema for keys). CSV (`.csv`) and GeoJSON are also available at the platform level but not used by this connector.
- **Full-table read (snapshot) request:**
  ```
  GET https://data.austintexas.gov/resource/dpvb-c5fy.json?$order=fiscal_year,class&$limit=1000
  X-App-Token: <YOUR_APP_TOKEN>
  ```
  Given the table only has 57 rows, a single request with `$limit=1000` (or simply omitting `$limit`/`$offset` pagination entirely) retrieves the entire dataset in one call.
- **Pagination (for completeness / future-proofing if row count grows):**
  - `$limit` — max rows to return per request. SODA defaults to 1,000 rows if unspecified; SODA 2.1+ endpoints (which `/resource/*.json` uses) have no hard upper cap on `$limit` in principle, but very large `$limit` values are discouraged — page in chunks (e.g. 1,000–50,000) instead.
  - `$offset` — zero-indexed row offset to start from; used together with `$limit` to page (e.g. `$limit=50&$offset=150` returns rows 151–200).
  - Always pair `$limit`/`$offset` paging with a stable `$order` clause (e.g. `$order=fiscal_year,class`) — without a deterministic sort, row order across pages is not guaranteed to be stable between requests.
  - Given this table's size (57 rows), pagination is not strictly necessary in practice, but the connector should still implement generic `$limit`/`$offset` paging (bounded loop until an empty page is returned) so the same code path works if the publisher's row count grows substantially in the future.
- **Filtering / projection (SoQL), useful optional parameters:**
  - `$select` — column projection, e.g. `$select=fiscal_year,class,number_of_projects_aegb_rated`. Supports aliasing (`AS`) and computed expressions; not required for this connector (select all columns by omitting `$select`).
  - `$where` — SoQL boolean filter expression, e.g. `$where=fiscal_year='2024'` or `$where=start_date > '2020-01-01T00:00:00'`. Not required for a full-table snapshot read, but usable if a future incremental-by-fiscal-year strategy is adopted (e.g. `$where=fiscal_year >= '2024'`).
  - `$order` — sort clause, e.g. `$order=fiscal_year DESC, class`. Recommended for deterministic pagination as noted above.
  - `$q` — full-text search across all text columns; not applicable to this structured/numeric dataset.
- **Deleted records:** No delete-feed or tombstone endpoint exists for this dataset. Deletions (if any occur) can only be detected by diffing a full snapshot read against the previously ingested snapshot (consistent with the `snapshot` ingestion type above).
- **Rate limits:**
  - Not numerically published by Socrata (no fixed "N requests per minute" figure found in official docs as of this research) — Socrata describes the behavior qualitatively rather than with a fixed quota:
    - Unauthenticated (no `X-App-Token`): throttled per source IP address, sharing a pool with all other traffic from that IP; more prone to unpredictable throttling.
    - Authenticated with a valid `X-App-Token`: "we do not throttle API requests that are using an application token, unless those requests are determined to be abusive or malicious" (per Socrata's official app-tokens documentation).
  - Throttled/rejected requests return HTTP `429`. The connector should implement exponential backoff retry on `429` (and on `5xx`) regardless of token usage, since Socrata's docs explicitly reserve the right to throttle even token-bearing requests it deems abusive.
  - `TBD:` No documented `Retry-After` header behavior was found for Socrata 429 responses in the researched docs; the connector should defensively check for and honor a `Retry-After` header if present, falling back to its own backoff schedule otherwise.
  - Given this dataset's tiny size (single request typically retrieves all 57 rows), rate limiting is not expected to be a practical concern for this specific table.
- Example request/response:
  ```
  GET https://data.austintexas.gov/resource/dpvb-c5fy.json?$limit=2&$order=fiscal_year,class
  X-App-Token: <YOUR_APP_TOKEN>
  ```
  ```json
  [
    {
      "class": "Commercial",
      "fiscal_year": "2007",
      "number_of_projects_aegb_rated": "16",
      "number_of_projects_leed_reported": "0",
      "total_square_footage_aegb_rated_projects": "720137",
      "number_of_residential_units_aegb_rated": "0",
      "number_of_smart_housing_units_aegb_rated": "0",
      "estimated_energy_savings_mbtu": "27158",
      "estimated_demand_savings_kw": "1514",
      "estimated_electric_energy_savings_kwh": "3716",
      "pv_generation_mwh_": "0",
      "gas_savings_ccf": "151173",
      "indoor_potable_water_reduction_gallons": "2316",
      "irrigation_potable_water_reduction_gallons_month_of_july": "12649",
      "construction_waste_diverted_from_landfill_tons": "3752",
      "start_date": "2006-10-01T00:00:00.000",
      "end_date": "2007-09-30T00:00:00.000"
    },
    {
      "class": "Multifamily",
      "fiscal_year": "2007",
      "number_of_projects_aegb_rated": "9",
      "estimated_demand_savings_kw": "801",
      "pv_generation_mwh_": "0",
      "start_date": "2006-10-01T00:00:00.000",
      "end_date": "2007-09-30T00:00:00.000"
    }
  ]
  ```
  Note: some `number`-typed fields are simply **absent from the JSON object** for a given row rather than present with a null/zero value (e.g. the second row above omits `number_of_projects_leed_reported`, `total_square_footage_aegb_rated_projects`, etc.) — see Known Quirks.

## **Field Type Mapping**

| Socrata `dataTypeName` | Observed JSON representation | Recommended standard type | Notes |
|---|---|---|---|
| `text` | JSON string | `string` | Includes `class`, `fiscal_year` (stored as text, not integer), and `pv_generation_mwh_` (see quirk below) |
| `number` | JSON string containing a decimal literal (e.g. `"2543.30"`, `"6688.255056000001"`) | `decimal` / `double` | Socrata's `number` type is arbitrary-precision and is serialized **as a JSON string**, not a JSON numeric literal, to avoid floating-point precision loss — the connector must explicitly cast/parse these strings to a numeric type; do not assume JSON-native numeric typing |
| `calendar_date` | JSON string, floating timestamp, e.g. `"2006-10-01T00:00:00.000"` | `timestamp` (no timezone) | No UTC offset or `Z` suffix is present — treat as a naive/local calendar date-time, not true UTC; matches SoQL's `floating_timestamp` semantics |

Special field behaviors:
- **`fiscal_year` is `text`, not `number`** — despite containing values like `"2024"`, it must be treated/compared as a string in SoQL `$where` clauses (e.g. `$where=fiscal_year='2024'`, not `fiscal_year=2024`) unless explicitly cast with a SoQL function.
- **`pv_generation_mwh_` is `text`, not `number`**, unlike its sibling savings/generation columns — a data-modeling quirk from the source publisher's column setup, not a documentation error. The connector's schema mapping must map this column to `string`, even though downstream consumers may want to cast it to numeric.
- **Sparse/absent fields per row**: rows do not always include every column key in the JSON payload — Socrata omits a column entirely from a row's JSON object when that cell is empty/null for that row, rather than emitting `"field": null`. The connector's schema/type inference must treat missing keys as null, and the declared/static schema (from the metadata endpoint) should be treated as the authoritative superset of columns, not the keys observed in any single row or page.
- **Leading-underscore field name** (`_of_rated_projects_outside_of_ae_service_area`) is a legitimate, stable `fieldName` — an artifact of Socrata's auto-generation of `fieldName` from a display label starting with `#` (`"# of Rated Projects Outside of AE Service Area"`), not a data-quality issue.

## Known Quirks

- **Numbers as JSON strings:** all `number`-typed columns are returned as quoted strings in JSON (e.g. `"2543.30"`), consistent with general Socrata SODA behavior (arbitrary-precision decimals are not native JSON floats). The connector must cast these to numeric types explicitly.
- **`pv_generation_mwh_` typed as `text`** rather than `number`, unlike other savings columns — verified directly against the dataset's own column metadata (`dataTypeName: "text"`), not an inference.
- **Sparse rows** — absent JSON keys for empty cells rather than explicit `null` values; schema inference from a small row sample can undercount columns (confirmed by comparing an early-fiscal-year sample against a recent-fiscal-year sample, which exposed additional columns not present in the earlier rows).
- **No declared primary key / row identifier** in the Socrata metadata — a derived composite key (`fiscal_year`, `class`) is used instead (see Get Object Primary Keys).
- **Annual update cadence with retroactive corrections possible** — publisher may revise historical fiscal-year values on update, motivating the `snapshot` ingestion type over an append-only incremental approach.
- **No numerically documented rate limit** — Socrata describes throttling qualitatively (IP-based for anonymous requests, effectively unthrottled for token-bearing "non-abusive" requests) rather than publishing a fixed requests-per-minute figure.
- **Base URL host is portal-specific** — while all Socrata-hosted portals share identical API mechanics, `data.austintexas.gov` must be used verbatim as the host for this connector; the pattern is not directly reusable for another Socrata portal without changing the host.

## Deferred Tables

None. Table scope for this connector is limited to the single table `green_building_ratings_aggregate` (resource id `dpvb-c5fy`), per the connector's defined scope. No other Austin, Texas open-data datasets were researched or deferred as part of this task.

## Research Log

| Source Type | URL | Accessed (UTC) | Confidence | What it confirmed |
|-------------|-----|----------------|------------|-------------------|
| Official Docs (Socrata Foundry) | https://dev.socrata.com/foundry/data.austintexas.gov/dpvb-c5fy | 2026-07-24 | Medium | Confirmed the page is a generic developer-portal navigation hub, not dataset-specific content; pointed to general SODA docs for auth/query details |
| Official API (dataset metadata) | https://data.austintexas.gov/api/views/dpvb-c5fy.json | 2026-07-24 | High | Full column list (`fieldName`, `name`, `dataTypeName`), row count, `rowsUpdatedAt`, `createdAt`, attribution, license, absence of `rowIdentifierColumnId` |
| Official API (row data, SODA v2.1) | https://data.austintexas.gov/resource/dpvb-c5fy.json?$limit=3 | 2026-07-24 | High | Confirmed JSON row shape, that `number` fields serialize as strings, and that empty cells are omitted rather than null |
| Official API (row data, sorted) | https://data.austintexas.gov/resource/dpvb-c5fy.json?$order=fiscal_year%20DESC&$limit=5 | 2026-07-24 | High | Confirmed full 22-column set appears across rows (later fiscal years populate columns absent from earliest rows); confirmed `$order` syntax |
| Official Docs | https://dev.socrata.com/docs/endpoints.html | 2026-07-24 | High | Confirmed SODA3 vs SODA2.1 endpoint/response-format differences, existence of `X-App-Token` header |
| Official Docs | https://dev.socrata.com/docs/app-tokens.html | 2026-07-24 | High | Confirmed `X-App-Token` header (preferred), `$$app_token`/`app_token` query-param alternatives, unauthenticated-allowed-but-IP-throttled behavior, "not throttled unless abusive" behavior for token-bearing requests, 429 status code |
| Official Docs | https://dev.socrata.com/docs/queries/offset.html | 2026-07-24 | High | `$offset` semantics (zero-indexed, paired with `$limit`) |
| Official Docs | https://dev.socrata.com/docs/queries/where.html | 2026-07-24 | High | `$where` SoQL boolean filter syntax (`AND`/`OR`/`NOT`/`IS NULL`) |
| Official Docs | https://dev.socrata.com/docs/queries/select.html | 2026-07-24 | High | `$select` projection/aliasing syntax |
| Web Search (support article) | https://support.socrata.com/hc/en-us/articles/202949268-How-to-query-more-than-1000-rows-of-a-dataset | 2026-07-24 | Medium | Confirmed default 1,000-row page size and general pagination guidance beyond 1,000 rows |
| Web Search (changelog) | https://dev.socrata.com/changelog/2016/06/04/clarification-of-throttling-limits.html | 2026-07-24 | Medium | Confirmed a changelog exists clarifying throttling behavior, though it does not itself publish numeric limits (limits documented qualitatively in app-tokens.html instead) |

Conflicts encountered: none material. The foundry page (`dev.socrata.com/foundry/...`) did not itself contain auth/pagination/schema details as anticipated; all such details were instead sourced from the generic `dev.socrata.com/docs/*` pages and the dataset's own metadata/row-data endpoints, per the task's own fallback instruction.
