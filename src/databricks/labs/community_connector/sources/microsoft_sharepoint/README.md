# Lakeflow Microsoft SharePoint Community Connector

This documentation describes how to configure and use the **Microsoft SharePoint** Lakeflow community connector to ingest SharePoint list metadata and list items into Databricks via the **Microsoft Graph API** (`https://graph.microsoft.com/v1.0`).

The connector authenticates with **Azure AD (Microsoft Entra ID)** using the app-only **OAuth 2.0 client-credentials** grant. It reads two objects: `lists` (snapshot) and `list_items` (change data capture with delete detection, via the Graph `delta` endpoint).

## Prerequisites

- **Microsoft 365 tenant with SharePoint Online**: A tenant containing the SharePoint site(s), lists, and list items you want to read.
- **Azure AD app registration (app-only)**: A registered application in Microsoft Entra ID configured for the client-credentials flow, with:
  - The **`Sites.Read.All`** Microsoft Graph **application** permission (not delegated), granted with **admin consent**. This read-only permission is sufficient for this connector. `Sites.ReadWrite.All` also works but grants more than is needed.
  - A **client secret** generated for the application.
- **Tenant administrator**: Admin consent is required to grant the `Sites.Read.All` application permission.
- **Network access**: The environment running the connector must be able to reach `https://login.microsoftonline.com` (for token acquisition) and `https://graph.microsoft.com` (for data).
- **Lakeflow / Databricks environment**: A workspace where you can register a Lakeflow community connector and run ingestion pipelines.

## Setup

### Required Connection Parameters

Provide the following **connection-level** options when configuring the connector. The connector performs the OAuth 2.0 client-credentials token exchange itself at runtime using `tenant_id`, `client_id`, and `client_secret` — it caches the access token and refreshes it before expiry. There is no interactive browser sign-in and no token to paste.

| Name | Type | Required | Description | Example |
|------|------|----------|-------------|---------|
| `tenant_id` | string | yes | Azure AD tenant ID or verified domain name. Found in the Azure Portal under **Azure Active Directory → Overview**. Used to build the OAuth token endpoint URL. | `contoso.onmicrosoft.com` |
| `client_id` | string | yes | Application (client) ID of the registered Azure AD application. Found on the app registration **Overview** page. | `11111111-2222-3333-4444-555555555555` |
| `client_secret` | string | yes | Client secret value for the Azure AD application registration. Found on the app registration **Certificates & secrets** page. Treat as a secret. | `abc123~secretValue...` |
| `site_url` | string | no | SharePoint site URL in colon-syntax format. Resolved once at connection time to the opaque Graph `site-id` and cached. If omitted (and `site_id` is not set), defaults to the tenant root site (`/sites/root`). | `contoso.sharepoint.com:/teams/hr` |
| `site_id` | string | no | Opaque Microsoft Graph `site-id` in composite format `hostname,spsite-id,spweb-id`. Use this if you already know the `site-id` to skip a discovery call. Takes precedence over `site_url` if both are provided. | `contoso.sharepoint.com,2C71...,2D22...` |
| `externalOptionsAllowList` | string | yes | Comma-separated list of table-specific option names allowed to pass through to the connector. This connector supports table-specific options, so this parameter must be set. | `max_pages_per_batch,top,include_system,list_id,site_url,site_id` |

The full, definitive list of supported table-specific options for `externalOptionsAllowList` is:

`max_pages_per_batch,top,include_system,list_id,site_url,site_id`

> **Note**: Table-specific options such as `list_id`, `include_system`, `top`, and `max_pages_per_batch` are **not** connection parameters. They are provided per-table via `table_configuration` in the pipeline specification. These option names must be included in `externalOptionsAllowList` for the connection to allow them. Note that `site_url` and `site_id` can be set either as connection parameters (applying to all tables) or as per-table options (overriding the connection value for a specific table).

### Registering the Azure AD Application

1. Sign in to the [Azure Portal](https://portal.azure.com) as an administrator.
2. Go to **Azure Active Directory (Microsoft Entra ID) → App registrations → New registration**.
   - Give the app a name. For an app-only (unattended) connector you do **not** need to configure a redirect URI.
3. On the app's **Overview** page, copy the **Application (client) ID** (`client_id`) and the **Directory (tenant) ID** or use your verified domain (`tenant_id`).
4. Go to **Certificates & secrets → New client secret**. Copy the secret **Value** immediately (it is shown only once) — this is your `client_secret`.
5. Go to **API permissions → Add a permission → Microsoft Graph → Application permissions**, add **`Sites.Read.All`**, then click **Grant admin consent for {tenant}**. The permission must show a green "Granted" status.
6. (Optional) Identify the SharePoint site to read. Use the colon-syntax `site_url` (e.g. `contoso.sharepoint.com:/teams/hr`) for a deterministic lookup, or leave it blank to default to the tenant root site.

### Create a Unity Catalog Connection

A Unity Catalog connection for this connector can be created in two ways via the UI:

1. Follow the **Lakeflow Community Connector** UI flow from the **Add Data** page.
2. Select any existing Lakeflow Community Connector connection for this source or create a new one, supplying `tenant_id`, `client_id`, `client_secret`, and optionally `site_url` or `site_id`.
3. Set `externalOptionsAllowList` to `max_pages_per_batch,top,include_system,list_id,site_url,site_id` (required for this connector to pass table-specific options).

The connection can also be created using the standard Unity Catalog API.

## Supported Objects

The Microsoft SharePoint connector exposes a **static list** of two tables (use the exact lowercase casing shown):

- `lists`
- `list_items`

### Object summary, primary keys, and ingestion mode

| Table | Description | Ingestion Type | Primary Key | Incremental Cursor |
|-------|-------------|----------------|-------------|--------------------|
| `lists` | Metadata for each list (generic list or document library) under the configured site. | `snapshot` | `id` (GUID string) | n/a |
| `list_items` | Row-level items belonging to a list, including their dynamic column ("field") values. | `cdc_with_deletes` | `["list_id", "id"]` (composite) | `lastModifiedDateTime` |

**Primary keys:**

- `lists`: `id` is the list GUID — always present and unique within the site.
- `list_items`: A SharePoint list item's `id` is only unique **within its list**, so the connector uses the composite key `(list_id, id)`. The connector adds the derived `list_id` and `site_id` columns to every `list_items` row for this reason. The nested `sharepointIds.listItemUniqueId` GUID is also available as a durable, rename-stable identifier.

**Incremental ingestion and delete detection (`list_items`):**

- `list_items` is ingested as `cdc_with_deletes` using the Microsoft Graph **delta** endpoint (`.../items/delta`). The connector walks the delta feed per list and persists the opaque `@odata.deltaLink` (delta token) as its offset cursor. On the next run it resumes from that token, so only created/updated/deleted items since the last run are returned.
- **Deletions** are detected because the delta feed represents a removed item with a `deleted: { "state": "deleted" }` facet instead of full field data. The connector emits these as delete tombstones on a separate delta chain, so downstream tables using SCD Type 1 (default) will have the corresponding rows removed.
- If a stored delta token becomes stale, Graph returns **`410 Gone`**; the connector automatically restarts that list's delta chain from a fresh, tokenless full enumeration.
- If `list_id` is not supplied as a table option, the connector reads the `lists` table first and iterates `list_items` for every non-system list discovered.

**Special columns to be aware of:**

- `fields` (on `list_items`): the dynamic per-list column values, stored as a **`VARIANT`** (JSON) column because the set of columns differs per list. Field values are always retrieved (the connector requests `$expand=fields` internally). Query them with Databricks variant accessors, e.g. `fields:Quantity`.
- `list_id` / `site_id` (on `list_items`): connector-derived lineage columns forming the durable composite key.
- `site_id` (on `lists`): connector-derived lineage column identifying the site the list belongs to.
- `system` (on `lists`): only populated when system (hidden) lists are requested via the `include_system` option; system lists are excluded by default.
- Nested Graph complex types (`createdBy`, `lastModifiedBy`, `list`, `contentType`, `parentReference`, `sharepointIds`, `deleted`) are modeled as nested structs, not flattened.

## Table Configurations

### Source & Destination

These are set directly under each `table` object in the pipeline spec:

| Option | Required | Description |
|---|---|---|
| `source_table` | Yes | Table name in the source system (`lists` or `list_items`) |
| `destination_catalog` | No | Target catalog (defaults to pipeline's default) |
| `destination_schema` | No | Target schema (defaults to pipeline's default) |
| `destination_table` | No | Target table name (defaults to `source_table`) |

### Common `table_configuration` options

These are set inside the `table_configuration` map alongside any source-specific options:

| Option | Required | Description |
|---|---|---|
| `scd_type` | No | `SCD_TYPE_1` (default) or `SCD_TYPE_2`. Applicable to `lists` (snapshot) and `list_items` (CDC). |
| `primary_keys` | No | List of columns to override the connector's default primary keys |
| `sequence_by` | No | Column used to order records for SCD Type 2 change tracking (e.g. `lastModifiedDateTime` for `list_items`) |
| `cluster_by` | No | List of columns to cluster the destination Delta table by (Liquid Clustering). Consumed by the pipeline; not forwarded to the source. |

### Source-specific `table_configuration` options

These options are passed per table under `table_configuration`. Every option used must also appear in the connection's `externalOptionsAllowList`.

| Option | Applies to | Required | Default | Description |
|--------|-----------|----------|---------|-------------|
| `list_id` | `list_items` | No | (all lists) | Scopes reads to a specific list GUID. If omitted, the connector discovers all non-system lists under the site and reads items from each. |
| `include_system` | `lists` | No | `false` | Set to `"true"` to include SharePoint/Graph-internal system lists (e.g. `Site Pages`, `Site Assets`), which are hidden by default. |
| `top` | `lists`, `list_items` | No | `200` | Page-size hint (`$top`) for Graph paging. The server may cap it. |
| `max_pages_per_batch` | `lists`, `list_items` | No | `100` | Maximum number of pages fetched per read call. Caps batch size and prevents unbounded reads. |
| `site_url` | `lists`, `list_items` | No | (connection value) | Overrides the connection-level `site_url` for this table. |
| `site_id` | `lists`, `list_items` | No | (connection value) | Overrides the connection-level `site_id` for this table. Takes precedence over `site_url`. |

## Data Type Mapping

### `listItem` / `list` system properties

Microsoft Graph JSON types are mapped to Spark types as follows:

| Graph Type | Example Fields | Spark Type | Notes |
|------------|----------------|------------|-------|
| `String` | `id`, `name`, `displayName`, `eTag`, `webUrl`, `description` | `StringType` | List and item GUIDs/identifiers are stored as strings. |
| `DateTimeOffset` | `createdDateTime`, `lastModifiedDateTime` | `TimestampType` | ISO 8601 with offset; `lastModifiedDateTime` is the `list_items` cursor. |
| `Boolean` | `system`, `list.hidden`, `list.contentTypesEnabled` | `BooleanType` | |
| `identitySet` (object) | `createdBy`, `lastModifiedBy` | `StructType` | Nested `user` / `application` / `device`, each `{id, displayName}`. |
| `listInfo` (object) | `list` | `StructType` | `{contentTypesEnabled, hidden, template}`. |
| `contentTypeInfo` (object) | `contentType` | `StructType` | `{id, name}`. |
| `itemReference` (object) | `parentReference` | `StructType` | Parent site/list reference. |
| `sharepointIds` (object) | `sharepointIds` | `StructType` | REST-compatibility identifiers (includes `listItemUniqueId` on items). |
| `deleted` (object) | `deleted` | `StructType` | `{state}`; only present on delta responses for removed `list_items`. |
| `fieldValueSet` (dynamic object) | `fields` | `VariantType` | Dynamic per-list column values serialized to JSON. |

### List column (`fields`) value types

The `fields` column is a `VARIANT` holding one key per list column. The underlying SharePoint column types render into JSON as follows (accessible via variant paths such as `fields:Quantity`):

| SharePoint column type | JSON value shape | Notes |
|------------------------|------------------|-------|
| text | string | Single or multi-line text; may contain HTML if rich text is enabled. |
| number / currency | number | `number` may have decimal places; `currency` includes locale formatting. |
| boolean | boolean (`true`/`false`) | May render as `0`/`1` from some clients. |
| dateTime | string (ISO 8601) | `dateOnly` vs `dateTime` per column display setting. |
| choice | string or array of strings | Multi-select choice columns return an array. |
| personOrGroup / lookup | object or array of objects | `{LookupId, LookupValue, ...}`; array when multi-value. |
| calculated | matches the formula output type | Server-computed, read-only. |
| hyperlinkOrPicture | object `{Url, Description}` | `isPicture` distinguishes image vs link. |
| term (managed metadata) | object or array of objects | Taxonomy term references. |
| geolocation / thumbnail | object | Structured value. |
| (legacy / unmapped) | string / raw JSON | Fallback for column types without a dedicated facet. |

System-provided keys present on virtually every list include `ID`, `Title` (may be absent on some document libraries), `ContentType`, `Created`, `Modified`, `Author`, and `Editor`.

## How to Run

### Step 1: Clone/Copy the Source Connector Code

Follow the Lakeflow Community Connector UI, which will guide you through setting up a pipeline using the Microsoft SharePoint connector code and place it under a project path Lakeflow can load.

### Step 2: Configure Your Pipeline

1. Update the `pipeline_spec` in the main pipeline file (e.g., `ingest.py`).
2. Reference the Unity Catalog connection configured with your Azure AD credentials, and list the tables to ingest with any table options under `table_configuration`.

Example `pipeline_spec` reading a specific list plus all lists on the site:

```json
{
  "pipeline_spec": {
    "connection_name": "sharepoint_connection",
    "object": [
      {
        "table": {
          "source_table": "lists",
          "table_configuration": {
            "include_system": "false"
          }
        }
      },
      {
        "table": {
          "source_table": "list_items",
          "table_configuration": {
            "list_id": "243bca4b-4e5e-45af-b37d-25f6135a740d",
            "top": "200"
          }
        }
      }
    ]
  }
}
```

- `connection_name` must point to the UC connection configured with your `tenant_id`, `client_id`, `client_secret`, and (optionally) `site_url` / `site_id`.
- For `list_items`, omit `list_id` to ingest items from every non-system list under the configured site, or set it to read a single list.
- To read from a site other than the connection default, set `site_url` or `site_id` in `table_configuration` (both must be in `externalOptionsAllowList`).

3. (Optional) Customize the source connector code if needed for special use cases.

### Step 3: Run and Schedule the Pipeline

Run the pipeline using your standard Lakeflow / Databricks orchestration (e.g., a scheduled job). For `list_items`:

- On the **first run**, the connector performs a full delta enumeration of each in-scope list and stores the resulting delta token as its offset.
- On **subsequent runs**, it resumes from the stored delta token, returning only created/updated/deleted items. If a token has expired (`410 Gone`), the connector automatically restarts that list's chain with a fresh full enumeration.

#### Best Practices

- **Start small**: Begin with the `lists` table (or a single `list_id` for `list_items`) to validate configuration and inspect the data shape before scaling to all lists.
- **Use incremental sync**: `list_items` uses the delta endpoint automatically, which is cheaper (1 resource unit per call with a token vs. 2 for full reads) and the Microsoft-recommended change-tracking pattern.
- **Set appropriate schedules**: Balance data freshness against SharePoint Online rate limits. SharePoint throttles per app-per-tenant using a resource-unit budget (roughly 1,250–6,250 units/minute, scaled by licensed users); avoid concurrent requests against the same site.
- **Tune paging**: Use `top` and `max_pages_per_batch` to control batch size. Raise `max_pages_per_batch` from its default of `100` only if a full backfill legitimately requires more pages.
- **Scope with `site_url`**: Prefer deterministic colon-syntax `site_url` (or a known `site_id`) over relying on discovery, especially if using a least-privilege permission model.

#### Troubleshooting

**Common Issues:**

- **Token acquisition / authentication failures (`401`)**:
  - Verify `tenant_id`, `client_id`, and `client_secret` are correct and the secret has not expired (client secrets have an expiry date in Azure).
  - Confirm the app has the **`Sites.Read.All`** *application* permission with **admin consent granted** (a green status in the Azure Portal). Delegated permissions will not work for this app-only flow.
- **`403 Forbidden` reading a site or list**:
  - The app may lack access to that specific site (e.g. under a `Sites.Selected` model) or admin consent was not fully granted. Ensure `Sites.Read.All` is consented tenant-wide.
- **Could not resolve `site-id`**:
  - Check the `site_url` is in valid colon-syntax (e.g. `contoso.sharepoint.com:/teams/hr`) and that the site exists. Alternatively supply the composite `site_id` directly.
- **Empty `fields` on `list_items`**:
  - The connector requests `$expand=fields` internally, so field values should be present. If a column is missing, confirm it is not a hidden column and that the item actually has a value.
- **Rate limiting (`429` / `503`)**:
  - The connector honors the `Retry-After` header and backs off automatically. If throttling persists, widen the schedule interval, reduce concurrency, or lower page sizes.
- **Missing system lists**:
  - System/hidden lists (e.g. `Site Pages`) are excluded by default. Set `include_system` to `"true"` on the `lists` table to surface them.

## References

- Connector implementation: `src/databricks/labs/community_connector/sources/microsoft_sharepoint/microsoft_sharepoint.py`
- Connector schemas and constants: `src/databricks/labs/community_connector/sources/microsoft_sharepoint/microsoft_sharepoint_schemas.py`
- Connector API research doc: `src/databricks/labs/community_connector/sources/microsoft_sharepoint/microsoft_sharepoint_api_doc.md`
- Connector spec: `src/databricks/labs/community_connector/sources/microsoft_sharepoint/connector_spec.yaml`
- Official Microsoft Graph documentation:
  - SharePoint API overview: `https://learn.microsoft.com/en-us/graph/api/resources/sharepoint?view=graph-rest-1.0`
  - List resource: `https://learn.microsoft.com/en-us/graph/api/resources/list?view=graph-rest-1.0`
  - List items: `https://learn.microsoft.com/en-us/graph/api/listitem-list?view=graph-rest-1.0`
  - List item delta (change tracking): `https://learn.microsoft.com/en-us/graph/api/listitem-delta?view=graph-rest-1.0`
  - Client credentials (app-only) auth: `https://learn.microsoft.com/en-us/graph/auth-v2-service`
- SharePoint Online throttling guidance: `https://learn.microsoft.com/en-us/sharepoint/dev/general-development/how-to-avoid-getting-throttled-or-blocked-in-sharepoint-online`
