from datetime import datetime
from pathlib import Path
import sqlite3

from aw_core import Event
from aw_client import ActivityWatchClient


def main() -> None:
    dbfile = _get_db_path()
    print(f"Reading from database file at {dbfile}")
    conn = sqlite3.connect(_get_db_path())
    conn.execute("pragma journal_mode=wal;")
    cur = conn.cursor()
    devices = get_devices(cur)

    for index, device in enumerate(devices):
        events = get_events_for_device(device[0], cur)
        print(
            f"{index + 1} / {len(devices)} Sending {len(events)} events to ActivityWatch for device {device[0]} - {device[1]}"
        )
        if len(events) > 0:
            send_to_activitywatch(events, device)


def get_devices(database_connection):
    query = """
    SELECT
      DISTINCT(ZSOURCE.ZDEVICEID) as deviceId,
	  ZSYNCPEER.ZMODEL as deviceModel
    FROM
      ZSOURCE
	  LEFT JOIN
		ZSYNCPEER
		ON ZSYNCPEER.ZDEVICEID = ZSOURCE.ZDEVICEID
    """
    return list(database_connection.execute(query))


def get_events_for_device(device, database_connection):
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
      AND 
      device = ?
  """
    rows = list(database_connection.execute(query, (device,)))
    # TODO: Handle timezone. Maybe not needed if everything is in UTC anyway?
    return [
        Event(
            timestamp=row[4],
            duration=datetime.fromisoformat(row[5]) - datetime.fromisoformat(row[4]),
            data={"app": row[0], "category": row[-1]},
        )
        for row in rows
    ]


def send_to_activitywatch(events, device):
    hostname = f"ios-{device[0]}-{device[1]}"
    # NOTE: 'aw-watcher-android' string is only there for aw-webui to detect it as a mobile device
    bucket = f"aw-watcher-android_aw-import-screentime_{hostname}"

    aw = ActivityWatchClient(client_name="aw-import-screentime")
    aw.client_hostname = hostname
    aw.create_bucket(bucket, "currentwindow")
    aw.send_events(bucket, events)


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
