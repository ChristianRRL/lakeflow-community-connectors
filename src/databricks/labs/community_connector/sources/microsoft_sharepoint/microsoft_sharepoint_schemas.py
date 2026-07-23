"""Schemas, metadata, and constants for the Microsoft SharePoint connector.

Schemas are derived from the Microsoft Graph ``list`` and ``listItem``
resource types (see ``microsoft_sharepoint_api_doc.md``).  Nested Graph
complex types (``identitySet``, ``listInfo``, ``itemReference``,
``sharepointIds``, ``contentTypeInfo``, ``deleted``) are modelled as nested
structs rather than flattened.  The dynamic ``fields`` facet on ``listItem``
is inherently per-list, so it is stored as a ``VariantType`` (JSON) column.
"""

from pyspark.sql.types import (
    BooleanType,
    StringType,
    StructField,
    StructType,
    TimestampType,
    VariantType,
)

# ---------------------------------------------------------------------------
# Nested struct schemas
# ---------------------------------------------------------------------------

# identitySet: each actor sub-struct is {id, displayName}.
_IDENTITY_SCHEMA = StructType(
    [
        StructField("id", StringType(), True),
        StructField("displayName", StringType(), True),
    ]
)

IDENTITY_SET_SCHEMA = StructType(
    [
        StructField("user", _IDENTITY_SCHEMA, True),
        StructField("application", _IDENTITY_SCHEMA, True),
        StructField("device", _IDENTITY_SCHEMA, True),
    ]
)
"""identitySet used for createdBy / lastModifiedBy."""

# listInfo: template and configuration details for a list.
LIST_INFO_SCHEMA = StructType(
    [
        StructField("contentTypesEnabled", BooleanType(), True),
        StructField("hidden", BooleanType(), True),
        StructField("template", StringType(), True),
    ]
)

# itemReference: parent site/list information.  Modelled with the fields Graph
# commonly populates; unknown extras are dropped by the schema projection.
ITEM_REFERENCE_SCHEMA = StructType(
    [
        StructField("id", StringType(), True),
        StructField("siteId", StringType(), True),
        StructField("driveId", StringType(), True),
        StructField("driveType", StringType(), True),
        StructField("path", StringType(), True),
    ]
)

# sharepointIds on the list resource.
LIST_SHAREPOINT_IDS_SCHEMA = StructType(
    [
        StructField("listId", StringType(), True),
        StructField("siteId", StringType(), True),
        StructField("siteUrl", StringType(), True),
        StructField("tenantId", StringType(), True),
        StructField("webId", StringType(), True),
    ]
)

# sharepointIds on the listItem resource (adds list-item-specific fields).
ITEM_SHAREPOINT_IDS_SCHEMA = StructType(
    [
        StructField("listId", StringType(), True),
        StructField("listItemId", StringType(), True),
        StructField("listItemUniqueId", StringType(), True),
        StructField("siteId", StringType(), True),
        StructField("siteUrl", StringType(), True),
        StructField("tenantId", StringType(), True),
        StructField("webId", StringType(), True),
    ]
)

# contentTypeInfo: {id, name}.
CONTENT_TYPE_SCHEMA = StructType(
    [
        StructField("id", StringType(), True),
        StructField("name", StringType(), True),
    ]
)

# deleted facet, only present on delta responses for removed items.
DELETED_SCHEMA = StructType(
    [
        StructField("state", StringType(), True),
    ]
)


# ---------------------------------------------------------------------------
# Table schemas
# ---------------------------------------------------------------------------

LISTS_SCHEMA = StructType(
    [
        StructField("id", StringType(), False),
        StructField("name", StringType(), True),
        StructField("displayName", StringType(), True),
        StructField("description", StringType(), True),
        StructField("webUrl", StringType(), True),
        StructField("createdDateTime", TimestampType(), True),
        StructField("lastModifiedDateTime", TimestampType(), True),
        StructField("createdBy", IDENTITY_SET_SCHEMA, True),
        StructField("lastModifiedBy", IDENTITY_SET_SCHEMA, True),
        StructField("eTag", StringType(), True),
        StructField("list", LIST_INFO_SCHEMA, True),
        StructField("parentReference", ITEM_REFERENCE_SCHEMA, True),
        StructField("sharepointIds", LIST_SHAREPOINT_IDS_SCHEMA, True),
        StructField("system", BooleanType(), True),
        # Connector-derived lineage column: the site the list belongs to.
        StructField("site_id", StringType(), True),
    ]
)
"""Schema for the ``lists`` table."""

LIST_ITEMS_SCHEMA = StructType(
    [
        StructField("id", StringType(), False),
        StructField("contentType", CONTENT_TYPE_SCHEMA, True),
        # Dynamic per-list column values — stored as VARIANT (JSON).
        StructField("fields", VariantType(), True),
        StructField("createdBy", IDENTITY_SET_SCHEMA, True),
        StructField("createdDateTime", TimestampType(), True),
        StructField("lastModifiedBy", IDENTITY_SET_SCHEMA, True),
        StructField("lastModifiedDateTime", TimestampType(), True),
        StructField("eTag", StringType(), True),
        StructField("webUrl", StringType(), True),
        StructField("description", StringType(), True),
        StructField("name", StringType(), True),
        StructField("parentReference", ITEM_REFERENCE_SCHEMA, True),
        StructField("sharepointIds", ITEM_SHAREPOINT_IDS_SCHEMA, True),
        StructField("deleted", DELETED_SCHEMA, True),
        # Connector-derived columns forming the durable composite key.
        StructField("list_id", StringType(), False),
        StructField("site_id", StringType(), True),
    ]
)
"""Schema for the ``list_items`` table."""


TABLE_SCHEMAS: dict[str, StructType] = {
    "lists": LISTS_SCHEMA,
    "list_items": LIST_ITEMS_SCHEMA,
}
"""Mapping of table names to their StructType schemas."""


# ---------------------------------------------------------------------------
# Table metadata
# ---------------------------------------------------------------------------

TABLE_METADATA: dict[str, dict] = {
    "lists": {
        "primary_keys": ["id"],
        "ingestion_type": "snapshot",
    },
    "list_items": {
        # ``id`` is only unique within a list, so the durable key is composite.
        "primary_keys": ["list_id", "id"],
        "cursor_field": "lastModifiedDateTime",
        "ingestion_type": "cdc_with_deletes",
    },
}
"""Metadata for each table: primary keys, cursor field, ingestion type."""


SUPPORTED_TABLES: list[str] = list(TABLE_SCHEMAS.keys())
"""All table names supported by the Microsoft SharePoint connector."""


# ---------------------------------------------------------------------------
# HTTP / retry constants
# ---------------------------------------------------------------------------

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
LOGIN_BASE_URL = "https://login.microsoftonline.com"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"

# Fields on the list resource that must be $select-ed to surface the normally
# hidden ``system`` facet.  Graph hides system lists unless system is selected.
LIST_SELECT_WITH_SYSTEM = (
    "id,name,displayName,description,webUrl,createdDateTime,"
    "lastModifiedDateTime,createdBy,lastModifiedBy,eTag,list,"
    "parentReference,sharepointIds,system"
)

RETRIABLE_STATUS_CODES = {429, 500, 502, 503}
MAX_RETRIES = 5
INITIAL_BACKOFF = 1.0  # seconds; doubled after each retry
REQUEST_TIMEOUT = 30  # seconds

# Default paging caps (small so tests never hang; users can raise them).
DEFAULT_MAX_PAGES = 100
DEFAULT_TOP = 200
