import sqlite3
from datetime import datetime
from pathlib import Path

from aw_client import ActivityWatchClient
from aw_core import Event


def main() -> None:
    dbfile = _get_db_path()
    print(f"Reading from database file at {dbfile}")
    conn = sqlite3.connect(_get_db_path())
    conn.execute("pragma journal_mode=wal;")
    devices = get_devices(conn)
    print(f"Found devices: {devices}")

    print("Running for this device")
    events = get_events_for_this_device(conn)

    for index, device in enumerate(devices):
        device_id, device_name = device
        events = get_events_for_device(conn, device_id)
        print(
            f"{index + 1} / {len(devices)} Sending {len(events)} events to ActivityWatch for device {device_id}"
        )
        if len(events) > 0:
            send_to_activitywatch(events, device)


r"""
To explore the knowledgeC.db database, use the following command:

$ sqlite3 ~/Library/Application\ Support/Knowledge/knowledgeC.db
sqlite> .tables

# Now, to see the table structure:
sqlite> .schema ZOBJECT

# To see the data:
sqlite> SELECT * FROM ZOBJECT LIMIT 10;
"""


def get_devices(conn):
    # Returns a list of tuples (device_id, device_name)
    # FIXME: This doesn't seem to work, maybe only returns iOS devices?
    #        I don't have any iOS devices to test with.
    #        Possible fix is to use ZSOURCE.ZDEVICEID instead of ZSYNCPEER.ZDEVICEID
    query = """
        SELECT
            ZSYNCPEER.ZDEVICEID as deviceId,
            ZSYNCPEER.ZMODEL as deviceModel
        FROM
            ZSYNCPEER
    """
    return list(conn.execute(query))


def get_events_for_this_device(conn):
    # Retrieve events for this device (not synced events)
    # Done by querying for events without ZDEVICEID set.
    query = """
        SELECT
          ZOBJECT.ZVALUESTRING AS "app",
            (ZOBJECT.ZENDDATE - ZOBJECT.ZSTARTDATE) AS "usage",
            ZOBJECT.ZSECONDSFROMGMT/3600 AS "tz",
            DATETIME(ZOBJECT.ZSTARTDATE + 978307200, \'UNIXEPOCH\') as "start_time",
            DATETIME(ZOBJECT.ZENDDATE + 978307200, \'UNIXEPOCH\') as "end_time",
            DATETIME(ZOBJECT.ZCREATIONDATE + 978307200, \'UNIXEPOCH\') as "created_at",
            ZSOURCE.ZDEVICEID AS "device"
          FROM
            ZOBJECT
            LEFT JOIN
              ZSTRUCTUREDMETADATA
            ON ZOBJECT.ZSTRUCTUREDMETADATA = ZSTRUCTUREDMETADATA.Z_PK
            LEFT JOIN
              ZSOURCE
            ON ZOBJECT.ZSOURCE = ZSOURCE.Z_PK
          WHERE
            ZSTREAMNAME = "/app/usage"
    """
    rows = list(conn.execute(query, ()))

    # Check for events with ZDEVICEID set, should be empty (unless you have an iOS device and the query doesn't handle it)
    assert all(row[-1] is None for row in rows)

    # Debug print 10 longest events
    for row in sorted(rows, key=lambda r: -r[1])[:10]:
        print(row)


def get_events_for_device(conn, device_id):
    query = """
        SELECT
          ZOBJECT.ZVALUESTRING AS "app",
            (ZOBJECT.ZENDDATE - ZOBJECT.ZSTARTDATE) AS "usage",
            ZOBJECT.ZSECONDSFROMGMT/3600 AS "tz",
            DATETIME(ZOBJECT.ZSTARTDATE + 978307200, \'UNIXEPOCH\') as "start_time",
            DATETIME(ZOBJECT.ZENDDATE + 978307200, \'UNIXEPOCH\') as "end_time",
            DATETIME(ZOBJECT.ZCREATIONDATE + 978307200, \'UNIXEPOCH\') as "created_at",
            CASE ZMODEL
              WHEN ZMODEL THEN ZMODEL
              ELSE "Other"
            END "source",
            ZSOURCE.ZDEVICEID AS "device"
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
            AND ZSOURCE.ZDEVICEID = ?
    """
    rows = list(conn.execute(query, (device_id,)))
    for row in rows[:10]:
        print(row)
    # TODO: Handle timezone. Maybe not needed if everything is in UTC anyway?
    return [
        Event(
            timestamp=row[4],
            duration=datetime.fromisoformat(row[5]) - datetime.fromisoformat(row[4]),
            data={"app": row[0], "category": row[-1]},
        )
        for row in rows
    ]


def send_to_activitywatch(events, device_id):
    hostname = f"ios-{device_id}"
    # NOTE: 'aw-watcher-android' string is only there for aw-webui to detect it as a mobile device
    bucket = f"aw-watcher-android_aw-import-screentime_{hostname}"

    aw = ActivityWatchClient(client_name="aw-import-screentime")
    aw.client_hostname = hostname
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
