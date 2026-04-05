#!/usr/bin/env python3
"""Cloudflare DNS Manager — interactive TUI for viewing and managing DNS records."""

import os
import sys

from dotenv import load_dotenv
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, Select, Switch

from cloudflare import PRIORITY_TYPES, PROXIABLE_TYPES, CloudflareAPI

RECORD_TYPES = [
    "A", "AAAA", "CNAME", "MX", "TXT", "NS", "CAA", "SRV", "PTR", "HTTPS", "TLSA", "DS",
]


class RecordFormModal(ModalScreen):
    """Create or edit a DNS record."""

    DEFAULT_CSS = """
    RecordFormModal {
        align: center middle;
    }
    #form-dialog {
        background: $surface;
        border: thick $primary;
        padding: 1 3;
        width: 74;
        height: auto;
    }
    #form-title {
        text-align: center;
        text-style: bold;
        color: $accent;
        padding-bottom: 1;
    }
    .field-row {
        height: 3;
        align: left middle;
    }
    .field-label {
        width: 12;
        text-align: right;
        padding-right: 1;
        padding-top: 1;
        color: $text-muted;
    }
    .field-row Input, .field-row Select {
        width: 1fr;
    }
    #button-row {
        margin-top: 1;
        align: center middle;
        height: 3;
    }
    #button-row Button {
        margin: 0 1;
    }
    """

    def __init__(self, zone_name: str, record: dict | None = None):
        super().__init__()
        self.zone_name = zone_name
        self.record = record

    def compose(self) -> ComposeResult:
        title = f"{'Edit' if self.record else 'New'} Record — {self.zone_name}"
        # Ensure the record's type is in our list
        initial_type = (self.record["type"] if self.record else "A") or "A"
        type_options = RECORD_TYPES if initial_type in RECORD_TYPES else [initial_type, *RECORD_TYPES]

        with Vertical(id="form-dialog"):
            yield Label(title, id="form-title")
            with Horizontal(classes="field-row"):
                yield Label("Type:", classes="field-label")
                yield Select(
                    [(t, t) for t in type_options],
                    id="field-type",
                    value=initial_type,
                    allow_blank=False,
                )
            with Horizontal(classes="field-row"):
                yield Label("Name:", classes="field-label")
                yield Input(
                    value=self.record["name"] if self.record else "",
                    placeholder="@ or subdomain",
                    id="field-name",
                )
            with Horizontal(classes="field-row"):
                yield Label("Content:", classes="field-label")
                yield Input(
                    value=self.record["content"] if self.record else "",
                    placeholder="IP address, hostname, or value",
                    id="field-content",
                )
            with Horizontal(classes="field-row", id="priority-row"):
                yield Label("Priority:", classes="field-label")
                priority_val = str(self.record.get("priority", 10)) if self.record else "10"
                yield Input(value=priority_val, placeholder="e.g. 10", id="field-priority")
            with Horizontal(classes="field-row"):
                yield Label("TTL:", classes="field-label")
                ttl_val = str(self.record.get("ttl", 1)) if self.record else "1"
                yield Input(value=ttl_val, placeholder="1 = Auto", id="field-ttl")
            with Horizontal(classes="field-row", id="proxied-row"):
                yield Label("Proxied:", classes="field-label")
                proxied_val = self.record.get("proxied", False) if self.record else False
                yield Switch(value=proxied_val, id="field-proxied")
            with Horizontal(id="button-row"):
                yield Button("Save", variant="primary", id="btn-save")
                yield Button("Cancel", id="btn-cancel")

    def on_mount(self) -> None:
        self._update_field_visibility()
        self.query_one("#field-name", Input).focus()

    def _update_field_visibility(self) -> None:
        rec_type = self.query_one("#field-type", Select).value
        if rec_type is Select.NULL:
            return
        self.query_one("#priority-row").display = rec_type in PRIORITY_TYPES
        self.query_one("#proxied-row").display = rec_type in PROXIABLE_TYPES

    @on(Select.Changed, "#field-type")
    def on_type_changed(self, event: Select.Changed) -> None:
        self._update_field_visibility()

    @on(Button.Pressed, "#btn-cancel")
    def on_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn-save")
    def on_save(self) -> None:
        rec_type = self.query_one("#field-type", Select).value
        if rec_type is Select.NULL:
            self.notify("Please select a record type", severity="warning")
            return

        name = self.query_one("#field-name", Input).value.strip()
        content = self.query_one("#field-content", Input).value.strip()
        ttl_str = self.query_one("#field-ttl", Input).value.strip() or "1"

        if not name or not content:
            self.notify("Name and content are required", severity="warning")
            return

        try:
            ttl = int(ttl_str)
        except ValueError:
            self.notify("TTL must be a number (1 = Auto)", severity="warning")
            return

        data: dict = {"type": rec_type, "name": name, "content": content, "ttl": ttl}

        if rec_type in PROXIABLE_TYPES:
            data["proxied"] = self.query_one("#field-proxied", Switch).value

        if rec_type in PRIORITY_TYPES:
            priority_str = self.query_one("#field-priority", Input).value.strip() or "10"
            try:
                data["priority"] = int(priority_str)
            except ValueError:
                self.notify("Priority must be a number", severity="warning")
                return

        result: dict = {"data": data}
        if self.record:
            result["id"] = self.record["id"]
        self.dismiss(result)


class ConfirmModal(ModalScreen):
    """Confirmation dialog for destructive actions."""

    DEFAULT_CSS = """
    ConfirmModal {
        align: center middle;
    }
    #confirm-dialog {
        background: $surface;
        border: thick $error;
        padding: 2 4;
        width: 54;
        height: auto;
    }
    #confirm-message {
        text-align: center;
        padding-bottom: 2;
    }
    #confirm-buttons {
        align: center middle;
        height: 3;
    }
    #confirm-buttons Button {
        margin: 0 1;
    }
    """

    def __init__(self, message: str):
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Label(self.message, id="confirm-message")
            with Horizontal(id="confirm-buttons"):
                yield Button("Delete", variant="error", id="btn-confirm")
                yield Button("Cancel", id="btn-cancel")

    @on(Button.Pressed, "#btn-confirm")
    def on_confirm(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#btn-cancel")
    def on_cancel(self) -> None:
        self.dismiss(False)


class DNSManagerApp(App):
    """Cloudflare DNS Manager TUI."""

    TITLE = "CF DNS Manager"

    DEFAULT_CSS = """
    Screen {
        background: $background;
    }
    #main {
        height: 1fr;
        padding: 1;
    }
    #zones-panel {
        width: 34;
        border: round $primary;
        margin-right: 1;
    }
    #records-panel {
        width: 1fr;
        border: round $primary;
    }
    .panel-title {
        background: $primary;
        color: $text;
        padding: 0 1;
        width: 100%;
        text-align: center;
        text-style: bold;
    }
    #zones-table {
        height: 1fr;
    }
    #records-table {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("n", "new_record", "New"),
        Binding("e", "edit_record", "Edit"),
        Binding("d", "delete_record", "Delete"),
        Binding("escape", "focus_zones", "Zones", show=False),
        Binding("left", "focus_zones", "Zones", show=False),
    ]

    def __init__(self, api: CloudflareAPI):
        super().__init__()
        self.api = api
        self.zones: list[dict] = []
        self.records: list[dict] = []
        self.selected_zone: dict | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            with Vertical(id="zones-panel"):
                yield Label("Zones", classes="panel-title")
                yield DataTable(id="zones-table", cursor_type="row", zebra_stripes=True)
            with Vertical(id="records-panel"):
                yield Label("DNS Records", id="records-title", classes="panel-title")
                yield DataTable(id="records-table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        zones_table = self.query_one("#zones-table", DataTable)
        zones_table.add_column("Zone Name", key="name")

        records_table = self.query_one("#records-table", DataTable)
        records_table.add_column("Name", key="name")
        records_table.add_column("Type", key="type")
        records_table.add_column("Content", key="content")
        records_table.add_column("TTL", key="ttl")
        records_table.add_column("Prx", key="proxied")

        self.load_zones()

    @work(exclusive=True, thread=True)
    def load_zones(self) -> None:
        try:
            zones = self.api.get_zones()
            self.call_from_thread(self._populate_zones, zones)
        except Exception as e:
            self.call_from_thread(self.notify, f"Failed to load zones: {e}", severity="error")

    def _populate_zones(self, zones: list[dict]) -> None:
        self.zones = zones
        table = self.query_one("#zones-table", DataTable)
        table.clear()
        for zone in zones:
            table.add_row(zone["name"], key=zone["id"])
        if zones:
            self.selected_zone = zones[0]
            self.load_records(zones[0]["id"])

    @work(exclusive=True, thread=True)
    def load_records(self, zone_id: str) -> None:
        try:
            records = self.api.get_dns_records(zone_id)
            self.call_from_thread(self._populate_records, records)
        except Exception as e:
            self.call_from_thread(self.notify, f"Failed to load records: {e}", severity="error")

    def _populate_records(self, records: list[dict]) -> None:
        self.records = records
        table = self.query_one("#records-table", DataTable)
        table.clear()
        for record in records:
            ttl_val = "Auto" if record.get("ttl") == 1 else str(record.get("ttl", ""))
            if record.get("proxiable"):
                proxied_val = "✓" if record.get("proxied") else "✗"
            else:
                proxied_val = "—"
            table.add_row(
                record["name"],
                record["type"],
                record["content"],
                ttl_val,
                proxied_val,
                key=record["id"],
            )
        zone_name = self.selected_zone["name"] if self.selected_zone else ""
        self.query_one("#records-title", Label).update(f"DNS Records — {zone_name}")

    @on(DataTable.RowHighlighted, "#zones-table")
    def on_zone_highlighted(self, event: DataTable.RowHighlighted) -> None:
        idx = event.cursor_row
        if 0 <= idx < len(self.zones):
            zone = self.zones[idx]
            if self.selected_zone is None or self.selected_zone["id"] != zone["id"]:
                self.selected_zone = zone
                self.load_records(zone["id"])

    @on(DataTable.RowSelected, "#zones-table")
    def on_zone_selected(self) -> None:
        self.query_one("#records-table", DataTable).focus()

    def _selected_record(self) -> dict | None:
        table = self.query_one("#records-table", DataTable)
        if not self.records or table.row_count == 0:
            return None
        idx = table.cursor_row
        return self.records[idx] if 0 <= idx < len(self.records) else None

    def action_focus_zones(self) -> None:
        self.query_one("#zones-table", DataTable).focus()

    def action_refresh(self) -> None:
        self.load_zones()

    def action_new_record(self) -> None:
        if not self.selected_zone:
            self.notify("Select a zone first", severity="warning")
            return
        self.push_screen(RecordFormModal(self.selected_zone["name"]), self._on_form_result)

    def action_edit_record(self) -> None:
        record = self._selected_record()
        if not record or not self.selected_zone:
            self.notify("Select a record to edit", severity="warning")
            return
        self.push_screen(
            RecordFormModal(self.selected_zone["name"], record=record),
            self._on_form_result,
        )

    def action_delete_record(self) -> None:
        record = self._selected_record()
        if not record or not self.selected_zone:
            self.notify("Select a record to delete", severity="warning")
            return
        msg = f"Delete '{record['name']}' ({record['type']})?\n\nThis cannot be undone."
        self.push_screen(
            ConfirmModal(msg),
            lambda confirmed: self._on_delete_confirmed(confirmed, record),
        )

    def _on_form_result(self, result: dict | None) -> None:
        if not result or not self.selected_zone:
            return
        zone_id = self.selected_zone["id"]
        if "id" in result:
            self._update_record(zone_id, result["id"], result["data"])
        else:
            self._create_record(zone_id, result["data"])

    def _on_delete_confirmed(self, confirmed: bool | None, record: dict) -> None:
        if confirmed and self.selected_zone:
            self._delete_record(self.selected_zone["id"], record["id"])

    @work(thread=True)
    def _create_record(self, zone_id: str, data: dict) -> None:
        try:
            self.api.create_dns_record(zone_id, data)
            self.call_from_thread(self.notify, "Record created")
            self.call_from_thread(self.load_records, zone_id)
        except Exception as e:
            self.call_from_thread(self.notify, f"Failed to create record: {e}", severity="error")

    @work(thread=True)
    def _update_record(self, zone_id: str, record_id: str, data: dict) -> None:
        try:
            self.api.update_dns_record(zone_id, record_id, data)
            self.call_from_thread(self.notify, "Record updated")
            self.call_from_thread(self.load_records, zone_id)
        except Exception as e:
            self.call_from_thread(self.notify, f"Failed to update record: {e}", severity="error")

    @work(thread=True)
    def _delete_record(self, zone_id: str, record_id: str) -> None:
        try:
            self.api.delete_dns_record(zone_id, record_id)
            self.call_from_thread(self.notify, "Record deleted")
            self.call_from_thread(self.load_records, zone_id)
        except Exception as e:
            self.call_from_thread(self.notify, f"Failed to delete record: {e}", severity="error")


def main():
    load_dotenv()
    token = os.getenv("CLOUDFLARE_API_TOKEN")
    if not token:
        print(
            "Error: CLOUDFLARE_API_TOKEN not set in environment or .env file",
            file=sys.stderr,
        )
        sys.exit(1)
    DNSManagerApp(CloudflareAPI(token)).run()


if __name__ == "__main__":
    main()
