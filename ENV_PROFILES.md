# Environment profiles

On each mini-PC, use alarm_sound_SB11.bat or alarm_sound_SB12.bat as appropriate.
The launcher sets ALARM_SOUND_ENV_FILE to the absolute config/.env.sb11 or
config/.env.sb12 path and starts the shared alarm_sound_v11.py once.
Both profiles use MP3_FOLDER=C:\Alarm and the existing shared reload node.
Local profiles are private and excluded from Git. Create them on the deployment
host using config/.env.example and supply the correct LINE_NAME, OPC endpoint,
MP3_FOLDER and SQL connection settings securely. Never commit populated profiles.

Profiles use canonical LINE_NAME. Blank/unset LINE_NAME falls back to deprecated
LINE_ID at configuration load only. Runtime status exposes line_name; mapping SQL
uses Alarm_Lists.LineName and validates the matching TagMaster.LineName/path.
History inserts write Alarm_History.LineName only. Apply the canonical migration
before running this version in scoped mode. Copied TagIds must be remapped after
TagMaster is populated; the stricter mapping join excludes unresolved identities.
No configured name retains legacy unscoped SQL, without requiring migration.

Profile keys override inherited values. Explicit selection never merges the
legacy .env and fails if the file is missing. With the selector unset,
config/.env and the existing environment precedence continue to work unchanged.
The legacy launcher remains untouched. Use a fresh process for each profile.

See ../OpcTagManager/ENV_PROFILES.md for the full deployment notes and offline
verification. Follow ../OpcTagManager/MULTI_LINE_DEPLOYMENT.md for the coordinated
SB12-first deployment and later optional cleanup of legacy SQL columns.
