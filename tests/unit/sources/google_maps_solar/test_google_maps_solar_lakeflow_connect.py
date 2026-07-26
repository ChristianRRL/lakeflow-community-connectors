import pytest

from databricks.labs.community_connector.libs.utils import parse_value
from databricks.labs.community_connector.sources.google_maps_solar.google_maps_solar import (
    GoogleMapsSolarLakeflowConnect,
)
from tests.unit.sources.test_partition_suite import SupportsPartitionTests
from tests.unit.sources.test_suite import LakeflowConnectTests


class TestGoogleMapsSolarConnector(LakeflowConnectTests, SupportsPartitionTests):
    """Simulate-mode suite for the Solar API connector.

    The connector implements ``SupportsPartition`` (one partition per query
    location) but not ``SupportsPartitionedStream`` — there is no cursor to
    split a stream on — so only ``SupportsPartitionTests`` is mixed in. Every
    table therefore reports as partitioned and the read coverage comes from
    ``get_partitions`` / ``read_partition`` rather than ``read_table``.
    """

    connector_class = GoogleMapsSolarLakeflowConnect
    simulator_source = "google_maps_solar"
    sample_records = 5

    # The Solar API has no discovery endpoint, so a query location is
    # mandatory input rather than something the connector can default. It is
    # declared at connection level here so every table inherits it; the
    # simulator never validates ``api_key``.
    #
    # Two locations, not one: the location fan-out is the whole reason this
    # connector implements ``SupportsPartition``, and a single-location config
    # would let a broken ``get_partitions`` pass. Note the simulator serves the
    # same corpus entity for every location (the spec is not location-keyed),
    # so the two partitions return identical payloads offline — the fan-out
    # itself is what is under test, not the per-location content.
    replay_config = {
        "api_key": "simulator-fake-api-key",
        "locations": "37.4450,-122.1390;40.7128,-74.0060",
    }

    table_configs = {
        "building_insights": {
            "requiredQuality": "HIGH",
            # Exercises the detectedArrays branch of buildingInsights:findClosest.
            "additionalInsights": "DETECTED_ARRAYS",
        },
        "data_layers": {
            "radiusMeters": "100",
            "view": "FULL_LAYERS",
        },
        "geo_tiff": {
            "radiusMeters": "100",
            # Keep the fan-out tiny: without a filter a single location
            # resolves ~17 rasters (5 scalar layers + 12 monthly shade
            # tiles), each a separate download. ``hourly_shade`` is kept in
            # the mix because it is the only layer that populates
            # ``month_index``.
            "layer_types": "dsm,hourly_shade",
            "max_assets_per_location": "3",
        },
    }

    # ------------------------------------------------------------------
    # Supplementary coverage
    #
    # ``LakeflowConnectTests`` routes every read assertion through
    # ``_non_partitioned_tables()``, which is empty for a ``SupportsPartition``
    # connector — so ``test_read_table`` / ``test_read_terminates`` /
    # ``test_every_column_populated_by_at_least_one_record`` all skip here.
    # ``read_table`` is still the single-driver path SDP takes when it does
    # not partition, so it gets equivalent checks below.
    # ------------------------------------------------------------------

    def test_read_table_snapshot_round_trip(self):
        """read_table yields schema-valid records and a terminal empty offset.

        All three tables are snapshot with no cursor, so the offset contract
        is trivially satisfied only if the connector returns ``{}`` — an
        offset that compares equal to the ``{}`` it was handed, which is what
        makes ``Trigger.AvailableNow`` stop after one pass.
        """
        errors = []
        for table in self._tables():
            opts = self._opts(table)
            schema = self.connector.get_table_schema(table, opts)
            iterator, offset = self.connector.read_table(table, {}, opts)
            records = self._consume(iterator)

            if offset != {}:
                errors.append(
                    f"[{table}] read_table returned offset {offset!r}; snapshot "
                    "tables must return an empty offset so the first call is "
                    "also the terminal one."
                )
            if not records:
                errors.append(f"[{table}] read_table returned no records.")
                continue
            for i, record in enumerate(records):
                try:
                    parse_value(record, schema)
                except Exception as e:
                    errors.append(f"[{table}] record {i} failed schema parsing: {e}")
        if errors:
            pytest.fail("\n\n".join(errors))

    def test_one_partition_per_configured_location(self):
        """The fan-out unit is the location, so partitions track them 1:1.

        ``SupportsPartitionTests`` only asserts the partition list is
        non-empty, which a connector that collapsed every location into one
        partition would still satisfy.
        """
        expected = [
            {"latitude": 37.4450, "longitude": -122.1390},
            {"latitude": 40.7128, "longitude": -74.0060},
        ]
        errors = []
        for table in self._tables():
            partitions = list(self.connector.get_partitions(table, self._opts(table)))
            if partitions != expected:
                errors.append(
                    f"[{table}] get_partitions returned {partitions!r}, "
                    f"expected one descriptor per configured location: {expected!r}"
                )
        if errors:
            pytest.fail("\n\n".join(errors))

    def test_read_table_requires_a_location(self):
        """A missing location is a configuration error, not an empty read.

        The Solar API has no discovery endpoint, so defaulting the location
        would silently ingest data about an unrelated building. Uses a fresh
        connector because the location on this suite's ``replay_config`` is a
        connection-level default that every table would otherwise inherit.
        """
        connector = self.connector_class({"api_key": "simulator-fake-api-key"})
        for table in connector.list_tables():
            with pytest.raises(ValueError, match="location"):
                connector.read_table(table, {}, {})
