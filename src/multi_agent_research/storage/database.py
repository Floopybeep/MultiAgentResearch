import json
import sqlite3


class Database:
    def __init__(self, path):
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS events "
            "(sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE, body TEXT)"
        )
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS records (key TEXT PRIMARY KEY, body TEXT)"
        )

    def record(self, key, value):
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO records VALUES (?, ?)",
                (key, json.dumps(value, default=str)),
            )

    def event(self, event):
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO events(event_id, body) VALUES (?, ?)",
                (event["event_id"], json.dumps(event)),
            )
        return cursor.lastrowid

    def close(self):
        self.connection.close()
