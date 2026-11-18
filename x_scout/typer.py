"""Server side of the "type" button. The typing itself happens in the owner's own Chrome (main X account) through the
extension in `extension/`: the button stores the draft here and opens the post in a new tab next to x-scout; the
extension takes the draft, types it into the reply box one key at a time and reports back. The owner reads it and
presses Reply himself: nothing clicks Reply or Post. The scout's browser profile is another X account and is never used
for writing.

Flow: POST /api/type (draft) → extension GET /api/type/next/{id} → status updates POST /api/type/status →
Reply click POST /api/type/sent → `sent` table, card ticked.
"""
from . import db

STATUSES = ("queued", "typing", "waiting", "sent", "already", "error")


class Typer:
    def __init__(self):
        self.pending = {}  # post id → item waiting for its tab
        self.state = {"status": "idle"}

    def queue(self, item):
        self.pending[item["id"]] = item
        self.state = {"status": "queued", "id": item["id"], "key": item.get("key")}

    def take(self, post_id):
        """The extension asks for the draft of the post its tab opened. → item or None."""
        return self.pending.get(post_id)

    def report(self, post_id, status, typed=None, error=None):
        if status not in STATUSES:
            return
        it = self.pending.get(post_id) or {}
        self.state = {"status": status, "id": post_id, "key": it.get("key")}
        if typed is not None:
            self.state["typed"] = typed
            self.state["exact"] = typed.strip() == (it.get("draft") or "").strip()
        if error:
            self.state["error"] = str(error)[:200]
        if status == "already" and it:
            db.log_sent(it["run_id"], it, None, "already")
            if it.get("key"):
                db.set_check(it["run_id"], it["key"], True)
            self.pending.pop(post_id, None)

    def sent(self, post_id, text):
        it = self.pending.pop(post_id, None)
        if not it:
            return False
        db.log_sent(it["run_id"], it, text, "sent")
        if it.get("key"):
            db.set_check(it["run_id"], it["key"], True)
        self.state = {"status": "sent", "id": post_id, "key": it.get("key")}
        return True


typer = Typer()
