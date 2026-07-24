"""Tests for the City of Austin, Texas (Socrata) LakeflowConnect connector.

Runs against the in-process source simulator described by
``source_simulator/specs/hackathon_austin_texas/``. Each of the seven tables
is a Socrata dataset at ``/resource/{4x4}.json`` served with offset/limit
pagination from a synthesized corpus.

The connector implements ``SupportsPartitionedStream`` (all tables are
partitioned on the ``:updated_at`` cursor), so this suite mixes in
``SupportsPartitionedStreamTests`` alongside the base ``LakeflowConnectTests``.

Stand-in credentials below are values of the right shape; the simulator
never validates them. Authentication is an optional ``X-App-Token`` header,
so a placeholder token is sufficient.
"""

from __future__ import annotations

from databricks.labs.community_connector.sources.hackathon_austin_texas.hackathon_austin_texas import (
    HackathonAustinTexasLakeflowConnect,
)
from tests.unit.sources.test_partition_suite import (
    SupportsPartitionedStreamTests,
)
from tests.unit.sources.test_suite import LakeflowConnectTests


class TestHackathonAustinTexasConnector(
    LakeflowConnectTests, SupportsPartitionedStreamTests
):
    connector_class = HackathonAustinTexasLakeflowConnect
    simulator_source = "hackathon_austin_texas"
    sample_records = 50

    # Optional Socrata app token — the simulator never validates it, so any
    # placeholder string of the right shape works.
    replay_config = {
        "app_token": "simulator-fake-app-token",
    }
