from datetime import datetime
import sqlite3

from aw_core import Event

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
    DATABASE_PATH = "/home/erb/tmp/sync-with-vm-host/Knowledge/knowledgeC.db"
    con = sqlite3.connect(DATABASE_PATH)
    cur = con.cursor()

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
    for e, r in zip(events, rows):
        print(e.timestamp)
        print(f" - duration: {e.duration}")
        print(f" - data: {e.data}")
        print(f" - raw row: {r}")


if __name__ == "__main__":
    main()
