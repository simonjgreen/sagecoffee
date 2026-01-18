"""Tests for the models module."""

import pytest

from sagecoffee.models import (
    AddApplianceMessage,
    Appliance,
    DeviceState,
    PingMessage,
    StateReport,
)


class TestAppliance:
    """Tests for Appliance model."""

    def test_parse_appliance(self, sample_appliances_response: dict) -> None:
        """Test parsing an appliance from API response."""
        data = sample_appliances_response["appliances"][0]
        appliance = Appliance.model_validate(data)

        assert appliance.serial_number == "A1SKAESA251400639"
        assert appliance.model == "BES995"
        assert appliance.name == "Oracle Dual Boiler"
        assert appliance.pairing_type == "wifi"

    def test_appliance_alias(self) -> None:
        """Test that Appliance handles both camelCase and snake_case."""
        # camelCase (from API)
        a1 = Appliance.model_validate(
            {
                "serialNumber": "ABC123",
                "model": "BES995",
            }
        )
        assert a1.serial_number == "ABC123"

        # snake_case (from Python)
        a2 = Appliance(serial_number="ABC123", model="BES995")
        assert a2.serial_number == "ABC123"


class TestStateReport:
    """Tests for StateReport model."""

    def test_parse_state_report(self, sample_state_report: dict) -> None:
        """Test parsing a state report from WebSocket."""
        report = StateReport.model_validate(sample_state_report)

        assert report.serial_number == "A1SKAESA251400639"
        assert report.message_type == "stateReport"
        assert report.version == 123
        assert "reported" in report.data

    def test_state_report_invalid_type(self) -> None:
        """Test that invalid messageType raises validation error."""
        with pytest.raises(Exception):
            StateReport.model_validate(
                {
                    "serialNumber": "ABC",
                    "messageType": "invalidType",
                    "data": {},
                }
            )


class TestDeviceState:
    """Tests for DeviceState model."""

    def test_from_state_report(self, sample_state_report: dict) -> None:
        """Test creating DeviceState from StateReport."""
        report = StateReport.model_validate(sample_state_report)
        state = DeviceState.from_state_report(report)

        assert state.serial_number == "A1SKAESA251400639"
        assert state.version == 123

    def test_reported_state(self, sample_state_report: dict) -> None:
        """Test getting reported state."""
        report = StateReport.model_validate(sample_state_report)
        state = DeviceState.from_state_report(report)

        assert state.reported_state == "ready"

    def test_desired_state(self, sample_state_report: dict) -> None:
        """Test getting desired state."""
        report = StateReport.model_validate(sample_state_report)
        state = DeviceState.from_state_report(report)

        assert state.desired_state == "ready"

    def test_boiler_temps(self, sample_state_report: dict) -> None:
        """Test getting boiler temperatures."""
        report = StateReport.model_validate(sample_state_report)
        state = DeviceState.from_state_report(report)

        boilers = state.boiler_temps
        assert len(boilers) == 2
        assert boilers[0].current_temp == 93.5
        assert boilers[0].target_temp == 94.0
        assert boilers[1].current_temp == 140.0

    def test_grind_size(self, sample_state_report: dict) -> None:
        """Test getting grind size."""
        report = StateReport.model_validate(sample_state_report)
        state = DeviceState.from_state_report(report)

        assert state.grind_size == 15

    def test_is_remote_wake_enabled(self, sample_state_report: dict) -> None:
        """Test checking remote wake enabled."""
        report = StateReport.model_validate(sample_state_report)
        state = DeviceState.from_state_report(report)

        assert state.is_remote_wake_enabled is True

    def test_timezone(self, sample_state_report: dict) -> None:
        """Test getting timezone."""
        report = StateReport.model_validate(sample_state_report)
        state = DeviceState.from_state_report(report)

        assert state.timezone == "Europe/London"

    def test_empty_state(self) -> None:
        """Test DeviceState with empty data."""
        state = DeviceState(
            raw_data={},
            serial_number="ABC123",
        )

        assert state.reported_state is None
        assert state.desired_state is None
        assert state.boiler_temps == []
        assert state.grind_size is None
        assert state.is_remote_wake_enabled is False
        assert state.timezone is None


class TestMessages:
    """Tests for WebSocket message models."""

    def test_add_appliance_message(self) -> None:
        """Test AddApplianceMessage serialization."""
        msg = AddApplianceMessage(
            serial_number="ABC123",
            app="sageCoffee",
            model="BES995",
        )

        data = msg.model_dump(by_alias=True)

        assert data["action"] == "addAppliance"
        assert data["serialNumber"] == "ABC123"
        assert data["app"] == "sageCoffee"
        assert data["model"] == "BES995"

    def test_ping_message(self) -> None:
        """Test PingMessage serialization."""
        msg = PingMessage()
        data = msg.model_dump()

        assert data["action"] == "ping"
