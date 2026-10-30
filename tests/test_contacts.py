import json

from bgb.models import Job
from bgb.sources.contacts import ContactsSource
from bgb.util import now_iso


class FakePeople:
    def __init__(self):
        self.people = [
            {"resourceName": "people/c1", "names": [{"displayName": "Ada Lovelace"}]},
            {"resourceName": "people/c2", "names": [{"displayName": "Grace Hopper"}]},
        ]
        self.deleted: list[str] = []
        self.expired = False

    def list_connections(self, user, page_token=None, sync_token=None):
        if sync_token:
            if self.expired:
                return {"expired": True, "people": [], "deleted": [], "next_page": None, "sync_token": None}
            return {
                "expired": False,
                "people": [],
                "deleted": list(self.deleted),
                "next_page": None,
                "sync_token": "s2",
            }
        return {
            "expired": False,
            "people": list(self.people),
            "deleted": [],
            "next_page": None,
            "sync_token": "s1",
        }


def test_contacts_full_then_incremental_delete():
    client = FakePeople()
    source = ContactsSource(client, ["Ada@Example.com"])
    first = source.scan(Job(id="j", name="n", created_at=now_iso()))
    assert first.scopes[0].mode == "full"
    obj = next(item for item in first.scopes[0].objects if item.path.endswith("c1.json"))
    payload = json.loads(obj.opener().read())
    assert payload["names"][0]["displayName"] == "Ada Lovelace"
    assert first.state["users"]["ada@example.com"]["sync_token"] == "s1"

    client.deleted = ["people/c2"]
    job = Job(id="j", name="n", created_at=now_iso(), source_state={"contacts": first.state})
    second = source.scan(job)
    assert second.scopes[0].mode == "incremental"
    assert second.scopes[0].deleted_ids == ["contacts:ada@example.com:people/c2"]
    assert second.scopes[0].objects == []

    client.expired = True
    third = source.scan(Job(id="j", name="n", created_at=now_iso(), source_state={"contacts": second.state}))
    assert third.scopes[0].mode == "full"
    assert third.warnings
