#!/usr/bin/env python3
"""Cloudflare Manager — interactive TUI for managing DNS records and R2 storage."""

import os
import sys

from dotenv import load_dotenv
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, Select, Switch, TabbedContent, TabPane

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


class BucketCreateModal(ModalScreen):
    """Create a new R2 bucket."""

    DEFAULT_CSS = """
    BucketCreateModal {
        align: center middle;
    }
    #bucket-dialog {
        background: $surface;
        border: thick $primary;
        padding: 1 3;
        width: 54;
        height: auto;
    }
    #bucket-title {
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
    .field-row Input {
        width: 1fr;
    }
    #bucket-buttons {
        margin-top: 1;
        align: center middle;
        height: 3;
    }
    #bucket-buttons Button {
        margin: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="bucket-dialog"):
            yield Label("New R2 Bucket", id="bucket-title")
            with Horizontal(classes="field-row"):
                yield Label("Name:", classes="field-label")
                yield Input(placeholder="my-bucket", id="field-bucket-name")
            with Horizontal(classes="field-row"):
                yield Label("Location:", classes="field-label")
                yield Input(placeholder="WNAM, ENAM, WEUR… (optional)", id="field-bucket-location")
            with Horizontal(id="bucket-buttons"):
                yield Button("Create", variant="primary", id="btn-save")
                yield Button("Cancel", id="btn-cancel")

    def on_mount(self) -> None:
        self.query_one("#field-bucket-name", Input).focus()

    @on(Button.Pressed, "#btn-cancel")
    def on_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn-save")
    def on_save(self) -> None:
        name = self.query_one("#field-bucket-name", Input).value.strip()
        if not name:
            self.notify("Bucket name is required", severity="warning")
            return
        location = self.query_one("#field-bucket-location", Input).value.strip() or None
        self.dismiss({"name": name, "location": location})


class CFManagerApp(App):
    """Cloudflare Manager TUI."""

    TITLE = "CF Manager"

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
    #buckets-panel {
        width: 34;
        border: round $primary;
        margin-right: 1;
    }
    #objects-panel {
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
    #buckets-table {
        height: 1fr;
    }
    #objects-table {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("n", "new_item", "New"),
        Binding("e", "edit_record", "Edit", show=True),
        Binding("d", "delete_item", "Delete"),
        Binding("h", "focus_left", "Left panel", show=False),
        Binding("1", "switch_tab('dns')", "1:DNS"),
        Binding("2", "switch_tab('r2')", "2:R2"),
    ]

    def __init__(self, api: CloudflareAPI):
        super().__init__()
        self.api = api
        self.zones: list[dict] = []
        self.records: list[dict] = []
        self.selected_zone: dict | None = None
        self.buckets: list[dict] = []
        self.objects: list[dict] = []
        self.selected_bucket: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(id="tabs"):
            with TabPane("DNS", id="dns"):
                with Horizontal(id="main"):
                    with Vertical(id="zones-panel"):
                        yield Label("Zones", classes="panel-title")
                        yield DataTable(id="zones-table", cursor_type="row", zebra_stripes=True)
                    with Vertical(id="records-panel"):
                        yield Label("DNS Records", id="records-title", classes="panel-title")
                        yield DataTable(id="records-table", cursor_type="row", zebra_stripes=True)
            with TabPane("R2", id="r2"):
                with Horizontal(id="r2-main"):
                    with Vertical(id="buckets-panel"):
                        yield Label("Buckets", classes="panel-title")
                        yield DataTable(id="buckets-table", cursor_type="row", zebra_stripes=True)
                    with Vertical(id="objects-panel"):
                        yield Label("Objects", id="objects-title", classes="panel-title")
                        yield DataTable(id="objects-table", cursor_type="row", zebra_stripes=True)
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

        buckets_table = self.query_one("#buckets-table", DataTable)
        buckets_table.add_column("Bucket Name", key="name")

        objects_table = self.query_one("#objects-table", DataTable)
        objects_table.add_column("Key", key="key")
        objects_table.add_column("Size", key="size")
        objects_table.add_column("Modified", key="modified")

        self.load_zones()
        if self.api.account_id:
            self.load_buckets()

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

    @on(DataTable.RowHighlighted, "#buckets-table")
    def on_bucket_highlighted(self, event: DataTable.RowHighlighted) -> None:
        idx = event.cursor_row
        if 0 <= idx < len(self.buckets):
            bucket = self.buckets[idx]
            if self.selected_bucket != bucket["name"]:
                self.selected_bucket = bucket["name"]
                self.load_objects(bucket["name"])

    @on(DataTable.RowSelected, "#buckets-table")
    def on_bucket_selected(self) -> None:
        self.query_one("#objects-table", DataTable).focus()

    def _active_tab(self) -> str:
        return self.query_one(TabbedContent).active

    def _selected_record(self) -> dict | None:
        table = self.query_one("#records-table", DataTable)
        if not self.records or table.row_count == 0:
            return None
        idx = table.cursor_row
        return self.records[idx] if 0 <= idx < len(self.records) else None

    def _selected_object(self) -> dict | None:
        table = self.query_one("#objects-table", DataTable)
        if not self.objects or table.row_count == 0:
            return None
        idx = table.cursor_row
        return self.objects[idx] if 0 <= idx < len(self.objects) else None

    def action_focus_left(self) -> None:
        if self._active_tab() == "r2":
            self.query_one("#buckets-table", DataTable).focus()
        else:
            self.query_one("#zones-table", DataTable).focus()

    def action_switch_tab(self, tab: str) -> None:
        self.query_one(TabbedContent).active = tab

    def action_refresh(self) -> None:
        if self._active_tab() == "r2":
            self.load_buckets()
            if self.selected_bucket:
                self.load_objects(self.selected_bucket)
        else:
            self.load_zones()

    def action_new_item(self) -> None:
        if self._active_tab() == "r2":
            self._action_new_bucket()
        else:
            self._action_new_record()

    def _action_new_record(self) -> None:
        if not self.selected_zone:
            self.notify("Select a zone first", severity="warning")
            return
        self.push_screen(RecordFormModal(self.selected_zone["name"]), self._on_form_result)

    def _action_new_bucket(self) -> None:
        if not self.api.account_id:
            self.notify("CLOUDFLARE_ACCOUNT_ID not set", severity="error")
            return
        self.push_screen(BucketCreateModal(), self._on_bucket_create_result)

    def action_edit_record(self) -> None:
        if self._active_tab() != "dns":
            return
        record = self._selected_record()
        if not record or not self.selected_zone:
            self.notify("Select a record to edit", severity="warning")
            return
        self.push_screen(
            RecordFormModal(self.selected_zone["name"], record=record),
            self._on_form_result,
        )

    def action_delete_item(self) -> None:
        if self._active_tab() == "r2":
            self._action_delete_r2()
        else:
            self._action_delete_record()

    def _action_delete_record(self) -> None:
        record = self._selected_record()
        if not record or not self.selected_zone:
            self.notify("Select a record to delete", severity="warning")
            return
        msg = f"Delete '{record['name']}' ({record['type']})?\n\nThis cannot be undone."
        self.push_screen(
            ConfirmModal(msg),
            lambda confirmed: self._on_delete_record_confirmed(confirmed, record),
        )

    def _action_delete_r2(self) -> None:
        # If focus is on objects table, delete object; otherwise delete bucket
        focused = self.focused
        objects_table = self.query_one("#objects-table", DataTable)
        if focused is objects_table:
            obj = self._selected_object()
            if not obj or not self.selected_bucket:
                self.notify("Select an object to delete", severity="warning")
                return
            msg = f"Delete object '{obj['key']}' from '{self.selected_bucket}'?\n\nThis cannot be undone."
            self.push_screen(
                ConfirmModal(msg),
                lambda confirmed: self._on_delete_object_confirmed(confirmed, obj),
            )
        else:
            idx = self.query_one("#buckets-table", DataTable).cursor_row
            if not self.buckets or not (0 <= idx < len(self.buckets)):
                self.notify("Select a bucket to delete", severity="warning")
                return
            bucket = self.buckets[idx]
            msg = f"Delete bucket '{bucket['name']}'?\n\nThis cannot be undone."
            self.push_screen(
                ConfirmModal(msg),
                lambda confirmed: self._on_delete_bucket_confirmed(confirmed, bucket["name"]),
            )

    def _on_form_result(self, result: dict | None) -> None:
        if not result or not self.selected_zone:
            return
        zone_id = self.selected_zone["id"]
        if "id" in result:
            self._update_record(zone_id, result["id"], result["data"])
        else:
            self._create_record(zone_id, result["data"])

    def _on_bucket_create_result(self, result: dict | None) -> None:
        if not result:
            return
        self._create_bucket(result["name"], result.get("location"))

    def _on_delete_record_confirmed(self, confirmed: bool | None, record: dict) -> None:
        if confirmed and self.selected_zone:
            self._delete_record(self.selected_zone["id"], record["id"])

    def _on_delete_bucket_confirmed(self, confirmed: bool | None, name: str) -> None:
        if confirmed:
            self._delete_bucket(name)

    def _on_delete_object_confirmed(self, confirmed: bool | None, obj: dict) -> None:
        if confirmed and self.selected_bucket:
            self._delete_object(self.selected_bucket, obj["key"])

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

    # ------------------------------------------------------------------
    # R2 workers
    # ------------------------------------------------------------------

    @work(exclusive=True, thread=True)
    def load_buckets(self) -> None:
        try:
            buckets = self.api.list_r2_buckets()
            self.call_from_thread(self._populate_buckets, buckets)
        except Exception as e:
            self.call_from_thread(self.notify, f"Failed to load buckets: {e}", severity="error")

    def _populate_buckets(self, buckets: list[dict]) -> None:
        self.buckets = buckets
        table = self.query_one("#buckets-table", DataTable)
        table.clear()
        for b in buckets:
            table.add_row(b["name"], key=b["name"])
        if buckets and not self.selected_bucket:
            self.selected_bucket = buckets[0]["name"]
            self.load_objects(buckets[0]["name"])

    @work(exclusive=True, thread=True)
    def load_objects(self, bucket: str) -> None:
        try:
            objects = self.api.list_r2_objects(bucket)
            self.call_from_thread(self._populate_objects, objects, bucket)
        except Exception as e:
            self.call_from_thread(self.notify, f"Failed to load objects: {e}", severity="error")

    def _populate_objects(self, objects: list[dict], bucket: str) -> None:
        self.objects = objects
        table = self.query_one("#objects-table", DataTable)
        table.clear()
        for o in objects:
            size = str(o.get("size", ""))
            modified = o.get("uploaded", "")
            table.add_row(o["key"], size, modified, key=o["key"])
        self.query_one("#objects-title", Label).update(f"Objects — {bucket}")

    @work(thread=True)
    def _create_bucket(self, name: str, location: str | None) -> None:
        try:
            self.api.create_r2_bucket(name, location=location)
            self.call_from_thread(self.notify, f"Bucket '{name}' created")
            self.call_from_thread(self.load_buckets)
        except Exception as e:
            self.call_from_thread(self.notify, f"Failed to create bucket: {e}", severity="error")

    @work(thread=True)
    def _delete_bucket(self, name: str) -> None:
        try:
            self.api.delete_r2_bucket(name)
            self.call_from_thread(self.notify, f"Bucket '{name}' deleted")
            if self.selected_bucket == name:
                self.selected_bucket = None
                self.call_from_thread(self._populate_objects, [], name)
            self.call_from_thread(self.load_buckets)
        except Exception as e:
            self.call_from_thread(self.notify, f"Failed to delete bucket: {e}", severity="error")

    @work(thread=True)
    def _delete_object(self, bucket: str, key: str) -> None:
        try:
            self.api.delete_r2_object(bucket, key)
            self.call_from_thread(self.notify, f"Deleted '{key}'")
            self.call_from_thread(self.load_objects, bucket)
        except Exception as e:
            self.call_from_thread(self.notify, f"Failed to delete object: {e}", severity="error")


def main():
    load_dotenv()
    token = os.getenv("CLOUDFLARE_API_TOKEN")
    if not token:
        print(
            "Error: CLOUDFLARE_API_TOKEN not set in environment or .env file",
            file=sys.stderr,
        )
        sys.exit(1)
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID")
    CFManagerApp(CloudflareAPI(token, account_id=account_id)).run()


if __name__ == "__main__":
    main()
