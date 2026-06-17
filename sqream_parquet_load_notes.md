Parquet staging is ready in `staging/`.

Use this when you have a path visible to the worker selected by SQream `server_picker`.
The current connection target is the picker endpoint, not a direct worker endpoint.

1. Generate staging parquet:

```bash
python3 load_features_to_sqream.py --limit 300 --batch-size 100 --load-mode stage-only-parquet
```

2. Copy the parquet files to a SQream-visible path.

Examples:
- NFS mount visible to picker-selected workers
- Shared cluster filesystem
- A path under the server's shared data mount

3. Replace placeholders in [sqream_parquet_load_template.sql](/home/ospadmin/workspaces/remoteagent/cc6mog23/sqream_parquet_load_template.sql).

Placeholders:
- `{{FEATURES_PARQUET_PATH}}`
- `{{EVENTS_PARQUET_PATH}}`

4. Run the SQL with the SQream CLI:

```bash
/SQREAM/sqream-db-v4.4.0/bin/sqream sql \
  --host 192.168.0.26 \
  --port 3108 \
  --database master \
  --username sqream \
  --password sqream \
  --clustered=true \
  --service sqream \
  --file sqream_parquet_load_template.sql \
  --results-only=true
```

Current finding:
- Local WSL path `/home/ospadmin/.../staging` is not usable for SQream workers selected through `192.168.0.26:3108`
- The SQL path is ready; only the shared parquet location is missing

Connection model confirmed from local SQream scripts:
- `metadata_server`: `192.168.0.26:3105`
- `server_picker`: `192.168.0.26:3108`
- `sqreamd` workers: `192.168.0.26:5000`, `192.168.0.26:5001`
- Client scripts should use `3108` with `--clustered=true --service sqream`
