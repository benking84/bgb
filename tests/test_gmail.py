from bgb.models import Job
from bgb.sources.gmail import GmailSource
from bgb.sources.keep import KeepSource
from bgb.util import now_iso
from tests.helpers import job, make_engine


class FakeGmail:
    def __init__(self):
        self.meta: dict[str, dict] = {}
        self.raw: dict[tuple[str, str], bytes] = {}
        self.history = {"historyId": "5", "records": []}
        self.expired = False
        self.profile_history = "1"
        self.raw_calls: list[tuple[str, str]] = []

    def get_profile(self, user: str) -> dict:
        return {"historyId": self.profile_history}

    def list_message_ids(self, user: str, page_token):
        return list(self.meta.get(user, {})), None

    def get_metadata(self, user: str, message_id: str) -> dict:
        return self.meta[user][message_id]

    def get_message(self, user: str, message_id: str) -> dict:
        self.raw_calls.append((user, message_id))
        return dict(self.meta[user][message_id], raw=self.raw[(user, message_id)])

    def list_history(self, user: str, start: str):
        if self.expired:
            return None
        return self.history


def _message(user: str, client: FakeGmail, message_id: str, raw: bytes, labels=None):
    client.meta.setdefault(user, {})[message_id] = {
        "id": message_id,
        "labelIds": labels or ["INBOX"],
        "internalDate": "1760000000000",
        "snippet": "snippet",
        "subject": f"Subject {message_id}",
    }
    client.raw[(user, message_id)] = raw


def test_full_scan_and_history_incremental():
    client = FakeGmail()
    user = "ada@example.com"
    _message(user, client, "m1", b"Subject: one\r\n\r\nhello\r\n")
    source = GmailSource(client, [user])
    first = source.scan(Job(id="j", name="n", created_at=now_iso()))
    assert first.scopes[0].mode == "full"
    obj = first.scopes[0].objects[0]
    assert obj.path == "gmail/ada@example.com/messages/m1.eml"
    assert obj.opener().read().startswith(b"Subject: one")

    job = Job(id="j", name="n", source_state={"gmail": first.state}, created_at=now_iso())
    client.profile_history = "5"
    client.history = {
        "historyId": "5",
        "records": [
            {"added": ["m2"], "deleted": [], "label_changed": []},
            {"added": [], "deleted": ["m1"], "label_changed": []},
            {"added": [], "deleted": [], "label_changed": ["m2"]},
        ],
    }
    _message(user, client, "m2", b"Subject: two\r\n\r\nthere\r\n", labels=["INBOX", "STARRED"])
    second = source.scan(job)
    scope = second.scopes[0]
    assert scope.mode == "incremental"
    assert scope.deleted_ids == ["gmail:ada@example.com:m1"]
    assert [item.source_id for item in scope.objects] == ["gmail:ada@example.com:m2"]
    # New messages carry no labels until the raw fetch, which returns them with the body.
    assert scope.objects[0].metadata == {}
    scope.objects[0].opener()
    assert scope.objects[0].metadata["labels"] == ["INBOX", "STARRED"]
    assert scope.objects[0].metadata["subject"] == "two"

    client.expired = True
    third = source.scan(Job(id="j", name="n", source_state={"gmail": second.state}, created_at=now_iso()))
    assert third.scopes[0].mode == "full"
    assert third.warnings


def test_identical_messages_dedup_and_label_change_does_not_reread(tmp_path):
    client = FakeGmail()
    user = "ada@example.com"
    body = bytes(range(96))
    _message(user, client, "m1", body)
    _message(user, client, "m2", body)
    source = GmailSource(client, [user])
    runtime, holder = make_engine(tmp_path, block_size=32, volume_size=4096, source=source)
    holder["source"] = source
    runtime.index.upsert_job(job(block_size=32, sources=["gmail"]))
    first = runtime.engine.run_backup("job1")
    assert first.stats["blocks_new"] == 3
    assert first.stats["blocks_reused"] == 3
    assert len(client.raw_calls) == 2

    saved = runtime.index.get_job("job1")
    client.profile_history = "9"
    client.history = {
        "historyId": "9",
        "records": [{"added": [], "deleted": [], "label_changed": ["m1"]}],
    }
    client.meta[user]["m1"]["labelIds"] = ["INBOX", "STARRED"]
    # The engine reads source state from the stored job. Patch history id so this is incremental.
    saved.source_state = {"gmail": {"users": {user: {"history_id": "1"}}}}
    runtime.index.upsert_job(saved)
    second = runtime.engine.run_backup("job1")
    assert second.stats["files_read"] == 0
    assert len(client.raw_calls) == 2
    fileset = runtime.index.list_filesets("job1")[0]
    entry = runtime.index.get_entry("job1", fileset.id, "gmail/ada@example.com/messages/m1.eml")
    assert "STARRED" in entry.metadata["labels"]


def test_keep_is_refused():
    from bgb.errors import UnsupportedSource

    try:
        KeepSource().scan(Job(id="j", name="n", created_at=now_iso()))
    except UnsupportedSource as exc:
        assert "Keep" in str(exc)
    else:
        raise AssertionError("Keep should not scan")
