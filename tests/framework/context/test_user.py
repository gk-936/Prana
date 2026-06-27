# tests/framework/context/test_user.py
from framework.context.user import UserContext


def test_minimal_user_defaults():
    u = UserContext(user_id="u1")
    assert u.role == "user" and u.locale == "en" and u.timezone == "UTC"
    assert u.permissions == frozenset()


def test_has_permission_explicit():
    u = UserContext(user_id="u1", permissions=frozenset({"read_orders"}))
    assert u.has_permission("read_orders")
    assert not u.has_permission("delete_users")


def test_admin_has_all_permissions():
    u = UserContext(user_id="a1", role="admin")
    assert u.has_permission("anything")


def test_metadata_holds_app_fields():
    u = UserContext(user_id="u1", metadata={"lat": 13.08, "lon": 80.27})
    assert u.metadata["lat"] == 13.08
