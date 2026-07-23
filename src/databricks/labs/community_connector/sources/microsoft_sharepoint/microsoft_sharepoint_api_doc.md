# **Microsoft SharePoint (Microsoft Graph API) API Documentation**

## **Scope note**

This document covers the **two tables** in scope for this research batch:

| Table | Endpoint |
|-------|----------|
| `lists` | `GET /sites/{site-id}/lists` — Enumerate the lists under the site |
| `list_items` | `GET /sites/{site-id}/lists/{list-id}/items` — Enumerate the listItems under the list |

Other SharePoint-via-Graph surfaces (`drives`/`driveItems` document libraries, `sites` sub-site enumeration, `contentTypes`, `columns`, site pages, permissions) are **out of scope** for this batch and are not documented here beyond what is needed to resolve `site-id`/`list-id` path parameters.

## **Authorization**

- **Chosen method**: OAuth 2.0 **Client Credentials** grant (app-only) against Microsoft Entra ID (formerly Azure AD). This is the standard method for unattended/service connectors; it does not require a signed-in user and does not use a `refresh_token`.
- **Token endpoint**:

```
POST https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token
Content-Type: application/x-www-form-urlencoded

client_id={client_id}
&client_secret={client_secret}
&grant_type=client_credentials
&scope=https://graph.microsoft.com/.default
```

- **Response**: JSON body with `access_token` (Bearer token), `token_type`, and `expires_in` (seconds, typically 3600). The connector must cache the token and refresh it (repeat the client-credentials call) before/at expiry — there is no separate refresh token in this flow.
- **Auth placement on Graph calls**:

```
Authorization: Bearer <access_token>
```

- **Connector-stored configuration** (deviates from the generic OAuth note of storing `client_id`/`client_secret`/`refresh_token`, since app-only client-credentials has no `refresh_token`):
  - `tenant_id` — Azure AD tenant ID or verified domain (e.g. `contoso.onmicrosoft.com`).
  - `client_id` — Application (client) ID of the Azure AD app registration.
  - `client_secret` — Client secret (or certificate, not covered here) for the app registration.
  - The connector performs the client-credentials exchange itself at runtime; it does **not** run an interactive/user-facing OAuth consent flow.
- **Required Microsoft Graph application permissions** (admin consent required), least-privileged first:
  - `Sites.Read.All` — read-only access to SharePoint sites, lists, and list items across the tenant. **Recommended for this connector** since only read operations are performed.
  - `Sites.ReadWrite.All` — higher-privileged alternative; only needed if write-back is required (out of scope for this connector).
  - `Sites.Selected` — narrower alternative that restricts the app to specific site collections granted individually via the Sites API; **not supported** by the `/sites?search=` endpoint used for site discovery (see Known Quirks), so it requires the caller to already know the target site's hostname/path.
- **Base URL**: `https://graph.microsoft.com/v1.0`

**Example authenticated request** (token acquisition + list call):

```bash
# 1. Acquire an app-only access token
curl -X POST "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "client_id={client_id}&client_secret={client_secret}&grant_type=client_credentials&scope=https://graph.microsoft.com/.default"

# 2. Use the returned access_token as a Bearer token
curl -H "Authorization: Bearer {access_token}" \
  "https://graph.microsoft.com/v1.0/sites/{site-id}/lists"
```

## **Resolving `site-id` (required path parameter)**

Every endpoint in scope is nested under `/sites/{site-id}/...`. The `site-id` is **not** the site's URL; it must be resolved first. The connector should require a human-friendly `site_url` (or `hostname` + `site_path`) as connection configuration and resolve it to a Graph `site-id` once (caching the result), rather than asking users to supply the opaque Graph ID directly.

Supported resolution methods (all under `GET https://graph.microsoft.com/v1.0/sites/...`):

| Path | Description | Least-privileged permission |
|------|-------------|------------------------------|
| `GET /sites/root` | The organization's default root site. | `Sites.Read.All` |
| `GET /sites/{hostname}:/{server-relative-path}` | Address a site by SharePoint hostname + server-relative path (colon syntax). E.g. `/sites/contoso.sharepoint.com:/teams/hr`. **Recommended method** — deterministic, single result, no search ranking involved. | `Sites.Read.All` |
| `GET /sites/{hostname}:/{server-relative-path}:/` | Same as above, with a trailing colon to explicitly transition back to resource addressing (useful when chaining further path segments). | `Sites.Read.All` |
| `GET /sites?search={query}` | Free-text search across the tenant for sites matching keywords; returns a collection of site objects with `id` populated. Useful for discovery when the exact server-relative path is unknown, but is a ranked search (not a deterministic lookup) and does not support `Sites.Selected`. | `Sites.Read.All` |
| `GET /sites/{hostname}` | Root site (`SPWeb`) in the default site collection for that hostname. | `Sites.Read.All` |
| `GET /sites/{hostname},{spsite-id}` | Root site in a specific site collection (`SPSite`) identified by GUID. | `Sites.Read.All` |
| `GET /sites/{hostname},{spsite-id},{spweb-id}` | A specific sub-site (`SPWeb`) within a specific site collection, addressed by both GUIDs. This is the canonical form of the `id` field returned by the above lookups. | `Sites.Read.All` |

**Example — resolve a site by path:**

```bash
curl -H "Authorization: Bearer {access_token}" \
  "https://graph.microsoft.com/v1.0/sites/contoso.sharepoint.com:/teams/hr"
```

**Example response** (the `id` field is the value to use as `{site-id}` in all subsequent calls):

```json
{
  "id": "contoso.sharepoint.com,2C712604-1370-44E7-A1F5-426573FDA80A,2D2244C3-251A-49EA-93A8-39E1C3A060FE",
  "name": "hr",
  "displayName": "HR",
  "webUrl": "https://contoso.sharepoint.com/teams/hr"
}
```

Note the `site-id` is a **composite string** `{hostname},{spsite-id},{spweb-id}` — it must be passed through URL-unescaped (commas are literal) in the path segment of subsequent requests.

**Example — search for a site by keyword** (fallback if the exact path is unknown):

```bash
curl -H "Authorization: Bearer {access_token}" \
  "https://graph.microsoft.com/v1.0/sites?search=HR"
```

## **Resolving `list-id` (required path parameter for `list_items`)**

The `list-id` (a GUID string, e.g. `243bca4b-4e5e-45af-b37d-25f6135a740d`) is obtained from the `id` field returned by the `lists` table's own endpoint (`GET /sites/{site-id}/lists`) — see **Object Schema → `lists`** below. There is no separate "resolve list" endpoint; the `lists` object list **is** the list-id discovery mechanism. Lists can alternatively be addressed by their `name`/`displayName` in some SharePoint REST-compatibility URL patterns, but the connector should use the GUID `id` returned by the `lists` endpoint as the canonical, stable identifier.

## **Object List**

The object list for this connector is **static**, scoped to the two tables below (both are children of a `site`, which itself is resolved via connection configuration, not a queryable connector table in this batch):

| Object Name | Description | Primary Endpoint | Parent | Ingestion Type |
|-------------|-------------|-------------------|--------|----------------|
| `lists` | Metadata for each list (generic list or document library) defined under the configured site. Discoverable via API. | `GET /sites/{site-id}/lists` | `site` (via `site_url` connection config) | `snapshot` |
| `list_items` | Row-level items belonging to a specific list, including their column ("field") values. Discoverable via API, layered under `lists` (requires `list-id` from the `lists` table). | `GET /sites/{site-id}/lists/{list-id}/items` | `lists` | `cdc_with_deletes` (via delta endpoint — see Read API section) |

**Connector scope / connection parameters**:
- `tenant_id`, `client_id`, `client_secret` — see Authorization.
- `site_url` (required) — e.g. `contoso.sharepoint.com:/teams/hr` or `contoso.sharepoint.com`; resolved once to a Graph `site-id` at connection time and cached.
- `list_id` (table option on `list_items`, optional) — if provided, scopes `list_items` reads to a specific list. If omitted, the connector should first read the `lists` table and iterate `list_items` for every non-hidden list returned (lists with the `system` facet, i.e. Graph-internal lists, are hidden by default and excluded unless explicitly requested — see Known Quirks).

## **Object Schema**

General notes:
- Microsoft Graph exposes a well-defined JSON schema for the `list` and `listItem` resource types (documented below). List **columns** (i.e. the user-defined fields on a list, such as "Employee" or "Quantity" in the examples below) are dynamic per list/site and are exposed through the `fields` facet on `listItem`, keyed by the `columnDefinition.name` of each column. See **Field Type Mapping** for how column types map to standard types.
- Nested Graph complex types (`identitySet`, `listInfo`, `sharepointIds`, `itemReference`, `contentTypeInfo`) are modeled as **nested structs** rather than flattened.

### `lists` object

**Source endpoint**:
`GET https://graph.microsoft.com/v1.0/sites/{site-id}/lists`

**Key behavior**:
- Returns all **non-hidden** lists under the site (document libraries and generic lists alike).
- Lists with the `system` facet (Graph/SharePoint-internal lists such as `Site Pages`, `Site Assets`, etc.) are **hidden by default**. To include them, add `system` to a `$select` query parameter, e.g. `?$select=id,name,system`.
- Supports standard `@odata.nextLink` pagination for tenants/sites with very large numbers of lists (uncommon, since a site typically has a small number of lists).
- No delta/incremental endpoint is documented for the `list` resource itself; treated as `snapshot`.

**High-level schema (connector view)**:

| Column Name | Type | Description |
|-------------|------|-------------|
| `id` | string | Unique identifier (GUID) of the list. Read-only. **Primary key.** |
| `name` | string | Internal/API name of the list. Read-only. |
| `displayName` | string | User-facing title of the list. |
| `description` | string | Descriptive text for the list. |
| `webUrl` | string (url) | URL that displays the list in the browser. Read-only. |
| `createdDateTime` | string (ISO 8601 datetime) | When the list was created. Read-only. |
| `lastModifiedDateTime` | string (ISO 8601 datetime) | When the list (or its items) was last modified. Read-only. |
| `createdBy` | struct (`identitySet`) | Identity of the creator. See nested schema. Read-only. |
| `lastModifiedBy` | struct (`identitySet`) | Identity of the last modifier. See nested schema. Read-only. |
| `eTag` | string | ETag / version stamp for the list resource. Read-only. |
| `list` | struct (`listInfo`) | Template and configuration details. See nested schema. |
| `parentReference` | struct (`itemReference`) | Parent site information. |
| `sharepointIds` | struct (`sharepointIds`) | SharePoint REST-compatibility identifiers. See nested schema. Read-only. |
| `system` | boolean | If present/true, the list is system-managed (only returned when `system` is explicitly `$select`ed). Read-only. |

**Nested `list` (listInfo) struct**:

| Field | Type | Description |
|-------|------|-------------|
| `contentTypesEnabled` | boolean | Whether content types are enabled for this list. |
| `hidden` | boolean | Whether the list isn't normally visible in the SharePoint UI. |
| `template` | string | Base list template. Common values: `documentLibrary`, `genericList`, `tasks`, `survey`, `links`, `announcements`, `contacts`, `discussionBoard`, `pictureLibrary`, and others (Graph documents this as non-exhaustive; connector should treat unknown values as opaque strings). |

**Nested `createdBy` / `lastModifiedBy` (identitySet) struct**:

| Field | Type | Description |
|-------|------|-------------|
| `user` | struct or null | `{ "id": string, "displayName": string }` — present when the actor is a user. |
| `application` | struct or null | `{ "id": string, "displayName": string }` — present when the actor is an application (app-only actions). |
| `device` | struct or null | `{ "id": string, "displayName": string }` — present when the actor is a device. |

**Nested `sharepointIds` struct**:

| Field | Type | Description |
|-------|------|-------------|
| `listId` | string (GUID) | Same value as top-level `id`. |
| `siteId` | string (GUID) | The `SPSite` GUID (site collection). |
| `siteUrl` | string | The SharePoint site URL. |
| `tenantId` | string (GUID) | The tenant GUID. |
| `webId` | string (GUID) | The `SPWeb` GUID. |

**Example request**:

```bash
curl -H "Authorization: Bearer {access_token}" \
  "https://graph.microsoft.com/v1.0/sites/contoso.sharepoint.com,2C712604-1370-44E7-A1F5-426573FDA80A,2D2244C3-251A-49EA-93A8-39E1C3A060FE/lists"
```

**Example response**:

```json
{
  "value": [
    {
      "id": "b57af081-936c-4803-a120-d94887b03864",
      "name": "Documents",
      "createdDateTime": "2016-08-30T08:32:00Z",
      "lastModifiedDateTime": "2016-08-30T08:32:00Z",
      "list": {
        "hidden": false,
        "template": "documentLibrary"
      }
    },
    {
      "id": "1234-112-112-4",
      "name": "MicroFeed",
      "createdDateTime": "2016-08-30T08:32:00Z",
      "lastModifiedDateTime": "2016-08-30T08:32:00Z",
      "list": {
        "hidden": false,
        "template": "genericList"
      }
    }
  ]
}
```

> The columns listed above define the **complete connector schema** for the `lists` table. If additional list fields (e.g. `columns`, `contentTypes` relationships) are needed in the future, they must be added as new columns/nested structs here.

### `list_items` object

**Source endpoint**:
`GET https://graph.microsoft.com/v1.0/sites/{site-id}/lists/{list-id}/items`

**Key behavior**:
- Returns items ("rows") belonging to a specific list.
- Column ("field") values are **not** included by default — they must be requested via `$expand=fields` (all columns) or `$expand=fields(select=Column1,Column2)` (specific columns only, more efficient).
- Supports `$filter` (`eq`, `ne`, `lt`, `gt`, `le`, `ge`, `startswith`) on both top-level `listItem` properties and on field values via `fields/ColumnName` syntax (e.g. `fields/Quantity lt 600`). Filtering works best on **indexed** columns; the service can only filter on one indexed field at a time.
- For incremental/change-tracking reads with delete detection, use the dedicated **delta** endpoint (`.../items/delta`) documented in the Read API section below, rather than polling this endpoint with a modified-date filter (SharePoint list columns do not reliably expose a documented, filterable "last modified" system column across all list templates).

**High-level schema (connector view)**:

| Column Name | Type | Description |
|-------------|------|-------------|
| `id` | string | Unique identifier of the item **within its list** (typically a small integer represented as a string, e.g. `"4"`). Not globally unique — combine with `list-id` (and `site-id`) for a globally unique connector key. Read-only. **Primary key** (composite with `list_id` at the connector level). |
| `contentType` | struct (`contentTypeInfo`) | `{ "id": string, "name": string }` — the SharePoint content type of this item (e.g. `Item`, `Document`, `Folder`). |
| `fields` | struct (`fieldValueSet`, dynamic) | The column values for this item. Only populated when `$expand=fields` is used. Keys correspond to the `name` (not `displayName`) of each `columnDefinition` on the list — see Field Type Mapping. Always includes system fields `ID`, `Title` (if present), `ContentType`, `Modified`, `Created`, `Author`, `Editor`. |
| `createdBy` | struct (`identitySet`) | Identity of the creator. Read-only. |
| `createdDateTime` | string (ISO 8601 datetime) | When the item was created. Read-only. |
| `lastModifiedBy` | struct (`identitySet`) | Identity of the last modifier. Read-only. |
| `lastModifiedDateTime` | string (ISO 8601 datetime) | When the item was last modified. Read-only. |
| `eTag` | string | ETag / version stamp. Read-only. |
| `webUrl` | string (url) | URL that displays the item in the browser. Read-only. |
| `description` | string | Descriptive text for the item (rarely populated for list items; more common on document library items). |
| `name` | string | The name/title of the item. Read-only. |
| `parentReference` | struct (`itemReference`) | Parent list/site information. |
| `sharepointIds` | struct (`sharepointIds`) | REST-compatibility identifiers, including `listItemId` and `listItemUniqueId` (a GUID, useful as a stable global key). Read-only. |
| `deleted` | struct (`deleted`) or absent | Only present when reading via the **delta** endpoint; indicates the item was deleted. `{ "state": "deleted" }`. |
| `list_id` | string (connector-derived) | The `{list-id}` path parameter used to retrieve this item. Needed to disambiguate `id` across lists. |
| `site_id` | string (connector-derived) | The `{site-id}` path parameter used to retrieve this item. |

**Nested `sharepointIds` struct** (list-item-specific fields, in addition to those documented under `lists`):

| Field | Type | Description |
|-------|------|-------------|
| `listItemId` | string | Same value as top-level `id`. |
| `listItemUniqueId` | string (GUID) | A GUID uniquely identifying the item, stable across renames — recommended as part of the connector's durable key alongside `list_id`. |

**Nested `fields` (fieldValueSet) struct**: dynamic — one key per list column. See **Field Type Mapping** for the type mapping from `columnDefinition` facets to values in this dictionary. Common system-provided keys present on virtually every list: `ID` (integer, duplicate of top-level `id`), `Title` (string, may be absent on lists without a Title column such as some document libraries), `ContentType` (string), `Created` / `Modified` (ISO 8601 datetime strings), `Author` / `Editor` (string, "Display Name" — a lookup rendering of `createdBy`/`lastModifiedBy`).

**Example request — get items with specific expanded fields**:

```bash
curl -H "Authorization: Bearer {access_token}" \
  "https://graph.microsoft.com/v1.0/sites/contoso.sharepoint.com,2C712604-1370-44E7-A1F5-426573FDA80A,2D2244C3-251A-49EA-93A8-39E1C3A060FE/lists/243bca4b-4e5e-45af-b37d-25f6135a740d/items?expand=fields(select=Name,Color,Quantity)"
```

**Example response**:

```json
{
  "value": [
    {
      "id": "2",
      "fields": {
        "Name": "Gadget",
        "Color": "Red",
        "Quantity": 503
      }
    },
    {
      "id": "4",
      "fields": {
        "Name": "Widget",
        "Color": "Blue",
        "Quantity": 2357
      }
    },
    {
      "id": "7",
      "fields": {
        "Name": "Gizmo",
        "Color": "Green",
        "Quantity": 92
      }
    }
  ]
}
```

**Example response — full item (via `$expand=fields`, without `select`)**:

```json
{
  "fields": {
    "Title": "Access card",
    "Employee": "Ryan Gregg",
    "EmployeeId": "10",
    "CardSerial": "01235492",
    "Alias": "RGregg",
    "ID": 1,
    "ContentType": "Item",
    "Modified": "2016-09-19T23:15:25-07:00",
    "Created": "2016-09-19T23:15:25-07:00"
  },
  "createdBy": {
    "user": {
      "id": "b757fdcb-0271-4807-b243-504139e4ba04",
      "displayName": "Ryan Gregg"
    }
  },
  "createdDateTime": "2016-09-20T06:15:25Z",
  "eTag": "48e941c3-9515-4c48-9760-c07c90c79d48,1",
  "id": "4",
  "lastModifiedBy": {
    "user": {
      "id": "b757fdcb-0271-4807-b243-504139e4ba04",
      "displayName": "Ryan Gregg"
    }
  },
  "lastModifiedDateTime": "2016-09-20T06:15:25Z"
}
```

**Example request — filtered read with expanded fields**:

```bash
curl -H "Authorization: Bearer {access_token}" \
  "https://graph.microsoft.com/v1.0/sites/contoso.sharepoint.com,2C712604-1370-44E7-A1F5-426573FDA80A,2D2244C3-251A-49EA-93A8-39E1C3A060FE/lists/243bca4b-4e5e-45af-b37d-25f6135a740d/items?expand=fields(select=Name,Color,Quantity)&\$filter=fields/Quantity lt 600"
```

> The columns listed above define the **complete connector schema** for the `list_items` table (top-level `listItem` properties). The `fields` struct is inherently dynamic per list; the connector should treat it as a variant/map type or discover columns via `GET /sites/{site-id}/lists/{list-id}/columns` (out of scope for this batch, noted for future work) to build a typed schema per list.

## **Get Object Primary Keys**

- **`lists`**: `id` (string GUID). Static — always present, always unique within the site. Retrieved as part of every `lists` API response; no separate lookup needed.
- **`list_items`**: `id` (string, typically a small integer) is **only unique within a single list**. The connector must use a composite key of `(list_id, id)` — or, more durably, `sharepointIds.listItemUniqueId` (a GUID that is stable across item ID reassignment scenarios and unique tenant-wide) combined with `list_id` for disambiguation. Both are static/structural facts about the `listItem` resource, not retrieved via a separate API call — they are present in every `list_items` response when `$select` includes `id` (default) or `sharepointIds` (must be explicitly selected/expanded, as it is not returned by default; confirm via `$select=id,sharepointIds`).

## **Object's ingestion type**

| Object | Ingestion Type | Rationale |
|--------|-----------------|-----------|
| `lists` | `snapshot` | No delta/change-tracking endpoint is documented for the `list` resource itself. `lastModifiedDateTime` is present but there's no confirmed `$filter` support on the `lists` collection endpoint to use it as a cursor safely; site-level list counts are typically small, so full snapshot reads are cheap. |
| `list_items` | `cdc_with_deletes` | The dedicated `GET /sites/{site-id}/lists/{list-id}/items/delta` endpoint returns newly created/updated items and represents deletions via a `deleted: { "state": "deleted" }` facet on the item, without requiring a full re-read of the list. This is the officially recommended way to track changes (see Read API section). |

## **Read API for Data Retrieval**

### `lists`

- **Method**: `GET /sites/{site-id}/lists`
- **Required params**: none beyond the `site-id` path segment.
- **Optional params**: `$select` (to include the normally-hidden `system` facet and pick specific properties), `$filter`, `$expand` (e.g. `columns`, `contentTypes` — out of scope for this batch).
- **Pagination**: standard Graph server-side paging. If the response includes `@odata.nextLink`, issue a `GET` on that exact URL (it already encodes any prior query parameters) to fetch the next page; stop when no `@odata.nextLink` is present. In practice, sites rarely have enough lists to trigger a second page, but the connector must still implement the loop defensively.
- **Incremental / deletes**: not supported for this collection (see Ingestion Type above); read as a full snapshot each run.
- **Rate limits**: see shared Rate Limits section below. This is a **multi-item query** = 2 resource units per call.

### `list_items`

- **Primary read method** (full/snapshot pass): `GET /sites/{site-id}/lists/{list-id}/items?expand=fields`
  - **Required params**: `site-id`, `list-id` path segments.
  - **Optional params**:
    - `$expand=fields` or `$expand=fields(select=Col1,Col2,...)` — required to retrieve column values; omit only if only `listItem` system properties (`id`, timestamps, etc.) are needed.
    - `$filter` — `fields/ColumnName op value` or top-level property filters, using `eq`, `ne`, `lt`, `gt`, `le`, `ge`, `startswith`. Best performance on indexed columns; only one indexed field can be filtered per request.
    - `$select` — restrict top-level `listItem` properties returned.
    - `$top` — client-side page-size hint (server may cap it).
  - **Pagination**: standard `@odata.nextLink` chasing — follow the full URL in `@odata.nextLink` (which carries forward `$expand`/`$filter`/`$top`) until it's absent.
- **Incremental read method** (recommended for ongoing syncs, supports deletes): `GET /sites/{site-id}/lists/{list-id}/items/delta`
  - **Required params**: `site-id`, `list-id` path segments.
  - **Optional params**: `token` (omit for a fresh full enumeration; `latest` to fetch only the current deltaLink without enumerating existing items; a previously-saved delta token to resume). Also supports `$select`, `$expand`, `$top`.
  - **Pagination / cursor protocol**:
    1. First call `GET .../items/delta` with no `token` (or with a previously stored delta token appended as `?token=...` — the full `@odata.deltaLink` URL from the prior run should be reused directly rather than re-constructing it).
    2. Each response page includes either `@odata.nextLink` (more pages remain in this delta batch — follow it) or `@odata.deltaLink` (this was the last page — **persist this URL verbatim** as the cursor for the next incremental run).
    3. Deleted items appear in the delta feed with a `deleted: { "state": "deleted" }` facet instead of full field data; the connector should treat these as delete events keyed by `id`/`sharepointIds.listItemUniqueId`.
    4. The delta feed reflects **latest state per item**, not a full change log — if an item changed twice between syncs, only its current state is returned once.
    5. A `410 Gone` response with error codes `resyncChangesApplyDifferences` or `resyncChangesUploadDifferences` (plus a `Location` header with a fresh `nextLink`) indicates the stored delta token is stale (e.g. very long gap since last sync) and a full resync is required — the connector must fall back to a full read and restart the delta chain from a fresh (tokenless) call.
  - **Rate limit note**: delta calls **with a token** are billed at the discounted rate of **1 resource unit** (vs. 2 for a token-less/full multi-item query), so the delta endpoint is both functionally and cost-wise the preferred read path once an initial baseline has been established.
- **Comparison — plain list vs. delta**: use the plain `items?expand=fields` endpoint for the initial full backfill (simpler, supports arbitrary `$filter`), then switch to `.../items/delta` for all subsequent incremental runs (supports deletes, cheaper per Graph resource-unit accounting, and is the Microsoft-recommended pattern for change tracking — CSOM/REST "get all + diff" polling is explicitly discouraged by Microsoft's own scanning-application guidance).
- **Table options**: `list_id` (required for a per-list connector table instance, or iterate all lists discovered via the `lists` table).

### Rate Limits (applies to both `lists` and `list_items`)

- SharePoint Online (including access via Microsoft Graph) throttles using a **resource-unit** cost model, not a flat requests-per-second limit:

| Resource units per request | Applies to |
|------------------------------|------------|
| 1 | Single-item GET, delta query **with** a token, file download |
| 2 | Multi-item query (e.g. list `lists`, list `items` without a delta token) |
| 5 | Any request involving `$expand=permissions` or permission operations |

- **Per-app-per-tenant limits** (default; Microsoft may adjust): 1,250–6,250 resource units per minute and 1.2M–6M resource units per 24 hours, scaled by the tenant's licensed user count.
- On exceeding a limit, Graph returns **HTTP 429** ("Too many requests") or **HTTP 503** ("Server Too Busy"), always with a `Retry-After` header (seconds to wait). SharePoint Online also returns (best-effort, currently beta) `RateLimit-Limit` / `RateLimit-Remaining` / `RateLimit-Reset` headers the connector should read proactively to back off before hitting a hard 429.
- The connector **must** honor `Retry-After` — retrying before the indicated wait counts against quota and worsens throttling.
- Recommendation: prefer the delta endpoint (1 unit/call after baseline) over repeated full `items` reads (2 units/call), avoid concurrent requests against the same site, and set a descriptive `User-Agent` (`NONISV|{Company}|{AppName}/{Version}`) to get traffic prioritization per Microsoft's decoration guidance.

## **Field Type Mapping**

### `listItem` / `list` system properties

| Graph Type | Standard Type | Notes |
|------------|----------------|-------|
| `String` | string | `id`, `name`, `eTag`, `webUrl`, `description` |
| `DateTimeOffset` | timestamp (UTC) | `createdDateTime`, `lastModifiedDateTime` — ISO 8601 with offset |
| `Boolean` | boolean | e.g. `listInfo.hidden`, `listInfo.contentTypesEnabled`, `system` |
| `identitySet` (struct) | struct | `createdBy`, `lastModifiedBy` — nested `user`/`application`/`device` sub-structs, each `{id: string, displayName: string}` |
| `listInfo` (struct) | struct | `list` property on `lists` — see nested schema above |
| `contentTypeInfo` (struct) | struct `{id: string, name: string}` | `contentType` on `list_items` |
| `sharepointIds` (struct) | struct | GUID/string identifiers for REST compatibility |
| `deleted` (struct) | struct `{state: string}` | Only present on delta responses for removed items |
| `fieldValueSet` (dynamic dict) | map/variant (or per-list typed struct if the connector resolves `columnDefinition`s) | See column type mapping below |

### List column (`columnDefinition`) type facets → `fields` value types

Each list column has exactly one type facet populated on its `columnDefinition` (retrievable via `GET /sites/{site-id}/lists/{list-id}/columns`, out of scope for this batch but relevant for typed-schema generation in a future batch). The corresponding value found under `listItem.fields[column.name]` maps as follows:

| Column facet | Standard Type | Notes / constraints |
|---------------|----------------|----------------------|
| `text` (`textColumn`) | string | Single line or multi-line text; multi-line may contain HTML if rich text is enabled. |
| `number` (`numberColumn`) | double / decimal | May have `decimalPlaces` and min/max validation. |
| `boolean` (`booleanColumn`) | boolean | Rendered as `0`/`1` or `true`/`false` depending on client. |
| `dateTime` (`dateTimeColumn`) | timestamp or date | `displayAs` indicates `dateOnly` vs `dateTime`. |
| `choice` (`choiceColumn`) | string (enum) or array of strings | `allowTextEntry`, `choices` list; multi-select choice columns return an array. |
| `currency` (`currencyColumn`) | decimal | Includes `locale` for currency symbol formatting. |
| `personOrGroup` (`personOrGroupColumn`) | struct or array of structs | Resolves to identity-like objects (`LookupId`, `LookupValue`, email); multi-value if `allowMultipleSelection` is true. |
| `lookup` (`lookupColumn`) | struct or array of structs (`LookupId`/`LookupValue`) | References another list's column; `allowMultipleValues` controls array vs scalar. |
| `calculated` (`calculatedColumn`) | type of `outputType` (string, number, boolean, dateTime) | Value is server-computed from a formula; read-only. |
| `term` (`termColumn`) | struct or array of structs | Managed metadata (taxonomy) term references. |
| `hyperlinkOrPicture` (`hyperlinkOrPictureColumn`) | struct `{Url, Description}` | `isPicture` distinguishes image vs link rendering. |
| `thumbnail` (`thumbnailColumn`) | struct | Image thumbnail metadata. |
| `geolocation` (`geolocationColumn`) | struct `{latitude, longitude, ...}` | |
| `contentApprovalStatus` (`contentApprovalStatusColumn`) | string (enum) | Approval workflow status. |
| *(none populated)* | opaque / string fallback | Graph documents that some legacy SharePoint field types (`SPFieldType`) aren't yet represented by a type facet; connector should fall back to treating the raw JSON value as a string/variant. |

### Special field behaviors

- `id` (top-level, on both `list` and `listItem`) is **auto-generated**, immutable, and read-only.
- `ID` (inside `fields`) on `list_items` duplicates the top-level `id` as an integer rather than a string — useful for numeric sorting/filtering (`fields/ID`).
- `eTag` changes on every update and can be used for optimistic-concurrency checks but **not** as an incremental cursor (it is not orderable/comparable across items).
- Hidden columns (`columnDefinition.hidden = true`) and hidden lists (`listInfo.hidden = true` / presence of `system` facet) are excluded from default responses and require explicit `$select` to surface — the connector should decide per-table-option whether to include them (default: exclude, matching Graph's own default).

## Known Quirks

- `Sites.Selected` application permission (a narrower, per-site-grant alternative to `Sites.Read.All`) is **not supported** by the `/sites?search=` discovery endpoint — if a customer wants to use `Sites.Selected` for least-privilege, the connector must be configured with the exact `site_url` (colon-syntax) rather than relying on search-based discovery.
- The `site-id` returned by discovery endpoints is a **composite string** (`hostname,spsite-id,spweb-id`) containing commas; it must be treated as an opaque token and passed through unmodified in subsequent path segments — do not attempt to parse or reconstruct it from its parts.
- `lists` hides Graph/SharePoint-system lists (`system` facet) by default; if a customer's use case needs those (e.g. `Site Pages`), the connector must add `system` to `$select` explicitly.
- `list_items.fields` is empty/absent unless `$expand=fields` (or the `select=` variant) is used — this is the single most common integration mistake against this API and must be a hard-coded default in the connector, not an opt-in table option.
- List item `id` is only unique **within its list**; the connector's primary/durable key must be scoped by `list_id` (see Get Object Primary Keys).
- Delta tokens can expire (returns `410 Gone`); the connector must catch this and fall back to a fresh full read + new delta chain rather than failing the sync.

## Sources and References

See Research Log below for full citations. Summary of confidence:
- **Official Microsoft Graph docs (learn.microsoft.com/graph)** — highest confidence; used for all endpoint shapes, permissions, schemas, and pagination/delta semantics.
- **Official SharePoint Online throttling doc (learn.microsoft.com/sharepoint)** — highest confidence; used for the Rate Limits section (Graph's own throttling-limits page defers to this doc for Files/Lists services).
- **Airbyte connector docs** — medium confidence; used only to cross-check that `Sites.Read.All`/`Sites.ReadWrite.All` are the expected application permissions and that dynamic list/column discovery is the standard integration pattern (consistent with official docs; no conflicts found).

## Research Log

| Source Type | URL | Accessed (UTC) | Confidence | What it confirmed |
|-------------|-----|-----------------|------------|---------------------|
| Official Docs | https://learn.microsoft.com/en-us/graph/api/resources/sharepoint?view=graph-rest-1.0 | 2026-07-23 | High | SharePoint API root resource paths, site addressing by hostname/path/GUID composite ID, `/sites/root`, `/sites?search=`, `/sites/{site-id}/lists`, `/sites/{site-id}/lists/{list-id}/items` |
| Official Docs | https://learn.microsoft.com/en-us/graph/api/resources/list?view=graph-rest-1.0 | 2026-07-23 | High | `list` resource properties, relationships, JSON representation |
| Official Docs | https://learn.microsoft.com/en-us/graph/api/listitem-list?view=graph-rest-1.0&tabs=http | 2026-07-23 | High | `GET /sites/{site-id}/lists/{list-id}/items` HTTP request, permissions table (`Sites.Read.All`/`Sites.ReadWrite.All`), `$expand=fields`, `$filter` semantics, example request/response |
| Official Docs | https://learn.microsoft.com/en-us/graph/api/resources/listitem?view=graph-rest-1.0 | 2026-07-23 | High | `listItem` resource properties, relationships (`fields`, `driveItem`, `versions`), JSON representation, `deleted` facet |
| Official Docs | https://learn.microsoft.com/en-us/graph/api/list-list?view=graph-rest-1.0&tabs=http | 2026-07-23 | High | `GET /sites/{site-id}/lists` HTTP request, permissions table, hidden `system` lists behavior, example response |
| Official Docs | https://learn.microsoft.com/en-us/graph/api/listitem-delta?view=graph-rest-1.0 | 2026-07-23 | High | `items/delta` endpoint, `token` query parameter, `@odata.nextLink`/`@odata.deltaLink` cursor protocol, deleted-item representation, `410 Gone` resync errors |
| Official Docs | https://learn.microsoft.com/en-us/graph/api/site-search?view=graph-rest-1.0 | 2026-07-23 | High | `/sites?search=` endpoint, permissions, `Sites.Selected` unsupported note, example site `id` format |
| Official Docs | https://learn.microsoft.com/en-us/graph/api/resources/columndefinition?view=graph-rest-1.0 | 2026-07-23 | High | Column type facets (`text`, `number`, `boolean`, `dateTime`, `choice`, `lookup`, `personOrGroup`, etc.) used for Field Type Mapping |
| Official Docs | https://learn.microsoft.com/en-us/graph/api/resources/listinfo?view=graph-rest-1.0 | 2026-07-23 | High | `listInfo` properties (`contentTypesEnabled`, `hidden`, `template`) and template value examples |
| Official Docs | https://learn.microsoft.com/en-us/graph/paging | 2026-07-23 | High | General `@odata.nextLink` server-side paging pattern, `$top`/`$skip`/`$skiptoken` client-side paging, retry-token pitfalls |
| Official Docs | https://learn.microsoft.com/en-us/sharepoint/dev/general-development/how-to-avoid-getting-throttled-or-blocked-in-sharepoint-online | 2026-07-23 | High | Resource-unit cost table, per-app-per-tenant rate limits, `Retry-After` / `RateLimit-*` header behavior, recommendation to prefer delta-with-token |
| Official Docs | https://learn.microsoft.com/en-us/graph/throttling-limits | 2026-07-23 | Medium | Confirms Graph's generic throttling page defers to the SharePoint-specific doc above for Files/Lists services |
| Airbyte Docs (via search) | https://docs.airbyte.com/integrations/enterprise-connectors/source-sharepoint-lists-enterprise | 2026-07-23 | Medium | Cross-check: confirms `Sites.Read.All`/`Sites.ReadWrite.All` as required app permissions and dynamic list/column discovery as the standard pattern; no conflicts with official docs |
