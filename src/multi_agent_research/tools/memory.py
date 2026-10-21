class PlanMemory:
    def __init__(self, db, artifacts):
        self.db, self.artifacts = db, artifacts
        row = db.connection.execute("SELECT body FROM records WHERE key='plan'").fetchone()
        import json

        self.ref = json.loads(row[0])["artifact_ref"] if row else None

    def write(self, plan):
        self.ref = self.artifacts.put({"plan": plan})
        self.db.record("plan", {"artifact_ref": self.ref})
        return {"plan_ref": self.ref}

    def read(self):
        return self.artifacts.get(self.ref) if self.ref else {"plan": None}
