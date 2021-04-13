aw-import-screentime
====================

**NOTE:** This is a work in progress.

Import data from Apple's Screen Time to ActivityWatch. This could potentially be used to retrieve the Screen Time data of both macOS and iOS devices.

Based on analysis of the `Knowledge.db` file done here: https://www.r-bloggers.com/2019/10/spelunking-macos-screentime-app-usage-with-r/


## Usage

Requirements:

 - Python 3.7+
 - Poetry

Install dependencies with: `poetry install`

Run script with: `poetry run python3 main.py`


## Limitations of Knowledge.db

 - How far back does the history go?
   - On my VM it goes to 2020-02-01 (~2.5mo back), but I've definitely used the machine before that.
 - How often does the db file update?
   - I can't seem to retrieve the latest entries, maybe they are stuck in WAL?
