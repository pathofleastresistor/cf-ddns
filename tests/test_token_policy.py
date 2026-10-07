import token_policy as tp

ACCT = "acct123"
ZONE_ID = "zone456"
ALL_ZONES_IN_ACCT = {f"{tp.ACCOUNT}.{ACCT}": {f"{tp.ZONE}.*": "*"}}


def test_flatten_splits_resources_and_groups():
    policies = [{
        "effect": "allow",
        "resources": {f"{tp.ZONE}.a": "*", f"{tp.ZONE}.b": "*"},
        "permission_groups": [{"id": "g1", "name": "Zone Read"}, {"id": "g2", "name": "DNS Write"}],
    }]
    rows = tp.flatten(policies)
    assert len(rows) == 4
    assert {"effect": "allow", "group_id": "g2", "group_name": "DNS Write",
            "resource": {f"{tp.ZONE}.b": "*"}} in rows


def test_build_groups_by_effect_and_resource():
    rows = [
        {"effect": "allow", "group_id": "g1", "group_name": "x", "resource": ALL_ZONES_IN_ACCT},
        {"effect": "allow", "group_id": "g2", "group_name": "y", "resource": ALL_ZONES_IN_ACCT},
        {"effect": "allow", "group_id": "g2", "group_name": "y", "resource": ALL_ZONES_IN_ACCT},
        {"effect": "deny", "group_id": "g2", "group_name": "y", "resource": {f"{tp.ZONE}.z": "*"}},
    ]
    policies = tp.build(rows)
    assert policies == [
        {"effect": "allow", "resources": ALL_ZONES_IN_ACCT, "permission_groups": [{"id": "g1"}, {"id": "g2"}]},
        {"effect": "deny", "resources": {f"{tp.ZONE}.z": "*"}, "permission_groups": [{"id": "g2"}]},
    ]


def test_build_flatten_round_trip_keeps_access():
    policies = [{
        "effect": "allow",
        "resources": {f"{tp.ZONE}.a": "*", f"{tp.ZONE}.b": "*"},
        "permission_groups": [{"id": "g1"}],
    }]
    pairs = lambda ps: {(r["group_id"], next(iter(r["resource"]))) for r in tp.flatten(ps)}
    assert pairs(tp.build(tp.flatten(policies))) == pairs(policies)


def test_describe():
    names = {ZONE_ID: "example.com"}
    assert tp.describe({f"{tp.ZONE}.{ZONE_ID}": "*"}, names) == "Zone example.com"
    assert tp.describe({f"{tp.ZONE}.*": "*"}) == "All zones (all accounts)"
    assert tp.describe(ALL_ZONES_IN_ACCT, account_id=ACCT) == "All zones in this account"
    assert tp.describe({f"{tp.ACCOUNT}.{ACCT}": "*"}, account_id=ACCT) == "This account"
    assert tp.describe({f"{tp.ACCOUNT}.*": "*"}) == "All accounts"
    assert tp.describe({f"{tp.R2_BUCKET}.{ACCT}_default_my-bucket": "*"}) == "R2 bucket my-bucket"
    assert tp.describe({f"{tp.R2_BUCKET}.{ACCT}_eu_b": "*"}) == "R2 bucket b (eu)"
    assert tp.describe({f"{tp.USER}.u1": "*"}) == "User (you)"


def test_resource_choices_for_zone_scope():
    zones = [{"id": ZONE_ID, "name": "example.com"}]
    choices = tp.resource_choices([tp.ZONE], zones, ACCT, None, [])
    assert choices[0] == ("All zones in this account", ALL_ZONES_IN_ACCT)
    assert ("Zone example.com", {f"{tp.ZONE}.{ZONE_ID}": "*"}) in choices


def test_resource_choices_user_scope_needs_tag():
    assert tp.resource_choices([tp.USER], [], ACCT, None, []) == []
    assert tp.resource_choices([tp.USER], [], ACCT, "u1", []) == [("User (you)", {f"{tp.USER}.u1": "*"})]


def test_find_user_tag():
    tokens = [{"policies": [{"effect": "allow", "resources": {f"{tp.USER}.u1": "*"},
                             "permission_groups": [{"id": "g"}]}]}]
    assert tp.find_user_tag(tokens) == "u1"
    assert tp.find_user_tag([]) is None


def test_to_expiry():
    assert tp.to_expiry("") is None
    assert tp.to_expiry("2026-12-31") == "2026-12-31T00:00:00Z"
    assert tp.to_expiry("2026-12-31T05:00:00Z") == "2026-12-31T05:00:00Z"


def test_ip_condition_sets_and_clears_allow_list():
    assert tp.ip_condition(None, "1.2.3.4, 10.0.0.0/8") == {"request.ip": {"in": ["1.2.3.4", "10.0.0.0/8"]}}
    assert tp.ip_condition({"request.ip": {"in": ["1.2.3.4"]}}, "") == {}
    kept = tp.ip_condition({"request.ip": {"in": ["1.2.3.4"], "not_in": ["5.6.7.8"]}}, "")
    assert kept == {"request.ip": {"not_in": ["5.6.7.8"]}}
