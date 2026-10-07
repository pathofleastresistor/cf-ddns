#!/usr/bin/env python3
"""Cloudflare Manager — interactive TUI for managing DNS records, R2 storage and API tokens."""

import os
import sys

from dotenv import dotenv_values, find_dotenv, load_dotenv, set_key
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button, DataTable, Footer, Header, Input, Label, OptionList, Select, Switch, TabbedContent, TabPane,
)
from textual.widgets.option_list import Option

import credentials
import token_policy as tp
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

    def __init__(self, message: str, confirm_label: str = "Delete"):
        super().__init__()
        self.message = message
        self.confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Label(self.message, id="confirm-message")
            with Horizontal(id="confirm-buttons"):
                yield Button(self.confirm_label, variant="error", id="btn-confirm")
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


class PermissionPickerModal(ModalScreen):
    """Pick a permission group and the resource it applies to."""

    DEFAULT_CSS = """
    PermissionPickerModal {
        align: center middle;
    }
    #perm-dialog {
        background: $surface;
        border: thick $primary;
        padding: 1 3;
        width: 90;
        height: auto;
        max-height: 90%;
    }
    #perm-title {
        text-align: center;
        text-style: bold;
        color: $accent;
        padding-bottom: 1;
    }
    #perm-options {
        height: 14;
        margin-bottom: 1;
    }
    #perm-desc {
        color: $text-muted;
        height: auto;
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
    .field-row Select {
        width: 1fr;
    }
    #perm-buttons {
        margin-top: 1;
        align: center middle;
        height: 3;
    }
    #perm-buttons Button {
        margin: 0 1;
    }
    """

    def __init__(self, groups: list[dict], ctx: dict):
        super().__init__()
        self.groups = sorted(groups, key=lambda g: g.get("name", ""))
        self.groups_by_id = {g["id"]: g for g in self.groups}
        self.ctx = ctx
        self.choices: list[tuple[str, dict]] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="perm-dialog"):
            yield Label("Add permission", id="perm-title")
            yield Input(placeholder="Filter, e.g. dns, r2, workers, zone", id="perm-filter")
            yield OptionList(id="perm-options")
            yield Label("", id="perm-desc")
            with Horizontal(classes="field-row"):
                yield Label("Resource:", classes="field-label")
                yield Select([], id="perm-resource", prompt="Pick a permission first")
            with Horizontal(classes="field-row"):
                yield Label("Effect:", classes="field-label")
                yield Select([("Allow", "allow"), ("Deny", "deny")], value="allow",
                             allow_blank=False, id="perm-effect")
            with Horizontal(id="perm-buttons"):
                yield Button("Add", variant="primary", id="btn-save")
                yield Button("Cancel", id="btn-cancel")

    def on_mount(self) -> None:
        self._fill_options("")
        self.query_one("#perm-filter", Input).focus()

    def _fill_options(self, text: str) -> None:
        words = text.lower().split()
        options = self.query_one("#perm-options", OptionList)
        options.clear_options()
        options.add_options([
            Option(f"{g['name']}  [dim]({tp.scope_label(g.get('scopes', []))})[/dim]", id=g["id"])
            for g in self.groups
            if all(w in g.get("name", "").lower() for w in words)
        ])

    @on(Input.Changed, "#perm-filter")
    def on_filter(self, event: Input.Changed) -> None:
        self._fill_options(event.value)

    @on(Input.Submitted, "#perm-filter")
    def on_filter_submit(self) -> None:
        self.query_one("#perm-options", OptionList).focus()

    @on(OptionList.OptionHighlighted, "#perm-options")
    def on_group_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        group = self.groups_by_id.get(event.option_id)
        if not group:
            return
        self.query_one("#perm-desc", Label).update(group.get("description", ""))
        self.choices = tp.resource_choices(
            group.get("scopes", []), self.ctx["zones"], self.ctx["account_id"],
            self.ctx["user_tag"], self.ctx["buckets"],
        )
        resource = self.query_one("#perm-resource", Select)
        resource.set_options([(label, i) for i, (label, _) in enumerate(self.choices)])
        if self.choices:
            resource.value = 0

    @on(OptionList.OptionSelected, "#perm-options")
    def on_group_selected(self) -> None:
        self.query_one("#perm-resource", Select).focus()

    @on(Button.Pressed, "#btn-cancel")
    def on_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn-save")
    def on_save(self) -> None:
        options = self.query_one("#perm-options", OptionList)
        if options.highlighted is None:
            self.notify("Pick a permission", severity="warning")
            return
        group = self.groups_by_id[options.get_option_at_index(options.highlighted).id]
        idx = self.query_one("#perm-resource", Select).value
        if idx is Select.NULL or not self.choices:
            msg = "Pick a resource" if self.choices else "No resource available for this scope (user id unknown?)"
            self.notify(msg, severity="warning")
            return
        self.dismiss({
            "effect": self.query_one("#perm-effect", Select).value,
            "group_id": group["id"],
            "group_name": group["name"],
            "resource": self.choices[idx][1],
        })


class TokenFormModal(ModalScreen):
    """Create a token, or edit an existing token's name, permissions and restrictions."""

    BINDINGS = [
        Binding("a", "add_permission", "Add permission"),
        Binding("delete", "remove_permission", "Remove permission"),
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    TokenFormModal {
        align: center middle;
    }
    #token-dialog {
        background: $surface;
        border: thick $primary;
        padding: 1 3;
        width: 110;
        height: 90%;
    }
    #token-title {
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
        width: 14;
        text-align: right;
        padding-right: 1;
        padding-top: 1;
        color: $text-muted;
    }
    .field-row Input, .field-row Select {
        width: 1fr;
    }
    #perm-heading {
        padding-top: 1;
        text-style: bold;
    }
    #token-perm-table {
        height: 1fr;
        border: round $primary;
    }
    #token-buttons {
        margin-top: 1;
        align: center middle;
        height: 3;
    }
    #token-buttons Button {
        margin: 0 1;
    }
    """

    def __init__(self, groups: list[dict], ctx: dict, token: dict | None = None):
        super().__init__()
        self.groups = groups
        self.groups_by_name = {g["name"]: g for g in groups}
        self.groups_by_id = {g["id"]: g for g in groups}
        self.ctx = ctx
        self.token = token
        self.rows = tp.flatten(token.get("policies", [])) if token else []

    def compose(self) -> ComposeResult:
        token = self.token or {}
        title = f"Edit token — {token['name']}" if self.token else "New API token"
        ips = ", ".join(((token.get("condition") or {}).get("request.ip") or {}).get("in", []))
        with Vertical(id="token-dialog"):
            yield Label(title, id="token-title")
            with Horizontal(classes="field-row"):
                yield Label("Name:", classes="field-label")
                yield Input(value=token.get("name", ""), placeholder="e.g. cf-ddns home", id="field-token-name")
            with Horizontal(classes="field-row"):
                yield Label("Expires:", classes="field-label")
                yield Input(value=(token.get("expires_on") or "")[:10],
                            placeholder="YYYY-MM-DD (blank = never)", id="field-token-expires")
            with Horizontal(classes="field-row"):
                yield Label("Client IPs:", classes="field-label")
                yield Input(value=ips, placeholder="Comma-separated IPs/CIDRs allowed to use it (blank = any)",
                            id="field-token-ips")
            if self.token:
                with Horizontal(classes="field-row"):
                    yield Label("Active:", classes="field-label")
                    yield Switch(value=token.get("status") != "disabled", id="field-token-active")
            with Horizontal(classes="field-row"):
                yield Label("Template:", classes="field-label")
                yield Select([(name, name) for name in tp.TEMPLATES], prompt="Add permissions from a template…",
                             id="field-token-template")
            yield Label("Permissions  [dim](a: add · Del: remove selected)[/dim]", id="perm-heading")
            yield DataTable(id="token-perm-table", cursor_type="row", zebra_stripes=True)
            with Horizontal(id="token-buttons"):
                yield Button("Add permission", id="btn-add-perm")
                yield Button("Remove", id="btn-remove-perm")
                yield Button("Save" if self.token else "Create", variant="primary", id="btn-save")
                yield Button("Cancel", id="btn-cancel")

    def on_mount(self) -> None:
        table = self.query_one("#token-perm-table", DataTable)
        table.add_column("Effect", key="effect")
        table.add_column("Permission", key="permission")
        table.add_column("Resource", key="resource")
        self._refresh_rows()
        self.query_one("#field-token-name", Input).focus()

    def _refresh_rows(self) -> None:
        table = self.query_one("#token-perm-table", DataTable)
        table.clear()
        zone_names = {z["id"]: z["name"] for z in self.ctx["zones"]}
        for row in self.rows:
            name = self.groups_by_id.get(row["group_id"], {}).get("name", row["group_name"])
            table.add_row(row["effect"], name, tp.describe(row["resource"], zone_names, self.ctx["account_id"]))

    def _add_row(self, row: dict) -> bool:
        if row in self.rows:
            return False
        self.rows.append(row)
        return True

    @on(Select.Changed, "#field-token-template")
    def on_template(self, event: Select.Changed) -> None:
        if event.value is Select.NULL:
            return
        missing, added = [], 0
        for group_name, scope in tp.TEMPLATES[event.value]:
            group = self.groups_by_name.get(group_name)
            resource = tp.default_resource(scope, self.ctx["account_id"], self.ctx["user_tag"])
            if not group or not resource:
                missing.append(group_name)
                continue
            added += self._add_row({"effect": "allow", "group_id": group["id"],
                                    "group_name": group_name, "resource": resource})
        self._refresh_rows()
        if missing:
            self.notify(f"Not available: {', '.join(missing)}", severity="warning")
        self.notify(f"Added {added} permission(s). To narrow one to a single zone, remove it and add it again.")
        event.select.clear()

    def action_add_permission(self) -> None:
        if isinstance(self.focused, Input):
            return
        self.app.push_screen(PermissionPickerModal(self.groups, self.ctx), self._on_picked)

    def _on_picked(self, row: dict | None) -> None:
        if row and self._add_row(row):
            self._refresh_rows()

    def action_remove_permission(self) -> None:
        if isinstance(self.focused, Input):
            return
        idx = self.query_one("#token-perm-table", DataTable).cursor_row
        if 0 <= idx < len(self.rows):
            del self.rows[idx]
            self._refresh_rows()

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn-add-perm")
    def on_add_perm(self) -> None:
        self.app.push_screen(PermissionPickerModal(self.groups, self.ctx), self._on_picked)

    @on(Button.Pressed, "#btn-remove-perm")
    def on_remove_perm(self) -> None:
        self.action_remove_permission()

    @on(Button.Pressed, "#btn-cancel")
    def on_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn-save")
    def on_save(self) -> None:
        name = self.query_one("#field-token-name", Input).value.strip()
        if not name:
            self.notify("Name is required", severity="warning")
            return
        if not any(r["effect"] == "allow" for r in self.rows):
            self.notify("Add at least one allow permission", severity="warning")
            return
        token = self.token or {}
        expires = self.query_one("#field-token-expires", Input).value.strip()
        if token.get("expires_on") and expires == token["expires_on"][:10]:
            expires_on = token["expires_on"]
        else:
            expires_on = tp.to_expiry(expires)
        body: dict = {
            "name": name,
            "policies": tp.build(self.rows),
            "condition": tp.ip_condition(token.get("condition"),
                                         self.query_one("#field-token-ips", Input).value),
        }
        if expires_on:
            body["expires_on"] = expires_on
        if token.get("not_before"):
            body["not_before"] = token["not_before"]
        if self.token:
            body["status"] = "active" if self.query_one("#field-token-active", Switch).value else "disabled"
        self.dismiss({"id": token.get("id"), "body": body})


class TokenValueModal(ModalScreen):
    """Show a token's secret, which Cloudflare returns only once, and offer to save it."""

    DEFAULT_CSS = """
    TokenValueModal {
        align: center middle;
    }
    #value-dialog {
        background: $surface;
        border: thick $success;
        padding: 1 3;
        width: 90;
        height: auto;
    }
    #value-title {
        text-align: center;
        text-style: bold;
        color: $success;
        padding-bottom: 1;
    }
    .value-note {
        width: 100%;
        color: $text-muted;
        padding: 1 0 0 0;
    }
    #value-targets {
        height: auto;
        padding-top: 1;
    }
    .target-row {
        height: 3;
    }
    .target-row Label {
        width: 1fr;
        padding-top: 1;
    }
    #value-buttons {
        margin-top: 1;
        align: center middle;
        height: 3;
    }
    #value-buttons Button {
        margin: 0 1;
    }
    """

    def __init__(self, name: str, value: str, targets: list[dict] | None = None, on_save=None):
        super().__init__()
        self.token_name = name
        self.value = value
        self.targets = targets or []
        self.on_save = on_save
        self.warned = False

    def compose(self) -> ComposeResult:
        with Vertical(id="value-dialog"):
            yield Label(f"Token value — {self.token_name}", id="value-title")
            yield Input(value=self.value, id="token-value")
            if self.targets:
                yield Label("This token is used in the places below. Save the new value to each:",
                            classes="value-note")
                with Vertical(id="value-targets"):
                    for i, target in enumerate(self.targets):
                        with Horizontal(classes="target-row"):
                            yield Label(target["label"])
                            if target.get("path"):
                                yield Button("Save here", variant="success", id=f"btn-save-target-{i}")
                            else:
                                yield Label("[dim]set outside a file; update it by hand[/dim]")
                yield Label("Anything already running with the old value needs a restart "
                            "(for the cf-ddns container: docker compose up -d).", classes="value-note")
            else:
                yield Label("Cloudflare shows this once. Store it now (e.g. in .env); "
                            "after this it can only be rolled, not viewed.", classes="value-note")
            with Horizontal(id="value-buttons"):
                yield Button("Copy", variant="primary", id="btn-copy")
                yield Button("Done", id="btn-done")

    @on(Button.Pressed, "#btn-copy")
    def on_copy(self) -> None:
        self.app.copy_to_clipboard(self.value)
        self.notify("Copied via the terminal clipboard. If it didn't arrive, select the text instead.")

    @on(Button.Pressed, ".target-row Button")
    def on_save_target(self, event: Button.Pressed) -> None:
        target = self.targets[int(event.button.id.rsplit("-", 1)[1])]
        error = self.on_save(target, self.value) if self.on_save else "nowhere to save"
        if error:
            self.notify(f"Couldn't save to {target['label']}: {error}", severity="error")
            return
        event.button.label = "Saved ✓"
        event.button.disabled = True
        self.notify(f"Saved to {target['label']}")

    @on(Button.Pressed, "#btn-done")
    def on_done(self) -> None:
        unsaved = [t for i, t in enumerate(self.targets) if t.get("path")
                   and not self.query_one(f"#btn-save-target-{i}", Button).disabled]
        if unsaved and not self.warned:
            self.notify("Not saved everywhere yet; this value can't be shown again. "
                        "Press Done again to close anyway.", severity="warning")
            self.warned = True
            return
        self.dismiss(None)

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
    #tokens-panel {
        width: 52;
        border: round $primary;
        margin-right: 1;
    }
    #token-perms-panel {
        width: 1fr;
        border: round $primary;
    }
    #tokens-table, #token-perms-table {
        height: 1fr;
    }
    #token-info {
        height: auto;
        padding: 0 1;
        color: $text-muted;
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
        Binding("3", "switch_tab('tokens')", "3:Tokens"),
        Binding("x", "roll_token", "Roll secret"),
    ]

    def __init__(self, api: CloudflareAPI, token_api: CloudflareAPI | None = None,
                 token_sources: list[dict] | None = None):
        super().__init__()
        self.api = api
        # Token management needs "API Tokens Write"; keep that power off the DDNS token.
        self.token_api = token_api or api
        # Where token secrets live on this machine; see token_sources() below.
        self.token_sources = token_sources or []
        self.tokens: list[dict] = []
        self.perm_groups: list[dict] = []
        self.user_tag: str | None = None
        self.tokens_in_use: dict[str, list[dict]] = {}
        self.tokens_loaded = False
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
            with TabPane("Tokens", id="tokens"):
                with Horizontal(id="tokens-main"):
                    with Vertical(id="tokens-panel"):
                        yield Label("API Tokens", classes="panel-title")
                        yield DataTable(id="tokens-table", cursor_type="row", zebra_stripes=True)
                    with Vertical(id="token-perms-panel"):
                        yield Label("Permissions", id="token-perms-title", classes="panel-title")
                        yield DataTable(id="token-perms-table", cursor_type="row", zebra_stripes=True)
                        yield Label("", id="token-info")
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

        tokens_table = self.query_one("#tokens-table", DataTable)
        tokens_table.add_column("Name", key="name")
        tokens_table.add_column("Status", key="status")
        tokens_table.add_column("Expires", key="expires")

        token_perms_table = self.query_one("#token-perms-table", DataTable)
        token_perms_table.add_column("Effect", key="effect")
        token_perms_table.add_column("Permission", key="permission")
        token_perms_table.add_column("Resource", key="resource")

        self.load_zones()
        if self.api.account_id:
            self.load_buckets()

    @work(exclusive=True, thread=True, group="zones")
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

    @work(exclusive=True, thread=True, group="records")
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
        left = {"r2": "#buckets-table", "tokens": "#tokens-table"}.get(self._active_tab(), "#zones-table")
        self.query_one(left, DataTable).focus()

    @on(TabbedContent.TabActivated)
    def on_tab_activated(self) -> None:
        if self._active_tab() == "tokens" and not self.tokens_loaded:
            self.load_tokens()
        self.refresh_bindings()

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        if action == "roll_token":
            return self._active_tab() == "tokens"
        if action == "edit_record":
            return self._active_tab() in ("dns", "tokens")
        return True

    def action_switch_tab(self, tab: str) -> None:
        self.query_one(TabbedContent).active = tab

    def action_refresh(self) -> None:
        if self._active_tab() == "tokens":
            self.load_tokens()
        elif self._active_tab() == "r2":
            self.load_buckets()
            if self.selected_bucket:
                self.load_objects(self.selected_bucket)
        else:
            self.load_zones()

    def action_new_item(self) -> None:
        if self._active_tab() == "tokens":
            self._action_new_token()
        elif self._active_tab() == "r2":
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
        if self._active_tab() == "tokens":
            self._action_edit_token()
            return
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
        if self._active_tab() == "tokens":
            self._action_delete_token()
        elif self._active_tab() == "r2":
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

    @work(exclusive=True, thread=True, group="buckets")
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

    @work(exclusive=True, thread=True, group="objects")
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

    # ------------------------------------------------------------------
    # API tokens
    # ------------------------------------------------------------------

    def _token_ctx(self) -> dict:
        return {
            "zones": self.zones,
            "account_id": self.api.account_id,
            "user_tag": self.user_tag,
            "buckets": self.buckets,
        }

    def _selected_token(self) -> dict | None:
        table = self.query_one("#tokens-table", DataTable)
        idx = table.cursor_row
        return self.tokens[idx] if self.tokens and 0 <= idx < len(self.tokens) else None

    def _in_use_label(self, token_id: str) -> str:
        return ", ".join(src["label"] for src in self.tokens_in_use.get(token_id, []))

    def _in_use_warning(self, token: dict) -> str:
        label = self._in_use_label(token["id"])
        return f"\n\nUsed in: {label}" if label else ""

    @work(exclusive=True, thread=True, group="tokens")
    def load_tokens(self) -> None:
        try:
            tokens = self.token_api.list_tokens()
            groups = self.token_api.list_permission_groups()
        except Exception as e:
            self.call_from_thread(self._show_token_access_error, str(e))
            return
        in_use: dict[str, list[dict]] = {}
        for src in self.token_sources:
            try:
                token_id = CloudflareAPI(src["value"]).verify_token()["id"]
            except Exception:
                continue
            in_use.setdefault(token_id, []).append(src)
        user_tag = tp.find_user_tag(tokens)
        if not user_tag:
            try:
                user_tag = self.token_api.get_user_tag()
            except Exception:
                pass
        self.call_from_thread(self._populate_tokens, tokens, groups, user_tag, in_use)

    def _show_token_access_error(self, error: str) -> None:
        self.query_one("#tokens-table", DataTable).clear()
        self.query_one("#token-perms-table", DataTable).clear()
        hint = (
            "This token can't manage API tokens. In the Cloudflare dashboard, go to "
            "My Profile → API Tokens → Create Token and use the \"Create Additional Tokens\" template. "
            f"Save that token to {_short(credentials.config_path('admin_token'))} (chmod 600) and restart."
            if "9109" in error or "403" in error else ""
        )
        self.query_one("#token-info", Label).update(f"[red]{error}[/red]\n\n{hint}".strip())

    def _populate_tokens(self, tokens: list[dict], groups: list[dict], user_tag: str | None,
                         in_use: dict[str, list[dict]]) -> None:
        self.tokens_loaded = True
        self.tokens = sorted(tokens, key=lambda t: t.get("name", "").lower())
        self.perm_groups = groups
        self.user_tag = user_tag
        self.tokens_in_use = in_use
        table = self.query_one("#tokens-table", DataTable)
        cursor = table.cursor_row
        table.clear()
        for t in self.tokens:
            name = t["name"] + (" [b]*[/b]" if t["id"] in in_use else "")
            table.add_row(name, t.get("status", ""), (t.get("expires_on") or "never")[:10], key=t["id"])
        if self.tokens:
            table.move_cursor(row=min(cursor, len(self.tokens) - 1))
            self._show_token(self._selected_token())
        else:
            self._show_token(None)

    def _show_token(self, token: dict | None) -> None:
        table = self.query_one("#token-perms-table", DataTable)
        table.clear()
        info = self.query_one("#token-info", Label)
        if not token:
            self.query_one("#token-perms-title", Label).update("Permissions")
            info.update("")
            return
        self.query_one("#token-perms-title", Label).update(f"Permissions — {token['name']}")
        zone_names = {z["id"]: z["name"] for z in self.zones}
        groups_by_id = {g["id"]: g["name"] for g in self.perm_groups}
        for row in tp.flatten(token.get("policies", [])):
            table.add_row(
                row["effect"],
                groups_by_id.get(row["group_id"], row["group_name"]),
                tp.describe(row["resource"], zone_names, self.api.account_id),
            )
        ip = (token.get("condition") or {}).get("request.ip") or {}
        lines = [
            f"Client IPs: {', '.join(ip.get('in', [])) or 'any'}"
            + (f" (except {', '.join(ip['not_in'])})" if ip.get("not_in") else ""),
            f"Issued {(token.get('issued_on') or '?')[:10]} · last used {(token.get('last_used_on') or 'never')[:10]}",
        ]
        if token["id"] in self.tokens_in_use:
            lines.append(f"[b]*[/b] Used in: {self._in_use_label(token['id'])}")
        info.update("\n".join(lines))

    @on(DataTable.RowHighlighted, "#tokens-table")
    def on_token_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if 0 <= event.cursor_row < len(self.tokens):
            self._show_token(self.tokens[event.cursor_row])

    @on(DataTable.RowSelected, "#tokens-table")
    def on_token_selected(self) -> None:
        self._action_edit_token()

    def _tokens_ready(self) -> bool:
        if not self.perm_groups:
            self.notify("Token list not loaded (see the Tokens tab)", severity="warning")
            return False
        return True

    def _action_new_token(self) -> None:
        if self._tokens_ready():
            self.push_screen(TokenFormModal(self.perm_groups, self._token_ctx()), self._on_token_form)

    def _action_edit_token(self) -> None:
        token = self._selected_token()
        if not token:
            self.notify("Select a token to edit", severity="warning")
            return
        if self._tokens_ready():
            self.push_screen(TokenFormModal(self.perm_groups, self._token_ctx(), token=token),
                             self._on_token_form)

    def _action_delete_token(self) -> None:
        token = self._selected_token()
        if not token:
            self.notify("Select a token to delete", severity="warning")
            return
        msg = f"Delete token '{token['name']}'?\n\nAnything using it stops working.{self._in_use_warning(token)}"
        self.push_screen(ConfirmModal(msg),
                         lambda ok: ok and self._delete_token(token["id"]))

    def action_roll_token(self) -> None:
        token = self._selected_token()
        if not token:
            self.notify("Select a token to roll", severity="warning")
            return
        msg = (f"Roll the secret for '{token['name']}'?\n\n"
               f"The current value stops working immediately; put the new one wherever it's used."
               f"{self._in_use_warning(token)}")
        self.push_screen(ConfirmModal(msg, confirm_label="Roll"),
                         lambda ok: ok and self._roll_token(token["id"], token["name"]))

    def _on_token_form(self, result: dict | None) -> None:
        if not result:
            return
        if result["id"]:
            self._update_token(result["id"], result["body"])
        else:
            self._create_token(result["body"])

    @work(thread=True)
    def _create_token(self, body: dict) -> None:
        try:
            token = self.token_api.create_token(body)
            self.call_from_thread(self.push_screen, TokenValueModal(token.get("name", ""), token.get("value", "")))
            self.call_from_thread(self.load_tokens)
        except Exception as e:
            self.call_from_thread(self.notify, f"Failed to create token: {e}", severity="error")

    @work(thread=True)
    def _update_token(self, token_id: str, body: dict) -> None:
        try:
            self.token_api.update_token(token_id, body)
            self.call_from_thread(self.notify, "Token updated")
            self.call_from_thread(self.load_tokens)
        except Exception as e:
            self.call_from_thread(self.notify, f"Failed to update token: {e}", severity="error")

    @work(thread=True)
    def _delete_token(self, token_id: str) -> None:
        try:
            self.token_api.delete_token(token_id)
            self.call_from_thread(self.notify, "Token deleted")
            self.call_from_thread(self.load_tokens)
        except Exception as e:
            self.call_from_thread(self.notify, f"Failed to delete token: {e}", severity="error")

    def _after_roll(self, token_id: str, name: str, value: str) -> None:
        targets = self.tokens_in_use.get(token_id, [])
        # The old secret is dead now; keep this session's clients working.
        feeds = set().union(*(src.get("feeds", set()) for src in targets))
        if "api" in feeds:
            self.api.set_token(value)
        if "admin" in feeds:
            self.token_api.set_token(value)
        self.push_screen(TokenValueModal(name, value, targets, self._save_token_value))

    def _save_token_value(self, src: dict, value: str) -> str | None:
        """Write a new secret where the old one was stored. Returns an error, or None."""
        try:
            if src["kind"] == "env":
                set_key(src["path"], src["key"], value, quote_mode="never")
            else:
                with open(src["path"], "w") as f:
                    f.write(value + "\n")
        except Exception as e:
            return str(e)
        src["value"] = value
        return None

    @work(thread=True)
    def _roll_token(self, token_id: str, name: str) -> None:
        try:
            value = self.token_api.roll_token(token_id)
            self.call_from_thread(self._after_roll, token_id, name, value)
        except Exception as e:
            self.call_from_thread(self.notify, f"Failed to roll token: {e}", severity="error")



def _short(path: str) -> str:
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path.startswith(home) else path


def token_sources(dotenv_path: str, api_token: str, admin_token: str | None) -> list[dict]:
    """Every place on this machine a Cloudflare token secret is kept.

    .env keys, plus token files: CLOUDFLARE_TOKEN_FILES (comma-separated), defaulting
    to token and admin_token in the credentials config dir. The Tokens tab marks
    matching tokens and offers to save a rolled secret back to each. "feeds" says
    which of this session's clients ("api", "admin") uses that secret.
    """
    def feeds(value: str) -> set[str]:
        return {name for name, v in (("api", api_token), ("admin", admin_token)) if v and v == value}

    sources = []
    in_file = dotenv_values(dotenv_path) if dotenv_path else {}
    for key in ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_MANAGER_TOKEN", "CLOUDFLARE_ADMIN_TOKEN"):
        value = os.getenv(key)
        if not value:
            continue
        saved_in_file = key in in_file
        sources.append({
            "kind": "env", "key": key, "path": dotenv_path if saved_in_file else None, "value": value,
            "label": f"{key} in {_short(dotenv_path)}" if saved_in_file else f"{key} (environment)",
            "feeds": feeds(value),
        })
    default_files = f"{credentials.config_path('token')},{credentials.config_path('admin_token')}"
    for path in os.getenv("CLOUDFLARE_TOKEN_FILES", default_files).split(","):
        path = os.path.expanduser(path.strip())
        if not path or not os.path.isfile(path):
            continue
        try:
            with open(path) as f:
                value = f.read().strip()
        except OSError:
            continue
        if value:
            sources.append({"kind": "file", "path": path, "value": value, "label": _short(path),
                            "feeds": feeds(value)})
    return sources


def main():
    dotenv_path = find_dotenv()
    load_dotenv(dotenv_path)
    token = credentials.manager_token()
    if not token:
        print(f"Error: no token. Set CLOUDFLARE_API_TOKEN or save one to {credentials.config_path('token')}",
              file=sys.stderr)
        sys.exit(1)
    account_id = credentials.account_id()
    api = CloudflareAPI(token, account_id=account_id)
    admin = credentials.admin_token()
    token_api = CloudflareAPI(admin, account_id=account_id) if admin else None
    CFManagerApp(api, token_api, token_sources(dotenv_path, token, admin)).run()

if __name__ == "__main__":
    main()
