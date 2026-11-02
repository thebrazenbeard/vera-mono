# Local historical export inventory (source-only)

The separate `ingest.export_inventory_cli` command enumerates a bounded directory and
produces a JSON **local-only, read-only** review manifest. It is deliberately
separate from the `ingest file` pipeline: it does not ingest, persist, publish,
normalize, grant rights, or approve any source. No configured store directory
is created.

Example using a **synthetic test directory**:

```console
PYTHONPATH=packages/vera_ingest/src python -m ingest.export_inventory_cli ./synthetic-exports
```

Default mode lists file extension, size and a temporary local ordinal, but
redacts names and root path, never opens file payloads, and does not inspect
archives. Every record is marked `UNREVIEWED` privacy,
`UNVERIFIED` data rights and `NOT_GRANTED` admission.

Local operators can explicitly request bounded local byte inspection:

```console
PYTHONPATH=packages/vera_ingest/src python -m ingest.export_inventory_cli ./synthetic-exports \
  --hash-local --inspect-zip-local --max-read-bytes 1048576
```

Identical SHA-256 digests receive a `duplicate_of` link. ZIP inspection reads
only the archive central directory. It **does not extract or execute** any
member. It rejects traversal/absolute/drive-letter paths, symlinks, encryption,
very large declared uncompressed sizes, high compression ratios, members with
common nested-archive/container suffixes and member count overflow. This is
**suffix-based screening, not a guarantee that disguised nested archives are
absent**. ZIP inputs have an absolute 2 MiB limit even
when the caller asks for a larger general file-byte cap. Known Windows
offline/reparse/recall placeholders and reparse roots are skipped/rejected
before any opted-in file read; large files are skipped rather than downloaded.
The size cap and metadata guards do not replace an OS-level sandbox when
untrusted software can race/change files during the inspection.

`--include-names` is an explicit **local-only** option. Even redacted
manifests may contain identifying file sizes and content hashes. Keep all
actual inventory output private until an independent privacy review and
repository-specific rights, provenance and licensing review are complete.
Historical files must never be treated as current installed Project
instructions or a GPU/data-rights grant merely because they were found.

The command intentionally offers no `--upload`, `--apply`, `--delete`,
training-data admission or publication path. Promotion to a destination
repository is a separate reviewed change against its current source and tests.
