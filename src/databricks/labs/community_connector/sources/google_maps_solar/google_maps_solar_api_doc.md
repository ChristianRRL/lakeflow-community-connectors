# **Google Maps Platform Solar API Documentation**

## Source Doc Summary

The **Solar API** (`solar.googleapis.com`, REST version `v1`) is a Google Maps Platform API that exposes solar-potential data for buildings and raw geospatial raster layers derived from aerial/satellite imagery. It is **not** a traditional paginated "list objects" API — it exposes three independent, single-resource **lookup** endpoints, keyed by a lat/lng location (or, for the raster endpoint, by an opaque asset id):

| Connector object | Source endpoint | HTTP method | Returns |
|---|---|---|---|
| `building_insights` | `buildingInsights:findClosest` | GET | Solar potential for the building closest to a lat/lng (roof segments, sunshine quantiles, financial analyses). |
| `data_layers` | `dataLayers:get` | GET | Signed, time-limited URLs pointing to downloadable GeoTIFF raster layers for an area around a lat/lng. |
| `geo_tiff` | `geoTiff:get` | GET | The raw GeoTIFF raster bytes referenced by one of the URLs returned from `data_layers`. |

No Airbyte or Fivetran connector exists for the Solar API (confirmed via web search on both vendors' connector catalogs — see Research Log). There is no Singer tap either. This documentation therefore relies entirely on Google's official REST reference and official guide pages, cross-referenced against the generated Python/Ruby/Elixir client library docs (which mirror the same proto-derived schema) for field-level confirmation.

---

## **Authorization**

- **Chosen method**: **API key** passed as the `key` query parameter on every request. This is the standard Google Maps Platform pattern and is explicitly documented for the Solar API (see `get-api-key` guide and `data-layers` guide example requests).
- **Setup steps**:
  1. Create/select a Google Cloud project and enable billing on it.
  2. Enable the **Solar API** for that project (Google Cloud Console → APIs & Services → Library → "Solar API").
  3. Create an API key (APIs & Services → Credentials → Create Credentials → API key).
  4. Restrict the key to the Solar API (and optionally by IP/HTTP referrer) as a security best practice.
- **Auth placement**: query parameter `key=YOUR_API_KEY` appended to every request URL (including the follow-up `geoTiff:get` requests built from URLs returned by `dataLayers:get`).
- **Other supported method (not used by this connector)**: OAuth 2.0 access token with scope `https://www.googleapis.com/auth/cloud-platform`, sent as `Authorization: Bearer <token>` plus an `X-Goog-User-Project` header for billing attribution. The official REST reference pages list this as the "canonical" auth method (it is a GCP/Cloud Endpoints API), but every hands-on guide/tutorial page (`get-api-key`, `building-insights`, `data-layers`) uses the simpler API-key-as-query-param flow, and that is what this connector will implement. OAuth is noted here only as an alternative; the connector does **not** implement interactive OAuth flows.
- **Billing requirement**: billing must be enabled on the project. Google Maps Platform does **not** bill for requests that return `NOT_FOUND` (404), but such requests still count against the queries-per-minute quota.

Example authenticated requests:

```bash
# building_insights
curl "https://solar.googleapis.com/v1/buildingInsights:findClosest?location.latitude=37.4450&location.longitude=-122.1390&requiredQuality=HIGH&key=YOUR_API_KEY"

# data_layers
curl "https://solar.googleapis.com/v1/dataLayers:get?location.latitude=37.4450&location.longitude=-122.1390&radiusMeters=100&view=FULL_LAYERS&requiredQuality=HIGH&key=YOUR_API_KEY"

# geo_tiff (id/URL comes from a prior data_layers response, e.g. the dsmUrl field)
curl "https://solar.googleapis.com/v1/geoTiff:get?id=fbde33e9cd16d5fd10d19a19dc580bc1-8614f599c5c264553f821cd034d5cf32&key=YOUR_API_KEY" --output dsm.tif
```

- Rate limit: **600 queries per minute**, applying to both `buildingInsights` and `dataLayers` endpoints (documented on the "Solar API Usage and Billing" page). The `geoTiff` endpoint is not separately quota-listed there; it is treated as part of the request flow for `dataLayers` (Google's billing model charges once per successful `buildingInsights`/`dataLayers` call regardless of how many GeoTIFF assets are subsequently downloaded from the URLs in that response), but `geoTiff:get` calls still count against overall project QPS and should be throttled the same as the other two endpoints as a safe default.
- Pricing: pay-as-you-go, billed per successful `buildingInsights`/`dataLayers` call (SKU-based, volume pricing); exact `$`/call rates are on Google's separate pricing pages and are out of scope for this doc. `NOT_FOUND` responses are not billed.

---

## **Object List**

The object list is **static** — the Solar API does not expose a discovery/list-objects endpoint. There are exactly three usable read resources, all single-item lookups (no collection semantics):

| Object Name | Description | Primary Endpoint | Ingestion Type |
|---|---|---|---|
| `building_insights` | Solar potential of the single building nearest to a given lat/lng: roof segments, sunshine quantiles, panel configs, financial analyses. | `GET https://solar.googleapis.com/v1/buildingInsights:findClosest` | `snapshot` |
| `data_layers` | Metadata + signed URLs pointing to downloadable raster layers (DSM, RGB, mask, annual/monthly flux, hourly shade) for an area around a lat/lng. | `GET https://solar.googleapis.com/v1/dataLayers:get` | `snapshot` |
| `geo_tiff` | The actual raster bytes (one GeoTIFF file per URL referenced in a `data_layers` row). | `GET https://solar.googleapis.com/v1/geoTiff:get` | `snapshot` |

Notes on scope/relationship between objects:
- `data_layers` is **layered under** an implicit query (lat/lng/radius/view/quality/pixel size) — it has no independent identity of its own.
- `geo_tiff` is **layered under** `data_layers`: every row it returns corresponds to one of the URL fields (`dsmUrl`, `rgbUrl`, `maskUrl`, `annualFluxUrl`, `monthlyFluxUrl`, or one entry of `hourlyShadeUrls`) produced by a `data_layers` call for the *same* query. `geo_tiff` cannot be read standalone without first obtaining fresh URLs from `data_layers` (see "Known Quirks" below — the URLs/ids expire after 1 hour).
- There is also a `buildingInsights.findClosest`-adjacent lookup-by-resource-name endpoint (`GET /v1/buildingInsights/{name}` conceptually, referred to in Google's docs as fetching by the `name` returned in a prior response), but the connector uses `findClosest` as the sole entry point since building insights are always requested by location in practice.
- All three endpoints require an input location (or, for `geo_tiff`, an input id/URL) supplied by the caller — there is no way to enumerate "all buildings" or "all data layers"; the connector's `location.latitude` / `location.longitude` (and, for the `geo_tiff` table, the upstream `id`) are therefore **required table options**, not discovered automatically.

---

## **Object Schema**

### General notes

- The Solar API is a proto-derived REST API (`google.maps.solar.v1` package); schemas are static and fully documented in Google's REST reference pages. There is no schema-discovery endpoint.
- Nested JSON objects are modeled as **nested structs** in the connector's tabular view, matching the azure_devops-style documentation convention used elsewhere in this repo.
- Common sub-types shared across all three objects:
  - `LatLng` (`google.type.LatLng`): `{ "latitude": number, "longitude": number }`
  - `Date` (`google.type.Date`): `{ "year": integer, "month": integer, "day": integer }`
  - `Money` (`google.type.Money`): `{ "currencyCode": string, "units": int64 (string-encoded), "nanos": integer }`

### `building_insights` object (endpoint: `buildingInsights:findClosest`)

**Source endpoint**:
`GET https://solar.googleapis.com/v1/buildingInsights:findClosest`

**Query parameters**:

| Parameter | Type | Required | Description |
|---|---|---|---|
| `location.latitude` | number (double) | Yes | Latitude of the query point. |
| `location.longitude` | number (double) | Yes | Longitude of the query point. |
| `requiredQuality` | enum `ImageryQuality` | No (default `HIGH`) | Minimum acceptable imagery quality. Values: `IMAGERY_QUALITY_UNSPECIFIED`, `HIGH`, `MEDIUM`, `LOW`, `BASE` (see enum table below). |
| `exactQualityRequired` | boolean | No (default `false`) | If `true`, only imagery of exactly `requiredQuality` is returned; if `false` (default), imagery of `requiredQuality` **or higher** is returned. |
| `experiments[]` | enum array `Experiment` | No | Pre-GA opt-in features. Currently `EXPANDED_COVERAGE` (expands geographic coverage; also unlocks the `BASE` imagery quality tier). |
| `additionalInsights[]` | enum array `AdditionalInsights` | No | Extra optional data to include. Currently `DETECTED_ARRAYS` (adds the `detectedArrays` field showing existing rooftop solar arrays detected in imagery). |

**Key behavior**:
- Returns data for the single building **closest** to the supplied lat/lng — not a list, not necessarily the building *containing* the point.
- No incremental cursor of any kind (imagery is refreshed on Google's own schedule, exposed via `imageryDate`/`imageryProcessedDate`); treated as `snapshot`.
- Returns `NOT_FOUND` (404) if there is no known building near the location or the source system has no coverage there (not billed, but still counts toward QPS quota).

**High-level schema (connector view) — top level**:

| Column Name | Type | Description |
|---|---|---|
| `name` | string | Resource name / stable building identifier, e.g. `buildings/ChIJh0CMPQW7j4ARLrRiVvmg6Vs`. |
| `center` | struct (`LatLng`) | Centroid of the building. |
| `boundingBox` | struct `{ sw: LatLng, ne: LatLng }` | Bounding box of the building footprint. |
| `imageryDate` | struct (`Date`) | Approximate date the source imagery was captured. |
| `imageryProcessedDate` | struct (`Date`) | Date processing on the imagery was finalized. |
| `postalCode` | string | Postal code of the building. |
| `administrativeArea` | string | Administrative area (e.g., US state code). |
| `statisticalArea` | string | Statistical area code (e.g., US Census tract id). |
| `regionCode` | string | ISO region/country code. |
| `imageryQuality` | enum `ImageryQuality` | Quality of imagery used for this result. |
| `solarPotential` | struct `SolarPotential` | Core solar-potential payload (see nested schema). |
| `detectedArrays` | struct `DetectedArrays` or null | Present only if `additionalInsights=DETECTED_ARRAYS` was requested. |

**Nested `solarPotential` (`SolarPotential`) struct**:

| Field | Type | Description |
|---|---|---|
| `maxArrayPanelsCount` | integer | Max number of panels that fit on the roof. |
| `panelCapacityWatts` | number | Wattage assumed per panel for these calcs. |
| `panelHeightMeters` | number | Assumed panel height. |
| `panelWidthMeters` | number | Assumed panel width. |
| `panelLifetimeYears` | integer | Assumed panel lifetime used in financial calcs. |
| `maxArrayAreaMeters2` | number | Max roof area usable for panels. |
| `maxSunshineHoursPerYear` | number | Max annual sunshine hours anywhere on the roof. |
| `carbonOffsetFactorKgPerMwh` | number | Local carbon offset factor. |
| `wholeRoofStats` | struct `SizeAndSunshineStats` | Aggregate stats across the whole roof. |
| `buildingStats` | struct `SizeAndSunshineStats` | Aggregate stats across the whole building footprint. |
| `roofSegmentStats` | array of struct `RoofSegmentSizeAndSunshineStats` | Per-roof-facet stats (one row per planar segment). |
| `solarPanels` | array of struct `SolarPanel` | Modeled individual panel placements, best-to-worst energy order. |
| `solarPanelConfigs` | array of struct `SolarPanelConfig` | Modeled configurations at increasing panel counts. |
| `financialAnalyses` | array of struct `FinancialAnalysis` | Financial projections, one per assumed monthly bill amount. |

**Nested `SizeAndSunshineStats`**:

| Field | Type | Description |
|---|---|---|
| `areaMeters2` | number | Area in square meters. |
| `sunshineQuantiles` | array of number | Sunshine hours/year at each decile (11 values: min, 10th...90th percentile, max). |
| `groundAreaMeters2` | number | Ground (footprint-projected) area in square meters. |

**Nested `RoofSegmentSizeAndSunshineStats`**:

| Field | Type | Description |
|---|---|---|
| `stats` | struct `SizeAndSunshineStats` | Size/sunshine stats for this segment. |
| `center` | struct (`LatLng`) | Segment centroid. |
| `boundingBox` | struct `{ sw: LatLng, ne: LatLng }` | Segment bounding box. |
| `pitchDegrees` | number | Roof pitch angle. |
| `azimuthDegrees` | number | Roof facet compass direction. |
| `planeHeightAtCenterMeters` | number | Height of the roof plane at its center. |

**Nested `SolarPanel`**:

| Field | Type | Description |
|---|---|---|
| `center` | struct (`LatLng`) | Panel center location. |
| `orientation` | enum `SolarPanelOrientation` (`SOLAR_PANEL_ORIENTATION_UNSPECIFIED`, `LANDSCAPE`, `PORTRAIT`) | Panel orientation. |
| `yearlyEnergyDcKwh` | number | Modeled yearly DC energy output for this panel. |
| `segmentIndex` | integer | Index into `roofSegmentStats` this panel sits on. |

**Nested `SolarPanelConfig`**:

| Field | Type | Description |
|---|---|---|
| `panelsCount` | integer | Number of panels in this configuration. |
| `yearlyEnergyDcKwh` | number | Modeled yearly DC output for this configuration. |
| `roofSegmentSummaries` | array of struct `RoofSegmentSummary` | Per-segment breakdown for this configuration. |

**Nested `RoofSegmentSummary`**:

| Field | Type | Description |
|---|---|---|
| `panelsCount` | integer | Panels placed on this segment for this configuration. |
| `yearlyEnergyDcKwh` | number | Yearly DC output from this segment in this configuration. |
| `pitchDegrees` | number | Segment pitch. |
| `azimuthDegrees` | number | Segment azimuth. |
| `segmentIndex` | integer | Index into `roofSegmentStats`. |

**Nested `FinancialAnalysis`**:

| Field | Type | Description |
|---|---|---|
| `monthlyBill` | struct (`Money`) | Assumed monthly electric bill for this analysis. |
| `defaultBill` | boolean | Whether this is the region's default assumed bill. |
| `averageKwhPerMonth` | number | Average monthly consumption implied by the bill. |
| `financialDetails` | struct `FinancialDetails` | Detailed financial breakdown. |
| `leasingSavings` | struct `LeasingSavings` or null | Savings if leasing panels. |
| `cashPurchaseSavings` | struct `CashPurchaseSavings` or null | Savings if buying with cash. |
| `financedPurchaseSavings` | struct `FinancedPurchaseSavings` or null | Savings if buying with a loan. |
| `panelConfigIndex` | integer | Index into `solarPanelConfigs` recommended for this bill level. |

**Nested `FinancialDetails`**:

| Field | Type | Description |
|---|---|---|
| `initialAcKwhPerYear` | number | Estimated first-year AC output. |
| `remainingLifetimeUtilityBill` | struct (`Money`) | Remaining lifetime utility cost after installing solar. |
| `federalIncentive` | struct (`Money`) | Federal tax incentive amount. |
| `stateIncentive` | struct (`Money`) or null | State incentive amount. |
| `utilityIncentive` | struct (`Money`) or null | Utility incentive amount. |
| `lifetimeSrecTotal` | struct (`Money`) or null | Lifetime SREC value. |
| `costOfElectricityWithoutSolar` | struct (`Money`) | Baseline lifetime electricity cost without solar. |
| `netMeteringAllowed` | boolean | Whether net metering applies in this region. |
| `solarPercentage` | number | % of consumption covered by solar. |
| `percentageExportedToGrid` | number | % of solar generation exported to the grid. |

**Nested `LeasingSavings`**: `{ leasesAllowed: boolean, leasesSupported: boolean, annualLeasingCost: Money, savings: SavingsOverTime }`

**Nested `CashPurchaseSavings`**: `{ outOfPocketCost: Money, upfrontCost: Money, rebateValue: Money, paybackYears: number, savings: SavingsOverTime }`

**Nested `FinancedPurchaseSavings`**: same shape as `CashPurchaseSavings` plus `loanInterestRate: number`.

**Nested `SavingsOverTime`**: `{ savingsYear1: Money, savingsYear20: Money, presentValueOfSavingsYear20: Money, savingsLifetime: Money, presentValueOfSavingsLifetime: Money, financiallyViable: boolean }`

**Nested `DetectedArrays`** (only present if `additionalInsights=DETECTED_ARRAYS`):

| Field | Type | Description |
|---|---|---|
| `detectionStatus` | enum `DetectionStatus` (`DETECTION_STATUS_UNSPECIFIED`, `DETECTION_STATUS_DATA_UNAVAILABLE`, `DETECTION_STATUS_ARRAYS_DETECTED`, `DETECTION_STATUS_NO_ARRAYS_DETECTED`) | Whether existing solar arrays were detected. |
| `latestCaptureDate` | struct (`Date`) | Date of the imagery used for array detection. |

**`ImageryQuality` enum** (shared by all 3 objects):

| Value | Meaning |
|---|---|
| `IMAGERY_QUALITY_UNSPECIFIED` | No quality known (not a valid request input). |
| `HIGH` | Low-altitude aerial imagery, ~0.1 m/pixel DSM. |
| `MEDIUM` | High-altitude aerial imagery, ~0.25 m/pixel DSM. |
| `LOW` | Satellite imagery, ~0.5 m/pixel or worse DSM. |
| `BASE` | Enhanced satellite imagery, ~0.25 m/pixel DSM; only returned/requestable when `experiments=EXPANDED_COVERAGE`. |

**Example request**:

```bash
curl "https://solar.googleapis.com/v1/buildingInsights:findClosest?location.latitude=37.4450&location.longitude=-122.1390&requiredQuality=HIGH&key=YOUR_API_KEY"
```

**Example response (truncated)**:

```json
{
  "name": "buildings/ChIJh0CMPQW7j4ARLrRiVvmg6Vs",
  "center": { "latitude": 37.4449439, "longitude": -122.13914659999998 },
  "boundingBox": {
    "sw": { "latitude": 37.4447321, "longitude": -122.1394224 },
    "ne": { "latitude": 37.4451909, "longitude": -122.1392928 }
  },
  "imageryDate": { "year": 2022, "month": 8, "day": 14 },
  "imageryProcessedDate": { "year": 2023, "month": 8, "day": 4 },
  "postalCode": "94303",
  "administrativeArea": "CA",
  "statisticalArea": "06085511100",
  "regionCode": "US",
  "imageryQuality": "HIGH",
  "solarPotential": {
    "maxArrayPanelsCount": 1163,
    "panelCapacityWatts": 400,
    "maxArrayAreaMeters2": 1903.5983,
    "maxSunshineHoursPerYear": 1802,
    "wholeRoofStats": {
      "areaMeters2": 2399.3958,
      "sunshineQuantiles": [351, 1396, 1474, 1527, 1555, 1596, 1621, 1640, 1664, 1759, 1864],
      "groundAreaMeters2": 2279.71
    },
    "roofSegmentStats": [
      {
        "pitchDegrees": 11.350553,
        "azimuthDegrees": 269.6291,
        "stats": { "areaMeters2": 452.00052, "sunshineQuantiles": [408, 1475, 1546], "groundAreaMeters2": 443.16 },
        "center": { "latitude": 37.4449728, "longitude": -122.1393637 },
        "planeHeightAtCenterMeters": 10.7835045
      }
    ],
    "financialAnalyses": [
      {
        "monthlyBill": { "currencyCode": "USD", "units": "35" },
        "panelConfigIndex": 0,
        "financialDetails": {
          "initialAcKwhPerYear": 1546.8864,
          "netMeteringAllowed": true,
          "solarPercentage": 86.7469
        }
      }
    ]
  }
}
```

> The fields listed above define the **complete connector schema** for `building_insights`. Any new fields added by Google in future API versions must be added here to keep this documentation accurate.

---

### `data_layers` object (endpoint: `dataLayers:get`)

**Source endpoint**:
`GET https://solar.googleapis.com/v1/dataLayers:get`

**Query parameters**:

| Parameter | Type | Required | Description |
|---|---|---|---|
| `location.latitude` | number (double) | Yes | Latitude of the center of the requested region. |
| `location.longitude` | number (double) | Yes | Longitude of the center of the requested region. |
| `radiusMeters` | number | Yes (in practice) | Radius around the center point to fetch. Up to 100 m is always allowed; beyond that, `radiusMeters <= pixelSizeMeters * 1000`; requests over 175 m radius cannot include monthly flux or hourly shade layers. |
| `view` | enum `DataLayerView` | No (default `FULL_LAYERS`) | Which subset of layers to compute/return. Values: `DATA_LAYER_VIEW_UNSPECIFIED` (=`FULL_LAYERS`), `DSM_LAYER` (DSM only), `IMAGERY_LAYERS` (DSM+RGB+mask), `IMAGERY_AND_ANNUAL_FLUX_LAYERS` (+ annual flux), `IMAGERY_AND_ALL_FLUX_LAYERS` (+ monthly flux), `FULL_LAYERS` (everything, including hourly shade). |
| `requiredQuality` | enum `ImageryQuality` | No (default `HIGH`) | Minimum acceptable imagery quality (same enum as `building_insights`). |
| `pixelSizeMeters` | number | No (default `0.1`) | Minimum resolution in meters/pixel. Supported: `0.1`, `0.25`, `0.5`, `1.0`. |
| `exactQualityRequired` | boolean | No (default `false`) | Same semantics as in `building_insights`. |
| `experiments[]` | enum array `Experiment` | No | Currently `EXPANDED_COVERAGE`. |

**Key behavior**:
- Returns **metadata plus signed URLs**, not the raster data itself.
- Each URL returned already points at `GET /v1/geoTiff:get?id=<opaque_id>` — the connector only needs to append `&key=YOUR_API_KEY` to fetch the corresponding `geo_tiff` row.
- **Regardless of resolution/quality requested, output rasters have fixed native resolutions**: DSM always 0.1 m/pixel, monthly flux always 0.5 m/pixel, hourly shade always 1 m/pixel (see `geo_tiff` section).
- No incremental cursor; treated as `snapshot`.
- **URLs (and the ids embedded in them) expire ~1 hour after the `dataLayers:get` call that produced them** — see "Known Quirks."

**High-level schema (connector view)**:

| Column Name | Type | Description |
|---|---|---|
| `imageryDate` | struct (`Date`) | Approximate date source imagery was captured. |
| `imageryProcessedDate` | struct (`Date`) | Date processing was finalized. |
| `dsmUrl` | string | Signed URL to the Digital Surface Model GeoTIFF (elevation, meters above sea level; `-9999` = invalid). |
| `rgbUrl` | string | Signed URL to the RGB aerial/satellite image GeoTIFF. |
| `maskUrl` | string | Signed URL to the binary rooftop building-mask GeoTIFF. |
| `annualFluxUrl` | string | Signed URL to the annual sunlight flux GeoTIFF (kWh/kW/year, unmasked). |
| `monthlyFluxUrl` | string or null | Signed URL to the 12-band monthly flux GeoTIFF (present unless `view=DSM_LAYER`/`IMAGERY_LAYERS`, or `radiusMeters > 175`). |
| `hourlyShadeUrls` | array of string | 12 signed URLs (one per month, Jan–Dec), each a 24-band hourly-shade GeoTIFF (present only for `view=FULL_LAYERS` and `radiusMeters <= 175`). |
| `imageryQuality` | enum `ImageryQuality` | Quality of imagery used. |
| `query_latitude` | number (connector-derived) | The `location.latitude` used for this request (not returned by the API; captured by the connector for joining to `geo_tiff` / `building_insights`). |
| `query_longitude` | number (connector-derived) | The `location.longitude` used for this request. |
| `query_radius_meters` | number (connector-derived) | The `radiusMeters` used for this request. |

**Example request**:

```bash
curl "https://solar.googleapis.com/v1/dataLayers:get?location.latitude=37.4450&location.longitude=-122.1390&radiusMeters=100&view=FULL_LAYERS&requiredQuality=HIGH&exactQualityRequired=false&pixelSizeMeters=0.5&key=YOUR_API_KEY"
```

**Example response**:

```json
{
  "imageryDate": { "year": 2022, "month": 4, "day": 6 },
  "imageryProcessedDate": { "year": 2023, "month": 8, "day": 4 },
  "dsmUrl": "https://solar.googleapis.com/v1/geoTiff:get?id=fbde33e9cd16d5fd10d19a19dc580bc1-dsm...",
  "rgbUrl": "https://solar.googleapis.com/v1/geoTiff:get?id=fbde33e9cd16d5fd10d19a19dc580bc1-rgb...",
  "maskUrl": "https://solar.googleapis.com/v1/geoTiff:get?id=fbde33e9cd16d5fd10d19a19dc580bc1-mask...",
  "annualFluxUrl": "https://solar.googleapis.com/v1/geoTiff:get?id=fbde33e9cd16d5fd10d19a19dc580bc1-flux...",
  "monthlyFluxUrl": "https://solar.googleapis.com/v1/geoTiff:get?id=fbde33e9cd16d5fd10d19a19dc580bc1-monthly...",
  "hourlyShadeUrls": [
    "https://solar.googleapis.com/v1/geoTiff:get?id=fbde33e9cd16d5fd10d19a19dc580bc1-shade-01...",
    "https://solar.googleapis.com/v1/geoTiff:get?id=fbde33e9cd16d5fd10d19a19dc580bc1-shade-02..."
  ],
  "imageryQuality": "HIGH"
}
```

> The fields listed above define the **complete connector schema** for `data_layers`.

---

### `geo_tiff` object (endpoint: `geoTiff:get`)

**Source endpoint**:
`GET https://solar.googleapis.com/v1/geoTiff:get`

**Query parameters**:

| Parameter | Type | Required | Description |
|---|---|---|---|
| `id` | string | Yes | Opaque asset id. In practice, callers do not construct this manually — they take one of the full URLs returned in a `data_layers` row (`dsmUrl`, `rgbUrl`, `maskUrl`, `annualFluxUrl`, `monthlyFluxUrl`, or an entry of `hourlyShadeUrls`), which already has `id=...` populated, and just append `&key=YOUR_API_KEY`. |

Request body must be empty.

**Key behavior / CRITICAL implementation note**:
- The proto/discovery-doc schema for this method's response is `google.api.HttpBody`, conceptually `{ "contentType": string, "data": bytes, "extensions": [...] }`. This is what you'll see described in generated client-library docs (Python/Ruby/Elixir wrappers deserialize into this shape, base64-decoding `data` for you).
- **However, when called directly as a plain REST/HTTP request (no Google client library), the raw HTTP response body IS the GeoTIFF file itself** — `Content-Type: image/tiff` (or similar), with the TIFF bytes as the literal response payload. It is **not** JSON-wrapped in `{contentType, data}` at the wire level for a direct `curl`/`requests` call; that structure only shows up if you go through a JSON-transcoding gRPC/discovery client. The connector must be implemented against the plain-REST behavior: read `response.content` (raw bytes) and `response.headers["Content-Type"]`.
- No pagination, no incremental cursor; single binary blob per request. Treated as `snapshot`.
- **GeoTIFF URLs/ids expire ~1 hour after the originating `dataLayers:get` call.** Downloaded files themselves may be cached/stored by the caller for **up to 30 days** per Google's stated policy, after which they should be treated as stale and re-fetched via a new `dataLayers:get` call.

**Raster format per layer type** (relevant for downstream parsing, not part of the JSON schema itself — these are properties of the binary GeoTIFF content, readable with a library such as `rasterio`/GDAL):

| Layer (source URL field) | Bit depth | Resolution | Bands | Notes |
|---|---|---|---|---|
| DSM (`dsmUrl`) | 32-bit float | 0.1 m/pixel (fixed) | 1 | Elevation in meters; `-9999` = invalid/no data. |
| RGB (`rgbUrl`) | 8-bit | 0.1 m/pixel (or 0.25 m if requested) | 3 (R, G, B) | Aerial/satellite photo. |
| Mask (`maskUrl`) | 1-bit | 0.1 m/pixel | 1 | Binary building/rooftop mask. |
| Annual flux (`annualFluxUrl`) | 32-bit float | 0.1 m/pixel | 1 | kWh/kW/year, unmasked. |
| Monthly flux (`monthlyFluxUrl`) | 32-bit float | 0.5 m/pixel (fixed) | 12 (Jan–Dec) | One band per month. |
| Hourly shade (`hourlyShadeUrls[i]`) | 32-bit int | 1 m/pixel (fixed) | 24 (hour 0–23) | Per pixel/band, each bit of the 32-bit int encodes sun visibility for one day of that month (up to 31 days); one file per month, hence 12 URLs. |

**High-level schema (connector view)**:

| Column Name | Type | Description |
|---|---|---|
| `asset_id` | string | The `id` query-param value extracted from the source URL. Connector-derived from the URL, since the API itself does not echo the id back in a JSON body. |
| `layer_type` | string (connector-derived) | Which `data_layers` field this asset came from: one of `dsm`, `rgb`, `mask`, `annual_flux`, `monthly_flux`, `hourly_shade`. |
| `month_index` | integer or null (connector-derived) | For `layer_type = hourly_shade` only: 1–12, indicating which position in `hourlyShadeUrls` this row corresponds to. Null otherwise. |
| `content_type` | string | HTTP `Content-Type` header from the response (e.g., `image/tiff`). |
| `data` | binary (bytes) | The raw GeoTIFF file bytes. **Recommended representation**: store as a `binary`/`bytes` column (Spark `BinaryType`) rather than base64-encoding into a string column, to avoid ~33% size bloat and unnecessary encode/decode steps. |
| `source_url` | string (connector-derived) | The full signed URL (without the `key` param) this asset was fetched from, for traceability/debugging. |
| `query_latitude` | number (connector-derived) | Latitude of the originating `data_layers` query (propagated through for joinability). |
| `query_longitude` | number (connector-derived) | Longitude of the originating `data_layers` query. |
| `fetched_at` | timestamp (connector-derived) | When the connector fetched this asset — important given the 1-hour URL expiry / 30-day cache-validity window. |

**Example request** (URL taken verbatim from a prior `data_layers` response, with `key` appended):

```bash
curl "https://solar.googleapis.com/v1/geoTiff:get?id=fbde33e9cd16d5fd10d19a19dc580bc1-8614f599c5c264553f821cd034d5cf32&key=YOUR_API_KEY" --output dsm.tif
```

**Example response**: raw binary GeoTIFF content (not human-readable JSON); HTTP header `Content-Type: image/tiff`.

> The fields listed above define the **complete connector schema** for `geo_tiff`. Because the API itself returns no field names (just bytes + content-type), most columns here are connector-derived from the request context — this is called out explicitly so future maintainers don't mistake them for API-native fields.

---

## **Get Object Primary Keys**

There is no API for retrieving primary keys — schemas and keys are static and determined by this documentation (and by the connector implementation, since the raw API returns no natural row-identity fields for two of the three objects).

| Object | Primary Key | Notes |
|---|---|---|
| `building_insights` | `name` | Stable Google-assigned building resource id (e.g. `buildings/ChIJ...`). Note: multiple nearby query locations can resolve to the *same* `name` (findClosest is location-driven, not id-driven), so `name` alone is a valid dedup key even though the table is queried by lat/lng. |
| `data_layers` | Composite: (`query_latitude`, `query_longitude`, `query_radius_meters`) | The API response itself contains no unique identifier; the input query parameters are the only stable identity for a given row. Same query params + same imagery generation should yield identical results (until Google refreshes imagery for that area). |
| `geo_tiff` | `asset_id` | Extracted from the `id` query parameter of the source URL. Note this id is **only valid for ~1 hour** from when the parent `data_layers` call was made — it is not a durable, indefinitely-reusable key across pipeline runs; each pipeline run effectively mints new `asset_id` values. |

---

## **Object's ingestion type**

All three objects are `snapshot`:

| Object | Ingestion Type | Rationale |
|---|---|---|
| `building_insights` | `snapshot` | No cursor field; results only change when Google reprocesses imagery for an area (irregular, undocumented cadence). Re-fetch on each run for a given location. |
| `data_layers` | `snapshot` | Same reasoning; also, URLs it returns are single-use/short-lived so caching prior results across runs isn't meaningful anyway. |
| `geo_tiff` | `snapshot` | Binary blob keyed by an ephemeral id; there is no concept of "new records since last run" — every pipeline run must go through `data_layers` again to mint fresh ids/URLs, then re-download. |

None of the three support `cdc`, `cdc_with_deletes`, or `append` semantics — there is no modification timestamp, revision counter, or delete feed exposed anywhere in the API.

---

## **Read API for Data Retrieval**

- All three endpoints are simple **GET** requests; there is no POST/list variant.
- **No pagination of any kind** on any of the three endpoints — each call returns exactly one resource (one building, one data-layers bundle, or one file). This is expected for single-resource lookup APIs and was confirmed by inspecting the full REST reference (`findClosest`, `dataLayers.get`, `geoTiff.get`) — none of them document a page token, `pageSize`, or `nextPageToken` field.
- **No incremental read / cursor support** — none of the three endpoints accept an `updatedSince`/`modifiedAfter`-style filter, and none of the response schemas expose a monotonically increasing revision or timestamp suitable as a cursor. `imageryDate`/`imageryProcessedDate` describe the *source imagery*, not a record-modification time, and cannot be used to filter server-side (they are output-only, not accepted as request filters).
- **No delete feed** — deleted/stale records are not signaled by the API at all; the connector's snapshot approach (re-fetch on each run) is the only way to detect changes.
- Required table options (connector-level parameters the user must supply per query row/table):
  - `building_insights`: `location.latitude`, `location.longitude` (required); `requiredQuality`, `exactQualityRequired`, `experiments`, `additionalInsights` (optional).
  - `data_layers`: `location.latitude`, `location.longitude`, `radiusMeters` (required); `view`, `requiredQuality`, `pixelSizeMeters`, `exactQualityRequired`, `experiments` (optional).
  - `geo_tiff`: a source URL/id (required) — in practice supplied by chaining from a `data_layers` read within the same pipeline run, not typed in ad hoc by the user, due to the 1-hour expiry.
- **Rate limit**: 600 queries/minute across `buildingInsights` + `dataLayers` (shared quota); apply client-side throttling/backoff for `geoTiff` calls at the same rate as a safe default since it is not separately documented. Exceeding the quota returns HTTP 429; standard exponential backoff should be used.
- **Comparison of read options**: there is only one way to read each object (no REST vs. gRPC choice relevant to a connector, no alternate list endpoint) — the REST GET endpoints documented here are the only supported read path.

Example end-to-end flow (connector logic, not raw API capability):
1. Call `dataLayers:get` for a `(lat, lng, radius)` row → get back a `data_layers` row containing 1–15 signed URLs (depending on `view`).
2. For each URL field present, call `geoTiff:get` (i.e., `GET <url>&key=API_KEY`) **promptly, within the 1-hour URL validity window** → emit one `geo_tiff` row per URL.
3. Independently, call `buildingInsights:findClosest` for the same `(lat, lng)` → emit one `building_insights` row.

---

## **Field Type Mapping**

| API Type | Spark/Connector Type | Notes |
|---|---|---|
| `string` | `string` | Includes resource names, enum string values, URLs. |
| `number` (double, e.g. lat/lng, areas, energy) | `double` | JSON numbers without an explicit int64 encoding. |
| `integer` (e.g. counts, `panelConfigIndex`) | `integer` (or `long` where values could be large, e.g. `Money.units`) | `Money.units` is transmitted as a **string-encoded int64** per Google's standard `Money` type — must be cast, not read as JSON number. |
| `boolean` | `boolean` | e.g. `netMeteringAllowed`, `exactQualityRequired`. |
| `google.type.LatLng` | `struct<latitude: double, longitude: double>` | Shared across all objects. |
| `google.type.Date` | `struct<year: int, month: int, day: int>` | Not a true `date` type at the wire level — day/month can legally be 0 in the general proto spec, though Solar API always populates full dates in practice. Map to Spark `struct`, not `DateType`, to avoid silent coercion errors if a partial date is ever returned. |
| `google.type.Money` | `struct<currencyCode: string, units: long, nanos: int>` | Combine `units` + `nanos/1e9` for a decimal amount if a flattened numeric column is desired downstream. |
| enum (`ImageryQuality`, `DataLayerView`, `Experiment`, `AdditionalInsights`, `SolarPanelOrientation`, `DetectionStatus`) | `string` | Preserve the enum's string constant (e.g., `"HIGH"`) rather than mapping to an integer; Google's REST JSON representation always uses the string form. |
| array of scalar/struct | `array<...>` | e.g. `sunshineQuantiles: array<double>`, `roofSegmentStats: array<struct<...>>`. |
| raw binary (GeoTIFF payload) | `binary` | Store as Spark `BinaryType`, not base64 string — see `geo_tiff` schema notes above. |

Special field behaviors:
- No fields are auto-incrementing/server-generated identifiers except the connector-derived `asset_id` (parsed from URLs) and `name` (a stable Google Place-like id for buildings).
- `solarPanelConfigs` is naturally ordered by increasing `panelsCount`; `financialAnalyses` is ordered to match typical monthly-bill brackets, with one entry flagged `defaultBill: true`.
- Optional/nullable fields: `detectedArrays` (only with `additionalInsights=DETECTED_ARRAYS`), `monthlyFluxUrl`/`hourlyShadeUrls` (only for wider `view` settings and small enough `radiusMeters`), `leasingSavings`/`stateIncentive`/`utilityIncentive`/`lifetimeSrecTotal` (region-dependent — not all financial incentive programs exist everywhere).

---

## Known Quirks / Implementation Gotchas

1. **`geoTiff:get` returns raw binary, not JSON, when called via plain REST.** The `google.api.HttpBody` wrapper shape (`{contentType, data, extensions}`) shown in the proto/reference docs and generated client libraries is a client-library abstraction; a direct HTTP GET to `geoTiff:get` returns the literal file bytes as the HTTP response body with the appropriate binary `Content-Type` header. The connector's HTTP client must be configured to read raw bytes (`response.content`), not attempt `response.json()`.
2. **GeoTIFF URLs and their embedded `id` values expire ~1 hour after the originating `dataLayers:get` call.** The `geo_tiff` table cannot be read independently/lazily — it must be read promptly after (or as a chained step within the same run as) a `data_layers` read for the same location, or the ids will 404/expire. Downloaded GeoTIFF *files* may be cached by the pipeline for up to 30 days, but the *source URL* cannot be re-used after ~1 hour to re-download.
3. **No pagination anywhere.** All three endpoints are single-resource lookups; do not implement page-token handling — it doesn't exist for this API.
4. **No incremental/CDC support.** There is no `updated_at`/revision field usable as a read cursor on any object; every read is effectively a fresh point-in-time snapshot for the given input location.
5. **`findClosest` semantics**: `buildingInsights:findClosest` returns the nearest known building to the query point, which may not be the building actually located at that point (e.g., if querying a point in a parking lot, it may return an adjacent building). This is expected API behavior, not a bug — document it for end users of the connector.
6. **Radius/pixel-size/view interactions on `dataLayers:get`** constrain which fields are populated: `monthlyFluxUrl` and `hourlyShadeUrls` are omitted when `radiusMeters > 175`, and are omitted entirely for narrower `view` settings (`DSM_LAYER`, `IMAGERY_LAYERS`, `IMAGERY_AND_ANNUAL_FLUX_LAYERS`). Document these as "optional/nullable," not "always present."
7. **`ImageryQuality=BASE`** is a fourth quality tier (beyond `HIGH`/`MEDIUM`/`LOW`) that only appears/can be requested when `experiments=EXPANDED_COVERAGE` is set — some public documentation snapshots list only 3 named tiers (`HIGH`/`MEDIUM`/`LOW`); `BASE` was confirmed present in the current generated Python client type stubs (`google-maps-solar` package) and is documented as tied to the `EXPANDED_COVERAGE` experiment.
8. **Billing**: `NOT_FOUND` (404) responses from `buildingInsights`/`dataLayers` are free but still count against the 600 QPM quota — do not assume "no charge" implies "no rate-limit impact."
9. **No Airbyte/Fivetran/Singer precedent exists** for this API (verified by web search across both vendors' connector catalogs — see Research Log); all auth/pagination/schema conclusions here are derived solely from Google's official docs and official generated client library docs, cross-referenced against each other.

---

## Research Log

| Source Type | URL | Accessed (UTC) | Confidence | What it confirmed |
|---|---|---|---|---|
| Official Docs | https://developers.google.com/maps/documentation/solar/overview | 2026-07-25 | High | Three endpoints exist (`buildingInsights`, `dataLayers`, `geoTiff`); high-level purpose. |
| Official Docs | https://developers.google.com/maps/documentation/solar/reference/rest/v1/buildingInsights/findClosest | 2026-07-25 | High | `findClosest` method, query params, full `BuildingInsights`/`SolarPotential` response schema, OAuth scope. |
| Official Docs | https://developers.google.com/maps/documentation/solar/reference/rest/v1/dataLayers/get | 2026-07-25 | High | `dataLayers.get` method, query params (`location`, `radiusMeters`, `view`, `requiredQuality`, `pixelSizeMeters`, `exactQualityRequired`, `experiments`). |
| Official Docs | https://developers.google.com/maps/documentation/solar/reference/rest/v1/dataLayers | 2026-07-25 | High | Full `DataLayers` response schema (`dsmUrl`, `rgbUrl`, `maskUrl`, `annualFluxUrl`, `monthlyFluxUrl`, `hourlyShadeUrls`, `imageryQuality`, dates). |
| Official Docs | https://developers.google.com/maps/documentation/solar/reference/rest/v1/geoTiff/get | 2026-07-25 | High | `geoTiff.get` method, `id` param, `HttpBody` response representation, OAuth scope. |
| Official Docs | https://developers.google.com/maps/documentation/solar/reference/rest/v1/ImageryQuality | 2026-07-25 | High | `ImageryQuality` enum values `IMAGERY_QUALITY_UNSPECIFIED`/`HIGH`/`MEDIUM`/`LOW` and descriptions. |
| Official Docs | https://developers.google.com/maps/documentation/solar/get-api-key | 2026-07-25 | High | API key setup steps; API-key-as-query-param auth pattern. |
| Official Docs | https://developers.google.com/maps/documentation/solar/building-insights | 2026-07-25 | High | Full worked example request/response for `buildingInsights:findClosest`. |
| Official Docs | https://developers.google.com/maps/documentation/solar/data-layers | 2026-07-25 | High | Full worked example request/response for `dataLayers:get`; confirms `geoTiff:get` follow-up pattern and 1-hour URL expiry. |
| Official Docs | https://developers.google.com/maps/documentation/solar/geotiff | 2026-07-25 | High | Per-layer raster band structure, bit depth, fixed resolutions, 30-day cache-validity note, 1-hour URL expiry. |
| Official Docs | https://developers.google.com/maps/documentation/solar/usage-and-billing | 2026-07-25 | High | 600 QPM shared quota for `buildingInsights`/`dataLayers`; billing SKU tiers; `NOT_FOUND` not billed. |
| Generated client docs | https://googleapis.dev/python/google-maps-solar/latest/solar_v1/types_.html | 2026-07-25 | Medium-High | Confirmed full `ImageryQuality` enum including `BASE` (tied to `EXPANDED_COVERAGE`); `DataLayerView` and `Experiment` enum values. |
| Web search (vendor catalog check) | Airbyte connector catalog / Fivetran connector catalog (general search, no dedicated Solar API connector found) | 2026-07-25 | High (absence confirmed) | No Airbyte, Fivetran, or Singer tap exists for the Google Solar API — this doc is derived solely from official Google sources. |

**Conflict resolution notes**:
- One secondary web-search summary suggested `ImageryQuality` might have a `LOW` **or** `BASE` value but not both; the official REST reference page and the generated Python client type stubs were prioritized and both list **four** values (`HIGH`, `MEDIUM`, `LOW`, `BASE`), with `BASE` gated behind the `EXPANDED_COVERAGE` experiment. This is called out explicitly in "Known Quirks" item 7 in case Google's docs are further updated.
- OAuth 2.0 (`cloud-platform` scope) is what the raw REST reference pages list as "Authorization" for each method (standard for Cloud Endpoints-fronted APIs), but every hands-on Google guide/tutorial page uses API-key-as-query-param. Per the skill's "single auth method" rule, API key was chosen as the primary documented method, with OAuth noted as an alternative only.
