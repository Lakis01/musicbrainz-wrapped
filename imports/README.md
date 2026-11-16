# ListenBrainz Data Import Folder

Drop your ListenBrainz data export right here—either:

1. **The downloaded `.zip` or `.tar.gz` archive** directly from ListenBrainz, **or**
2. **The extracted export folder** (e.g. `listenbrainz_YourName_1794214563/` containing `listens/` and `user.json`).

## How to Export Your Listens from ListenBrainz

1. Log in at **https://listenbrainz.org/settings/export/** (or click your profile icon → **Settings** → **Export**).
2. Under **Export your listens**, click **Export listens**.
3. Wait a short moment for ListenBrainz to package your listening history, then download the `.zip` archive.
4. Either:
   - Place the `.zip` (or extracted folder) inside this `imports/` directory and click **Sync / Select Folder** in the web app, **or**
   - Upload the `.zip` directly from the **Data Source** dialog in the web UI, **or**
   - Point the CLI directly to your folder: `python3 visualize.py --sync --data-dir "/path/to/listenbrainz_export"`

*(Note: Archives and listening databases in this folder are ignored by `.gitignore` so your personal listening history is never committed to Git.)*
