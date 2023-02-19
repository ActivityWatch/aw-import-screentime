from datetime import datetime
from pathlib import Path
import sqlite3

from aw_core import Event
from aw_client import ActivityWatchClient


query = """
SELECT
  ZOBJECT.ZVALUESTRING AS "app",
    (ZOBJECT.ZENDDATE - ZOBJECT.ZSTARTDATE) AS "usage",
    CASE ZOBJECT.ZSTARTDAYOFWEEK
      WHEN "1" THEN "Sunday"
      WHEN "2" THEN "Monday"
      WHEN "3" THEN "Tuesday"
      WHEN "4" THEN "Wednesday"
      WHEN "5" THEN "Thursday"
      WHEN "6" THEN "Friday"
      WHEN "7" THEN "Saturday"
    END "dow",
    ZOBJECT.ZSECONDSFROMGMT/3600 AS "tz",
    DATETIME(ZOBJECT.ZSTARTDATE + 978307200, \'UNIXEPOCH\') as "start_time",
    DATETIME(ZOBJECT.ZENDDATE + 978307200, \'UNIXEPOCH\') as "end_time",
    DATETIME(ZOBJECT.ZCREATIONDATE + 978307200, \'UNIXEPOCH\') as "created_at",
    CASE ZMODEL
      WHEN ZMODEL THEN ZMODEL
      ELSE "Other"
    END "source"
  FROM
    ZOBJECT
    LEFT JOIN
      ZSTRUCTUREDMETADATA
    ON ZOBJECT.ZSTRUCTUREDMETADATA = ZSTRUCTUREDMETADATA.Z_PK
    LEFT JOIN
      ZSOURCE
    ON ZOBJECT.ZSOURCE = ZSOURCE.Z_PK
    LEFT JOIN
      ZSYNCPEER
    ON ZSOURCE.ZDEVICEID = ZSYNCPEER.ZDEVICEID
  WHERE
    ZSTREAMNAME = "/app/usage"
"""


def main() -> None:
    dbfile = _get_db_path()
    print(f"Reading from database file at {dbfile}")

    # Open the database
    conn = sqlite3.connect(_get_db_path())

    # Set journal mode to WAL.
    conn.execute("pragma journal_mode=wal;")

    cur = conn.cursor()

    rows = list(cur.execute(query))
    # TODO: Handle timezone. Maybe not needed if everything is in UTC anyway?
    events = [
        Event(
            timestamp=row[4],
            duration=datetime.fromisoformat(row[5]) - datetime.fromisoformat(row[4]),
            data={"app": row[0], "category": row[-1]},
        )
        for row in rows
    ]

    # for e, r in zip(events, rows):
    #     print(e.timestamp)
    #     print(f" - duration: {e.duration}")
    #     print(f" - data: {e.data}")
    #     print(f" - raw row: {r}")

    send_to_activitywatch(events)


def send_to_activitywatch(events):
    print("Sending events to ActivityWatch...")

    hostname = "macos-screentime-test"

    # NOTE: 'aw-watcher-android' string is only there for aw-webui to detect it as a mobile device
    bucket = f"aw-watcher-android_aw-import-screentime_{hostname}"

    aw = ActivityWatchClient(client_name="aw-import-screentime")
    aw.client_hostname = hostname

    # buckets = aw.get_buckets()
    # if bucket in buckets.keys():
    #     ans = input("Bucket already found, overwrite? (y/N): ")
    #     if ans == "y":
    #         aw.delete_bucket(bucket, force=True)

    aw.create_bucket(bucket, "currentwindow")
    aw.insert_events(bucket, events)


def _get_db_path():
    path_test = Path("~/tmp/sync-with-vm-host/Knowledge/knowledgeC.db").expanduser()
    path_prod = Path(
        "~/Library/Application Support/Knowledge/knowledgeC.db"
    ).expanduser()

    path = path_test if path_test.exists() else path_prod
    assert path.exists(), "couldn't find database file"
    return path


if __name__ == "__main__":
    main()
