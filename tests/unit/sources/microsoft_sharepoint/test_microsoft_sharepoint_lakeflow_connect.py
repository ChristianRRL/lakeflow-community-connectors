"""Tests for the Microsoft SharePoint (Microsoft Graph) LakeflowConnect connector.

Runs against the in-process source simulator described by
``source_simulator/specs/microsoft_sharepoint/``. The connector hits:

  * ``login.microsoftonline.com/<tenant>/oauth2/v2.0/token`` — stub Bearer
    token (corpus ``auth_token``).
  * ``graph.microsoft.com/v1.0/sites/root`` (or ``/sites/{selector}``) — site
    resolution to the opaque composite Graph site-id (corpus ``site``).
  * ``graph.microsoft.com/v1.0/sites/{site-id}/lists`` — snapshot of lists
    (corpus ``lists``).
  * ``graph.microsoft.com/v1.0/sites/{site-id}/lists/{list-id}/items`` and
    ``.../items/delta`` — list items, full and delta (corpus ``list_items``).

The connector extends ``SupportsPartition`` (batch full-refresh parallelism),
so the test class mixes in ``SupportsPartitionTests`` alongside
``LakeflowConnectTests``. Both tables are therefore exercised through the
partitioned read path.

Stand-in credentials below are values of the right shape; the simulator does
not validate them.
"""

from __future__ import annotations

from databricks.labs.community_connector.sources.microsoft_sharepoint.microsoft_sharepoint import (
    MicrosoftSharepointLakeflowConnect,
)
from tests.unit.sources.test_partition_suite import SupportsPartitionTests
from tests.unit.sources.test_suite import LakeflowConnectTests


class TestMicrosoftSharepointConnector(LakeflowConnectTests, SupportsPartitionTests):
    connector_class = MicrosoftSharepointLakeflowConnect
    simulator_source = "microsoft_sharepoint"
    sample_records = 5

    # Stand-in credentials. The simulator never validates these — any values
    # of the right shape work. Plausible GUID-shaped strings so the OAuth
    # token URL match (``{tenant_id}``) and the client-credentials request
    # both work. No ``site_id`` / ``site_url`` so the connector exercises the
    # ``/sites/root`` resolution path.
    replay_config = {
        "tenant_id": "00000000-0000-0000-0000-000000000000",
        "client_id": "11111111-1111-1111-1111-111111111111",
        "client_secret": "simulator-fake-client-secret",
    }
