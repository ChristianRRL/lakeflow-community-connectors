# **Hackathon Austin Texas (City of Austin Open Data Portal) API Documentation**

Source system: **City of Austin, Texas Open Data Portal** — `data.austintexas.gov`, built on the **Socrata Open Data API (SODA)**. The portal exposes thousands of public datasets, each identified by a 4-character-dash-4-character **Socrata dataset ID** (the "4x4", e.g. `dpvb-c5fy`), and each is queryable as a REST/JSON (or CSV/XML) resource at a stable URL regardless of the dataset's human-readable title.

> **Scope note**: The 7 tables requested for this connector (`transportation_and_mobility`, `green_building_ratings_aggregate`, `solar_program_current_incentive_levels_and_available_capacity`, `green_building_energy_code_compliance`, `green_building_developer_agreements`, `coa_energy_codes_timeline`, `discount_monthly_new_enrollment_by_zip`) are **snake_case labels supplied by the requester**, not always exact Socrata dataset titles. Every table below documents the **actual dataset** on `data.austintexas.gov` chosen as the closest reasonable match, with the mapping/assumption called out explicitly where the name isn't a 1:1 title match (see `transportation_and_mobility` in particular).

## **Authorization**

- **Chosen method**: **App Token** via the `X-App-Token` HTTP header. No OAuth flow, no user login, and no per-dataset credential is required to read **public** datasets on `data.austintexas.gov`.
- **How to obtain a token**: Register a free Socrata/Tyler Data & Insights account and create an "App Token" from the account's developer settings (any City of Austin portal account works; app tokens are account-scoped, not dataset-scoped). This is a single static string the connector stores in configuration (e.g. `app_token`).
- **Auth placement**:
  - Preferred (SODA 2.1 / 3.0): HTTP header `X-App-Token: {app_token}`.
  - Legacy fallback (SODA 2.0/2.1 only): query parameter `$$app_token={app_token}`.
- **Anonymous access**: Requests **without** a token still work for public datasets, but are throttled at a much lower, shared-by-IP rate limit and are more likely to receive `429 Too Many Requests`. Requests **with** a valid app token get their own request pool and are effectively unthrottled for legitimate/non-abusive use.
- **SODA3 note (forward-looking)**: Socrata's newer **SODA3** query surface (now the default in the platform UI) requires requests to be either user-authenticated or carry a valid app token for most query actions; only bulk `/export` endpoints remain fully anonymous. The classic `/resource/{4x4}.json` REST endpoint (SODA 2.1-compatible) documented here continues to work, but the connector should **always** send `X-App-Token` to avoid future throttling/authorization changes.
- **No OAuth / no secrets beyond the token**: There is no `client_id`/`client_secret`/`refresh_token` exchange for this source — the app token is a long-lived static credential, analogous to an API key.

Example authenticated request:

```bash
curl -H "X-App-Token: {APP_TOKEN}" \
  -H "Accept: application/json" \
  "https://data.austintexas.gov/resource/dpvb-c5fy.json?\$limit=50"
```

Notes:
- Base host for all 7 objects in this connector: `https://data.austintexas.gov`.
- Rate limits: Socrata does not publish a fixed numeric RPS limit; documented behavior is "throttled by IP without a token, effectively unthrottled with a token unless usage is abusive." The connector should still apply reasonable client-side pacing (e.g. sequential requests, retry-with-backoff on `429`) since the exact threshold is undocumented (`TBD: exact anonymous vs. token'd requests/sec threshold — not published by Socrata`).


## **Object List**

The object list for this connector is **static** — a curated set of 7 City of Austin Open Data Portal datasets selected to match the requested table names. Socrata *does* also expose a live, queryable catalog of all datasets on the portal (used below to resolve `transportation_and_mobility`, and useful generally for object discovery): `GET https://data.austintexas.gov/resource/my8q-n4hf.json` (the "Asset Inventory: Austin Open Data Portal" dataset) or the public Discovery API `GET https://api.us.socrata.com/api/catalog/v1?domains=data.austintexas.gov&q={search terms}`.

| Table name (this connector) | Matched Socrata dataset title | 4x4 ID | Resource endpoint | Update cadence | Ingestion type |
|---|---|---|---|---|---|
| `transportation_and_mobility` | Open Data Portal Datasets - Austin Transportation and Public Works | `28ys-ieqv` | `GET /resource/28ys-ieqv.json` | Daily | `cdc` |
| `green_building_ratings_aggregate` | Green Building Ratings Aggregate | `dpvb-c5fy` | `GET /resource/dpvb-c5fy.json` | Annually | `cdc` |
| `solar_program_current_incentive_levels_and_available_capacity` | Solar Program Current Incentive Levels and Available Capacity | `vxq2-zjmn` | `GET /resource/vxq2-zjmn.json` | As Needed | `cdc` |
| `green_building_energy_code_compliance` | Green Building Energy Code Compliance | `i7vh-fpaj` | `GET /resource/i7vh-fpaj.json` | Annually | `cdc` |
| `green_building_developer_agreements` | Green Building Developer Agreements | `63mb-dbmj` | `GET /resource/63mb-dbmj.json` | As Needed | `cdc` |
| `coa_energy_codes_timeline` | COA Energy Codes Timeline | `xn7p-rafv` | `GET /resource/xn7p-rafv.json` | As Needed | `cdc` |
| `discount_monthly_new_enrollment_by_zip` | Discount Monthly New Enrollment by Zip | `guem-bnpv` | `GET /resource/guem-bnpv.json` | Historical (Not Updated) | `cdc` |

**Mapping assumptions / notes**:
- **`transportation_and_mobility`**: There is **no single Socrata dataset** literally titled "Transportation and Mobility" — it is a **browse category** on the portal (as reflected in the requester's example browse URL) containing many individual datasets (e.g. `Real-Time Traffic Incident Reports`, `Traffic Signals Status`, `Austin Crash Report Data`, `Urban Roadways`, etc.). Rather than arbitrarily pick one sub-dataset, this connector maps `transportation_and_mobility` to **`Open Data Portal Datasets - Austin Transportation and Public Works`** (`28ys-ieqv`) — an official, actively-maintained (daily) Socrata dataset that **itself lists every public dataset published by Austin Transportation and Public Works**, including each sub-dataset's own 4x4 ID, name, description, URL, update frequency, and row/download counts. This gives the connector a genuinely queryable, schema-stable "transportation and mobility" table, and — as a side benefit — a live, API-driven way to discover individual TPW datasets (e.g. crash reports, signals, road conditions) for a future connector iteration. This mapping is called out here as an explicit assumption per the research scope instructions.
- **`discount_monthly_new_enrollment_by_zip`**: matches an Austin Energy dataset of the same name almost verbatim. Note the portal also publishes a **fiscal-year-suffixed successor dataset**, `Discount Monthly New Enrollment by Zip FY 2025` (4x4 `miq7-jh88`), covering Oct 2024–Sep 2025 with the same shape. See Known Quirks under that object's section.
- All other 5 tables matched an existing dataset title on the portal essentially exactly (only capitalization/hyphenation differs from the snake_case name given).

**Static list of all connector objects** (for interface `list_tables()` implementations): `transportation_and_mobility`, `green_building_ratings_aggregate`, `solar_program_current_incentive_levels_and_available_capacity`, `green_building_energy_code_compliance`, `green_building_developer_agreements`, `coa_energy_codes_timeline`, `discount_monthly_new_enrollment_by_zip`.


## **Object Schema**

### General notes

- Socrata provides machine-readable schema/metadata for every dataset via `GET https://data.austintexas.gov/api/views/{4x4}.json`, which returns a `columns` array with each column's human `name`, API `fieldName` (snake_case, used in `$select`/`$where`/`$order`), and `dataTypeName`.
- Field names below are the **actual API `fieldName`s** observed from live `GET /resource/{4x4}.json` responses (confirmed against, and in a few cases more precise than, the `/api/views/{4x4}.json` metadata — Socrata sometimes auto-derives a slightly different `fieldName` than the display `name` implies, e.g. truncated/underscored versions).
- Every Socrata dataset also carries three **system fields** not returned by default: `:id`, `:created_at`, `:updated_at`. These must be explicitly requested via `$select=:*,*` (or `$select=:id,:created_at,:updated_at,...`) or the legacy `$$exclude_system_fields=false` parameter. They are documented once here and referenced per-object below since they underpin the connector's general incremental-sync strategy (see **Read API for Data Retrieval**).

### `transportation_and_mobility` (mapped to `Open Data Portal Datasets - Austin Transportation and Public Works`, `28ys-ieqv`)

**Source endpoint**: `GET https://data.austintexas.gov/resource/28ys-ieqv.json`

**Key behavior**:
- One row per dataset published under the Austin Transportation and Public Works department on the portal (currently ~506 rows).
- Refreshed **daily**; each row carries its own `updatedat` / `data_updated_at` timestamps, making this an easy incremental (append/upsert) source.
- `dataset_url` is a nested object (`{"url": "..."}"`).

**Schema**:

| Column Name | Type | Description |
|---|---|---|
| `id` | text | 4x4 Socrata ID of the referenced dataset. Unique per row. |
| `name` | text | Dataset display name. |
| `description` | text | Dataset description. |
| `dataset_url` | struct `{url: text}` | Link to the referenced dataset's landing page. |
| `attribution` | text | Publisher attribution string. |
| `type` | text | Asset type, e.g. `dataset`, `story`, `map`, `chart`. |
| `update_frequency` | text | Free-text cadence, e.g. `Multiple Per Day`, `Daily`, `Quarterly`, `As Needed`. |
| `department_name` | text | Owning department (filtered to Transportation and Public Works and related programs). |
| `program_name` | text | Owning program/division. |
| `spatial_information` | text | Free-text spatial coverage note (often empty). |
| `strategic_area` | text | Free-text strategic-plan tag (often empty). |
| `updatedat` | floating_timestamp | Last time the *dataset asset* (metadata or data) was updated. |
| `createdat` | floating_timestamp | When the dataset asset was first published. |
| `metadata_updated_at` | floating_timestamp | Last metadata-only update. |
| `data_updated_at` | floating_timestamp | Last time underlying row data changed. |
| `publication_date` | floating_timestamp | When the asset was made public. |
| `download_count` | number | Cumulative download count. |
| `page_views_last_week` | number | Rolling 7-day page views. |
| `page_views_last_month` | number | Rolling 30-day page views. |
| `page_views_total` | number | All-time page views. |
| `row_count` | number | Row count of the referenced dataset (null for non-tabular assets like stories). |
| `cover_image_url` | url | Cover image, if any. |
| `automation_method` | text | How the dataset is published, e.g. `REST API`, `Manual`. |
| `automation_method_other` | text | Free-text override for `automation_method`. |
| `owner_display_name` | text | Publishing owner/team. |
| `tags` | text | Comma-separated tags. |
| `is_public` | checkbox (boolean) | Whether the asset is public. |

**Example request**:

```bash
curl -H "X-App-Token: {APP_TOKEN}" \
  "https://data.austintexas.gov/resource/28ys-ieqv.json?\$limit=2&\$order=updatedat%20DESC"
```

**Example response** (truncated):

```json
[
  {
    "id": "dx9v-zd7x",
    "name": "Real-Time Traffic Incident Reports",
    "description": "This dataset contains traffic incident information ...",
    "dataset_url": {"url": "https://data.austintexas.gov/d/dx9v-zd7x"},
    "attribution": "City of Austin, Texas - data.austintexas.gov",
    "type": "dataset",
    "update_frequency": "Multiple Per Day",
    "department_name": "Transportation and Public Works",
    "program_name": "Data and Technology Services Division",
    "updatedat": "2025-09-19T03:55:21.000",
    "createdat": "2017-09-25T08:48:03.000",
    "data_updated_at": "2025-09-19T03:55:21.000",
    "publication_date": "2024-01-26T13:55:45.000",
    "download_count": "15032",
    "row_count": "438381",
    "automation_method": "REST API",
    "owner_display_name": "transportation.data@austintexas.gov",
    "tags": "transportation, safety, roads, pedestrians",
    "is_public": true
  }
]
```

**Primary key**: `id` (the 4x4 of the referenced sub-dataset — unique within this catalog table).


### `green_building_ratings_aggregate` (`dpvb-c5fy`)

**Source endpoint**: `GET https://data.austintexas.gov/resource/dpvb-c5fy.json`

**Key behavior**:
- One row per building **class** (`Commercial`, `Multifamily`, `Single Family`) per **fiscal year**, since Fiscal Year 2007. Austin Energy Green Building (AEGB) star-rating and resource-savings rollups.
- 57 rows total as of research date; updated **annually**.
- Several numeric fields are only populated for certain classes/years (e.g. `pv_generation_mwh_`, `gas_savings_ccf`) and appear as absent keys rather than `0`/`null` in sparse rows — the connector should treat missing keys as `NULL`.

**Schema**:

| Column Name | Type | Description |
|---|---|---|
| `class` | text | Building class: `Commercial`, `Multifamily`, `Single Family`. |
| `fiscal_year` | text | Fiscal year, e.g. `"2007"`. |
| `number_of_projects_aegb_rated` | number | Count of AEGB-rated projects. |
| `number_of_projects_leed_reported` | number | Count of LEED-reported projects. |
| `total_square_footage_aegb_rated_projects` | number | Total rated square footage. |
| `number_of_residential_units_aegb_rated` | number | Residential units rated (Multifamily/Single Family). |
| `number_of_smart_housing_units_aegb_rated` | number | Rated units in S.M.A.R.T. Housing developments. |
| `estimated_energy_savings_mbtu` | number | Estimated energy savings (MBTU). |
| `estimated_demand_savings_kw` | number | Estimated peak demand savings (kW). |
| `estimated_electric_energy_savings_kwh` | number | Estimated electric energy savings. |
| `pv_generation_mwh_` | text | Estimated PV generation (MWh) — note: typed as text in the source despite being numeric-looking. |
| `gas_savings_ccf` | number | Gas savings (CCF). |
| `indoor_potable_water_reduction_gallons` | number | Indoor potable water reduction (1,000 gal). |
| `irrigation_potable_water_reduction_gallons_month_of_july` | number | Irrigation potable water reduction, July baseline (1,000 gal). |
| `process_portable_water_reduction_1000_gallons_` | number | Process potable water reduction (1,000 gal). |
| `construction_waste_diverted_from_landfill_tons` | number | Construction waste diverted (tons). |
| `number_of_aegb_rated_residential_units_outside_ae_service` | number | Rated residential units outside Austin Energy service territory. |
| `number_of_aegb_rated_units_in_s_m_a_r_t_developments_outside_ae_service` | number | S.M.A.R.T. Housing rated units outside AE service territory. |
| `projects_sq_ft_outside_ae_service` | number | Rated project sq. ft. outside AE service territory. |
| `_of_rated_projects_outside_of_ae_service_area` | number | Count of rated projects outside AE service territory. |
| `start_date` | calendar_date | Fiscal year start date. |
| `end_date` | calendar_date | Fiscal year end date. |

**Example request**:

```bash
curl -H "X-App-Token: {APP_TOKEN}" \
  "https://data.austintexas.gov/resource/dpvb-c5fy.json?\$where=fiscal_year='2024'"
```

**Example response**:

```json
[
  {
    "class": "Commercial",
    "fiscal_year": "2007",
    "number_of_projects_aegb_rated": "16",
    "total_square_footage_aegb_rated_projects": "720137",
    "estimated_energy_savings_mbtu": "27158",
    "estimated_demand_savings_kw": "1514",
    "gas_savings_ccf": "151173",
    "start_date": "2006-10-01T00:00:00.000",
    "end_date": "2007-09-30T00:00:00.000"
  }
]
```

**Primary key**: Composite natural key (`class`, `fiscal_year`). No dedicated single-column ID exists in the published schema; the Socrata system field `:id` can be used as a stable surrogate key if a single-column PK is required.


### `solar_program_current_incentive_levels_and_available_capacity` (`vxq2-zjmn`)

**Source endpoint**: `GET https://data.austintexas.gov/resource/vxq2-zjmn.json`

**Key behavior**:
- One row per Austin Energy Solar Rebate Program **incentive tier** (residential and small/large commercial), tracking requested/reserved/available rebate capacity in kW-AC. Includes both currently open and historically closed tiers (e.g. `"Small Commercial - $0.08/kWh Closed"`).
- Small (17 rows in this dataset). Update frequency: **As Needed** — Austin Energy edits this table whenever a tier opens, closes, or its capacity changes; there is no fixed cadence.
- `date_last_updated` reflects the last time that specific row (tier) was revised, not a whole-table refresh timestamp.

**Schema**:

| Column Name | Type | Description |
|---|---|---|
| `program` | text | Program/incentive tier label, e.g. `"Small Commercial - $0.08/kWh Closed"`, `"Residential - $.90/Watt - Closed"`. Effectively a natural key. |
| `capacity_requested_kw_ac` | number | Cumulative capacity requested for this tier (kW-AC). |
| `capacity_reserved_kw_ac` | number | Capacity reserved/installed for this tier (kW-AC). |
| `capacity_available_kw_ac` | number | Remaining available capacity for this tier (kW-AC). |
| `date_last_updated` | calendar_date | Date this row was last revised by Austin Energy. |

**Example request**:

```bash
curl -H "X-App-Token: {APP_TOKEN}" \
  "https://data.austintexas.gov/resource/vxq2-zjmn.json?\$order=date_last_updated%20DESC"
```

**Example response**:

```json
[
  {
    "program": "Small Commercial - $0.08/kWh Closed",
    "capacity_requested_kw_ac": "0",
    "capacity_reserved_kw_ac": "500",
    "capacity_available_kw_ac": "0",
    "date_last_updated": "2015-12-07T00:00:00.000"
  },
  {
    "program": "Residential - $.90/Watt - Closed",
    "capacity_requested_kw_ac": "0",
    "capacity_reserved_kw_ac": "1500",
    "capacity_available_kw_ac": "0",
    "date_last_updated": "2015-11-09T00:00:00.000"
  }
]
```

**Primary key**: `program` (unique per incentive tier in the observed data). Fallback: Socrata system field `:id`.


### `green_building_energy_code_compliance` (`i7vh-fpaj`)

**Source endpoint**: `GET https://data.austintexas.gov/resource/i7vh-fpaj.json`

**Key behavior**:
- One row per fiscal year (since FY 2007) summarizing residential/multifamily/commercial permit counts and estimated energy-code savings.
- 19 rows; updated **annually** (new fiscal-year row appended each year; prior years are not expected to change once published).

**Schema**:

| Column Name | Type | Description |
|---|---|---|
| `fiscal_year` | text | Fiscal year, e.g. `"2025"`. |
| `number_of_residential_building_permits` | number | Count of single-family residential permits. |
| `residential_energy_code_savings_kw` | number | Residential estimated demand savings (kW). |
| `residential_energy_code_savings_mwh` | number | Residential estimated energy savings (MWh). |
| `number_of_multifamily_unit_permits` | number | Count of multifamily unit permits. |
| `multifamily_energy_code_savings_kw` | number | Multifamily estimated demand savings (kW). |
| `multifamily_energy_code_savings_mwh` | number | Multifamily estimated energy savings (MWh). |
| `square_footage_of_commercial_building_permits` | number | Commercial permitted square footage. |
| `commercial_energy_code_savings_kw` | number | Commercial estimated demand savings (kW). |
| `commercial_energy_code_savings_mwh` | number | Commercial estimated energy savings (MWh). |
| `start_date` | calendar_date | Fiscal year start date. |
| `end_date` | calendar_date | Fiscal year end date. |
| `total_energy_code_saving` | number | Total estimated demand savings across classes (kW). |
| `total_energy_code_savings_mwh_` | number | Total estimated energy savings across classes (MWh). |

**Example request**:

```bash
curl -H "X-App-Token: {APP_TOKEN}" \
  "https://data.austintexas.gov/resource/i7vh-fpaj.json?\$order=fiscal_year%20DESC&\$limit=2"
```

**Example response**:

```json
[
  {
    "fiscal_year": "2025",
    "number_of_residential_building_permits": "1904",
    "residential_energy_code_savings_kw": "1477",
    "residential_energy_code_savings_mwh": "2049",
    "number_of_multifamily_unit_permits": "8691",
    "multifamily_energy_code_savings_kw": "4405",
    "multifamily_energy_code_savings_mwh": "5186",
    "square_footage_of_commercial_building_permits": "5996025.000000001",
    "commercial_energy_code_savings_kw": "1711",
    "commercial_energy_code_savings_mwh": "5630",
    "start_date": "2024-10-01T00:00:00.000",
    "end_date": "2025-09-30T00:00:00.000",
    "total_energy_code_saving": "7593",
    "total_energy_code_savings_mwh_": "12864"
  }
]
```

**Primary key**: `fiscal_year` (one row per fiscal year). Fallback: Socrata system field `:id`.


### `green_building_developer_agreements` (`63mb-dbmj`)

**Source endpoint**: `GET https://data.austintexas.gov/resource/63mb-dbmj.json`

**Key behavior**:
- One row per developer agreement/PUD area **requiring** an Austin Energy Green Building rating (e.g. as a condition of PUD zoning, a density bonus program, or S.M.A.R.T. Housing participation). This is a **geospatial** dataset — each row includes a MultiPolygon boundary.
- 38 rows; update frequency **As Needed** (new agreements added irregularly; existing polygons rarely change once created).
- `ordinance_` is a nested URL struct linking to the governing City ordinance/PDF document.

**Schema**:

| Column Name | Type | Description |
|---|---|---|
| `the_geom` | multipolygon (geo) | Agreement/PUD area boundary geometry (GeoJSON MultiPolygon). |
| `gis_id` | number | Numeric GIS identifier. Unique per agreement/area. |
| `name` | text | Agreement/development name, e.g. `"North Austin Medical Center PUD"`. |
| `ordinance_` | struct `{url: text}` | Link to the governing ordinance/agreement document. |
| `created_da` | calendar_date | Date the GIS record was created. |
| `shape_area` | number | Polygon area (source CRS units, typically sq. ft.). |
| `shape_len` | number | Polygon perimeter length (source CRS units). |

**Example request**:

```bash
curl -H "X-App-Token: {APP_TOKEN}" \
  "https://data.austintexas.gov/resource/63mb-dbmj.json?\$select=gis_id,name,ordinance_,created_da,shape_area&\$limit=2"
```

**Example response** (geometry omitted for brevity):

```json
[
  {
    "gis_id": "10",
    "name": "North Austin Medical Center PUD",
    "ordinance_": {"url": "https://services.austintexas.gov/edims/document.cfm?id=139617"},
    "created_da": "2011-06-20T00:00:00.000",
    "shape_area": "2782268.94185",
    "shape_len": "10000.8049443"
  },
  {
    "gis_id": "1",
    "name": "Amarra Drive Lot 1, Block A",
    "ordinance_": {"url": "https://services.austintexas.gov/edims/document.cfm?id=115220"},
    "created_da": "2011-06-22T00:00:00.000",
    "shape_area": "1436643.5758",
    "shape_len": "4850.91043902"
  }
]
```

**Primary key**: `gis_id`.


### `coa_energy_codes_timeline` (`xn7p-rafv`)

**Source endpoint**: `GET https://data.austintexas.gov/resource/xn7p-rafv.json`

**Key behavior**:
- Historical summary of City Council technical/energy code adoptions going back to 1989 (per portal description, covering "the past seven decades" including pre-1989 baseline entries in some views).
- Only 9 rows — a small, effectively static reference/lookup table. Update frequency **As Needed** (only changes when Council adopts a new energy code cycle, roughly every 3 years).
- `line` appears to be a low-cardinality sub-ordering/grouping indicator (observed value `"1"` across multiple distinct rows in the sample), **not** a unique identifier by itself.

**Schema**:

| Column Name | Type | Description |
|---|---|---|
| `effective_date` | calendar_date | Date the code adoption took effect. |
| `city_of_austin_energy_code` | number | Flag/indicator (`0`/`1`) for whether this was a City of Austin-specific energy code amendment cycle. |
| `residential_energy_code` | text | Residential code edition adopted, e.g. `"1995 CABO"`. |
| `commercial_energy_code` | text | Commercial code edition adopted, e.g. `"1993 Model Energy Code"`. |
| `residential_ordinance` | text | Ordinance number for the residential code adoption. |
| `commercial_ordinance` | text | Ordinance number for the commercial code adoption (sparsely populated — absent on several rows). |
| `energy_code_name` | text | Combined display label, e.g. `"1995 CABO (1993 Model Energy Code)"`. |
| `line` | number | Low-cardinality row-ordering/grouping value; not confirmed unique. |

**Example request**:

```bash
curl -H "X-App-Token: {APP_TOKEN}" \
  "https://data.austintexas.gov/resource/xn7p-rafv.json?\$order=effective_date"
```

**Example response**:

```json
[
  {
    "effective_date": "1989-04-16T00:00:00.000",
    "city_of_austin_energy_code": "1",
    "residential_energy_code": "1986 CABO",
    "commercial_energy_code": "1986 Model Energy Code",
    "residential_ordinance": "880128-N",
    "energy_code_name": "1986 CABO (1986 Model Energy Code)",
    "line": "1"
  },
  {
    "effective_date": "1993-02-10T00:00:00.000",
    "city_of_austin_energy_code": "0",
    "residential_energy_code": "1992 CABO",
    "commercial_energy_code": "1989 Model Energy Code",
    "residential_ordinance": "921112-B",
    "energy_code_name": "1992 CABO (1989 Model Energy Code)",
    "line": "1"
  }
]
```

**Primary key**: `TBD: no confirmed single-column unique natural key` — `effective_date` is a strong candidate (one code-adoption event per date in the sample) but uniqueness across the full 9-row history was not exhaustively verified. Recommend using the Socrata system field `:id` as the primary key for this object.


### `discount_monthly_new_enrollment_by_zip` (`guem-bnpv`)

**Source endpoint**: `GET https://data.austintexas.gov/resource/guem-bnpv.json`

**Key behavior**:
- One row per ZIP code (48 rows), reporting the count of **new** Austin Energy Customer Assistance Program (CAP) "Discount" enrollments per month for FY 2024 (Oct 2023–Sep 2024).
- **Pivoted/wide schema**: each fiscal-year month is its own column (`oct_23`, `nov_23`, ..., `sep_24`) rather than one row per (zip, month). Update frequency: **Historical (Not Updated)** — this specific dataset is frozen once its fiscal year closes.
- **Known quirk — dataset re-published per fiscal year**: Austin Energy publishes a **new dataset ID** each fiscal year rather than appending rows to this one. The FY 2025 edition is a separate dataset, `Discount Monthly New Enrollment by Zip FY 2025` (4x4 `miq7-jh88`), with columns `unnamed_column` (zip code), `october_2024` ... `september_2025`. A production connector should either (a) treat each fiscal-year dataset as its own table/vintage, or (b) maintain a small static map of `fiscal_year -> 4x4 id` (extendable by querying the catalog dataset `my8q-n4hf` for new datasets matching `"Discount Monthly New Enrollment by Zip"`) and union rows client-side. This connector documents the base (`guem-bnpv`, FY 2024) dataset as the primary object per the requested table name; the FY 2025 successor is noted here rather than added as an 8th table, since it is out of the requested scope.

**Schema** (base dataset, `guem-bnpv`, FY 2024):

| Column Name | Type | Description |
|---|---|---|
| `zip_code` | text | 5-digit ZIP code. |
| `oct_23` | number | New Discount-program enrollments, October 2023. |
| `nov_23` | number | New enrollments, November 2023. |
| `dec_23` | number | New enrollments, December 2023. |
| `jan_24` | number | New enrollments, January 2024. |
| `feb_24` | number | New enrollments, February 2024. |
| `mar_24` | number | New enrollments, March 2024. |
| `apr_24` | number | New enrollments, April 2024. |
| `may_24` | number | New enrollments, May 2024. |
| `jun_24` | number | New enrollments, June 2024. |
| `jul_24` | number | New enrollments, July 2024. |
| `aug_24` | number | New enrollments, August 2024. |
| `sep_24` | number | New enrollments, September 2024. |

**Example request**:

```bash
curl -H "X-App-Token: {APP_TOKEN}" \
  "https://data.austintexas.gov/resource/guem-bnpv.json?\$limit=2"
```

**Example response**:

```json
[
  {
    "zip_code": "78613",
    "oct_23": "2", "nov_23": "8", "dec_23": "3", "jan_24": "0",
    "feb_24": "3", "mar_24": "0", "apr_24": "5", "may_24": "1",
    "jun_24": "6", "jul_24": "18", "aug_24": "12", "sep_24": "4"
  },
  {
    "zip_code": "78617",
    "oct_23": "47", "nov_23": "47", "dec_23": "36", "jan_24": "34",
    "feb_24": "36", "mar_24": "55", "apr_24": "39", "may_24": "61",
    "jun_24": "77", "jul_24": "253", "aug_24": "99", "sep_24": "49"
  }
]
```

**Primary key**: `zip_code`.


## **Get Object Primary Keys**

There is no dedicated Socrata "get primary key" API — primary keys are **not** declared in dataset metadata (`/api/views/{4x4}.json` describes columns, not keys) and must be inferred from the data model. Summary:

| Object | Primary key | Notes |
|---|---|---|
| `transportation_and_mobility` | `id` | Socrata 4x4 of the referenced dataset row. |
| `green_building_ratings_aggregate` | (`class`, `fiscal_year`) composite | Fallback: system field `:id`. |
| `solar_program_current_incentive_levels_and_available_capacity` | `program` | Fallback: system field `:id`. |
| `green_building_energy_code_compliance` | `fiscal_year` | Fallback: system field `:id`. |
| `green_building_developer_agreements` | `gis_id` | True numeric unique identifier. |
| `coa_energy_codes_timeline` | `TBD` — recommend system field `:id` | No confirmed unique natural key column. |
| `discount_monthly_new_enrollment_by_zip` | `zip_code` | One row per ZIP code. |

For any object, the Socrata-managed row identifier can always be retrieved as a stable synthetic key via:

```bash
curl -H "X-App-Token: {APP_TOKEN}" \
  "https://data.austintexas.gov/resource/{4x4}.json?\$select=:id,*&\$limit=1"
```


## **Object's ingestion type**

All 7 objects are documented as **`cdc`** (incremental read, upserts only — no delete feed). Rationale and caveats:

- Every Socrata dataset exposes system fields `:created_at` and `:updated_at` (fixed timestamps, queryable via `$select` and filterable via `$where`), which gives every object — even ones without a natural per-row date column — a reliable **upsert cursor**: `$where=:updated_at > '{last_cursor_iso8601}'&$order=:updated_at`.
- Several objects additionally carry natural cadence/date fields that make good secondary filters or sanity cursors: `transportation_and_mobility` (`updatedat`, `data_updated_at`), `solar_program_...` (`date_last_updated`), `green_building_developer_agreements` (`created_da`).
- **No native delete feed**: Socrata's public REST API does **not** expose a "deleted rows" endpoint or tombstone records for row-level deletes within a dataset. If a row is deleted at the source, the only way to detect it via the API is a periodic full-table reconciliation (compare current full snapshot's primary keys against previously seen keys). Because of this, none of these objects should be classified `cdc_with_deletes`; the connector should schedule a periodic full-`snapshot` reconciliation pass alongside the incremental `cdc` reads if hard-delete detection is required.
- Given how small and infrequently updated most of these datasets are (9–57 rows, "Annually"/"As Needed"/"Historical" cadence), a simple `snapshot`-per-run strategy is also a perfectly reasonable simpler alternative for `green_building_ratings_aggregate`, `solar_program_current_incentive_levels_and_available_capacity`, `green_building_energy_code_compliance`, `green_building_developer_agreements`, `coa_energy_codes_timeline`, and `discount_monthly_new_enrollment_by_zip` — call this out as an implementation choice, not a documentation gap.


## **Read API for Data Retrieval**

- **Method**: `GET` only (read-only public data; no write/POST operations are documented or needed for this connector).
- **Response format**: `.json` suffix on the resource path returns JSON (array of row objects); `.csv` and `.xml` are also available on the same 4x4 ID (e.g. `/resource/{4x4}.csv`). This connector standardizes on `.json`.
- **Required query parameters**: none — `GET /resource/{4x4}.json` with no parameters returns the first page of rows (default page size — SODA caps a single page at **50,000 rows**, but the practical default without `$limit` is much smaller, so an explicit `$limit` should always be set).
- **Optional / commonly used SODA query parameters**:
  - `$select` — choose columns, including system fields (`:id`, `:created_at`, `:updated_at`) via explicit name or wildcard (`$select=:*,*`).
  - `$where` — SoQL filter expression, e.g. `$where=:updated_at > '2024-01-01T00:00:00.000'`, `$where=fiscal_year='2024'`.
  - `$order` — sort, e.g. `$order=:updated_at`, `$order=effective_date DESC`.
  - `$limit` — page size (max 50,000 per Socrata's paging documentation; recommend 1,000–5,000 for these small reference datasets).
  - `$offset` — zero-indexed row offset for offset-based pagination (`$offset=1000&$limit=1000` for page 2, etc.).
  - `$q` — full-text search across all columns.
  - `$$app_token` — legacy query-string form of the app token (header form `X-App-Token` preferred).
- **Pagination pattern** (works uniformly across all 7 objects):

```bash
# page 1
curl -H "X-App-Token: {APP_TOKEN}" \
  "https://data.austintexas.gov/resource/{4x4}.json?\$order=:id&\$limit=1000&\$offset=0"
# page 2
curl -H "X-App-Token: {APP_TOKEN}" \
  "https://data.austintexas.gov/resource/{4x4}.json?\$order=:id&\$limit=1000&\$offset=1000"
```
Stop paginating when a page returns fewer rows than `$limit`. Given all 7 datasets here are small (9–506 rows), a single page (`$limit=5000`, no `$offset` loop needed) is sufficient in practice.

- **Incremental read pattern** (general, applies to all 7 objects via system fields):

```bash
curl -H "X-App-Token: {APP_TOKEN}" \
  "https://data.austintexas.gov/resource/{4x4}.json?\$select=:*,*&\$where=:updated_at > '{last_cursor_iso8601}'&\$order=:updated_at&\$limit=5000"
```

- **Delete handling**: not supported natively (see **Object's ingestion type** above). No dedicated delete/tombstone endpoint exists on this API surface.
- **API comparison**: The only alternative read surface is the bulk `/resource/{4x4}.csv` or `/resource/{4x4}.xml` export, or the full `/api/views/{4x4}/rows.csv?accessType=DOWNLOAD` bulk-download endpoint (does not require an app token, but does not support `$where`/incremental filtering — full snapshot only). The `.json` resource endpoint documented above is preferred because it supports filtering, ordering, and pagination.
- **Rate limits**: No published fixed numeric limit. Without `X-App-Token`: shared, low, per-IP throttle. With `X-App-Token`: effectively unthrottled for legitimate use; `429 Too Many Requests` returned if throttled either way. The connector should always send `X-App-Token` and implement retry-with-backoff on `429`.


## **Field Type Mapping**

| Socrata `dataTypeName` | Standard type | Notes |
|---|---|---|
| `text` | string | Default type for free-text and most categorical/ID-like fields (Socrata frequently returns numeric-looking values as `text`, e.g. `fiscal_year`, `gis_id` in raw JSON — always numeric strings; cast at connector layer per documented column). |
| `number` | double / decimal | Returned as a JSON string (e.g. `"1477"`) by the REST resource endpoint, not a JSON numeric literal — the connector must parse/cast explicitly. |
| `calendar_date` | date / timestamp (no timezone) | ISO 8601-like string, e.g. `"2024-10-01T00:00:00.000"`. Local/naive — no timezone offset included. |
| `floating_timestamp` | timestamp (no timezone) | Same wire format as `calendar_date`; used for system/audit-style timestamp fields like `updatedat`. |
| `fixed_timestamp` | timestamp (UTC) | Used for the system fields `:created_at` / `:updated_at`. |
| `checkbox` | boolean | JSON `true`/`false`. |
| `url` | string / struct | May appear as a plain string or as a nested struct `{"url": "..."}` (observed for `ordinance_`, `dataset_url`, `cover_image_url`). |
| `multipolygon` / `point` / `line` / `polygon` (geo types) | GeoJSON struct | Returned as a nested GeoJSON object (`{"type": "MultiPolygon", "coordinates": [...]}"`). Only `green_building_developer_agreements.the_geom` uses this among the 7 objects here. |
| `money` | decimal | Not present in the 7 objects documented here, but a standard Socrata type on the platform generally. |

**Special behaviors**:
- **Sparse columns**: Socrata omits a key entirely from the JSON response for a given row when that field is null/blank for that row (rather than emitting `"field": null`), observed on `green_building_ratings_aggregate` and `coa_energy_codes_timeline`. The connector must treat missing keys as `NULL`, not error.
- **Auto-generated values**: the system fields `:id`, `:created_at`, `:updated_at` are Socrata-managed and not part of the published column schema; they must be explicitly selected (see **Object Schema — General notes**).
- **No foreign-key/relationship metadata** is exposed by the API for any of these 7 objects; relationships (e.g. between the catalog table's `id` and other portal datasets) are informational/documentational only.


## Sources and References

- Official Socrata SODA developer docs — App Tokens, Authentication, Pagination/Offset, System Fields, SODA3 overview — **Highest confidence** (used for Authorization, pagination, and system-fields sections).
- Live `GET /api/views/{4x4}.json` metadata calls and live `GET /resource/{4x4}.json` sample data calls against `data.austintexas.gov` for each of the 7 mapped datasets — **Highest confidence** (ground truth for actual field names/types/example payloads; metadata-derived field names were cross-checked against and superseded by observed live JSON field names where they differed).
- City of Austin Open Data Portal dataset landing pages (data.austintexas.gov) and Data.gov mirror/catalog pages for the same datasets — **High confidence** (used to identify candidate dataset titles and confirm descriptions/update cadence).
- Socrata public Discovery API (`api.us.socrata.com/api/catalog/v1`) — **High confidence** (used to resolve the exact 4x4 ID for `discount_monthly_new_enrollment_by_zip`, which did not surface via general web search).

### Research Log

| Source Type | URL | Accessed (UTC) | Confidence | What it confirmed |
|---|---|---|---|---|
| Official Docs | https://dev.socrata.com/docs/app-tokens.html | 2026-07-24 | High | App token header (`X-App-Token`), rate-limit behavior with/without token |
| Official Docs | https://support.socrata.com/hc/en-us/articles/34730618169623-SODA3-API | 2026-07-24 | High | SODA3 auth requirement change, `/export` remaining anonymous |
| Official Docs | https://dev.socrata.com/docs/queries/offset.html | 2026-07-24 | High | `$offset`/`$limit` pagination semantics, 50,000-row page cap |
| Official Docs | https://dev.socrata.com/docs/system-fields | 2026-07-24 | High | `:id`, `:created_at`, `:updated_at` system fields and how to select them |
| Live API | https://data.austintexas.gov/api/views/28ys-ieqv.json | 2026-07-24 | Highest | `transportation_and_mobility` mapping, schema, cadence |
| Live API | https://data.austintexas.gov/resource/28ys-ieqv.json | 2026-07-24 | Highest | `transportation_and_mobility` example response |
| Live API | https://data.austintexas.gov/api/views/dpvb-c5fy.json | 2026-07-24 | Highest | `green_building_ratings_aggregate` schema, cadence |
| Live API | https://data.austintexas.gov/resource/dpvb-c5fy.json | 2026-07-24 | Highest | `green_building_ratings_aggregate` example response |
| Live API | https://data.austintexas.gov/api/views/vxq2-zjmn.json | 2026-07-24 | Highest | `solar_program_current_incentive_levels_and_available_capacity` schema, cadence |
| Live API | https://data.austintexas.gov/resource/vxq2-zjmn.json | 2026-07-24 | Highest | `solar_program_...` example response, actual field names |
| Live API | https://data.austintexas.gov/api/views/i7vh-fpaj.json | 2026-07-24 | Highest | `green_building_energy_code_compliance` schema, cadence |
| Live API | https://data.austintexas.gov/resource/i7vh-fpaj.json | 2026-07-24 | Highest | `green_building_energy_code_compliance` example response |
| Live API | https://data.austintexas.gov/api/views/63mb-dbmj.json | 2026-07-24 | Highest | `green_building_developer_agreements` schema, cadence |
| Live API | https://data.austintexas.gov/resource/63mb-dbmj.json | 2026-07-24 | Highest | `green_building_developer_agreements` example response, geometry structure |
| Live API | https://data.austintexas.gov/api/views/xn7p-rafv.json | 2026-07-24 | Highest | `coa_energy_codes_timeline` schema, cadence |
| Live API | https://data.austintexas.gov/resource/xn7p-rafv.json | 2026-07-24 | Highest | `coa_energy_codes_timeline` example response |
| Live API (Discovery) | https://api.us.socrata.com/api/catalog/v1?domains=data.austintexas.gov&q=discount%20enrollment%20zip | 2026-07-24 | High | Resolved 4x4 IDs `guem-bnpv` (FY2024) and `miq7-jh88` (FY2025) for the discount enrollment dataset |
| Live API | https://data.austintexas.gov/api/views/guem-bnpv.json | 2026-07-24 | Highest | `discount_monthly_new_enrollment_by_zip` schema, cadence |
| Live API | https://data.austintexas.gov/resource/guem-bnpv.json | 2026-07-24 | Highest | `discount_monthly_new_enrollment_by_zip` example response |
| Live API | https://data.austintexas.gov/api/views/miq7-jh88.json | 2026-07-24 | High | FY2025 successor dataset schema (documented as a Known Quirk, not a separate table) |
| Portal page | https://data.austintexas.gov/Transportation-and-Mobility/Open-Data-Portal-Datasets-Austin-Transportation-an/28ys-ieqv | 2026-07-24 | Medium | Confirmed dataset title/category placement (page itself required JS; metadata pulled via API instead) |
| Portal/Catalog mirror | https://catalog.data.gov/dataset/coa-energy-codes-timeline , https://catalog.data.gov/dataset/discount-monthly-new-enrollment-by-zip , https://catalog.data.gov/dataset/green-building-energy-code-compliance , https://catalog.data.gov/dataset/solar-program-current-incentive-levels-and-available-capacity | 2026-07-24 | Medium | Cross-confirmed dataset titles/descriptions for candidate matching |
