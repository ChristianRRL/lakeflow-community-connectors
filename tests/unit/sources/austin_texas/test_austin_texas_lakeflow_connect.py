from databricks.labs.community_connector.sources.austin_texas.austin_texas import (
    AustinTexasLakeflowConnect,
)
from tests.unit.sources.test_suite import LakeflowConnectTests


class TestAustinTexasConnector(LakeflowConnectTests):
    """Simulate-mode tests for the Austin, Texas Socrata connector.

    Spec + corpus live at ``source_simulator/specs/austin_texas/``. The
    single table (``green_building_ratings_aggregate``, resource dpvb-c5fy)
    is a full snapshot each sync, served from a bare JSON array with SODA
    ``$offset``/``$limit`` paging.
    """

    connector_class = AustinTexasLakeflowConnect
    simulator_source = "austin_texas"
    # The Socrata app token is optional (public dataset). The simulator
    # never validates credentials, so a minimal stand-in config suffices.
    replay_config = {"app_token": "simulator-fake-token"}
