"""
Data Engine — SQL dump acquisition, anonymization, test DB provisioning.

Flow per run:
  1. dump_source()       → source_dump.sql  (from live source DB or supplied file)
  2. import to staging   → testctl_staging_<run_id>
  3. anonymize in place  → deterministic scrambling per anonymization.yaml rules
  4. export anonymized   → anonymized_dump.sql  (sha256-hashed for audit)
  5. create test DB      → testctl_run_<run_id>
  6. import anonymized   → ready to test
  7. drop staging DB

All deterministic mappings use HMAC-SHA256(seed + key + original) so that
the same original value always produces the same anonymized value within a
single run (preserving referential integrity across tables).
"""

import hashlib
import re
import subprocess
from pathlib import Path
from typing import Optional

import yaml


class DataEngine:
    def __init__(self, config_path: Path, db_config: dict, anon_config_path: Path):
        self.config_path = config_path
        self.db_config = db_config
        with open(anon_config_path) as f:
            self.anon_config = yaml.safe_load(f)
        self.seed: str = self.anon_config.get("seed", "testctl-default-seed")
        self._maps: dict[str, dict[str, str]] = {}

    # ── public API ──────────────────────────────────────────────────────

    def provision(self, run_id: str, source_dump: Optional[Path] = None) -> tuple[str, str]:
        """Provision a fresh anonymized test DB. Returns (db_name, anon_hash)."""
        run_dir = self.config_path / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        staging_db = f"testctl_staging_{run_id}"
        test_db = f"testctl_run_{run_id}"

        dump_path = source_dump or self._dump_source(run_dir)

        self._create_db(staging_db)
        self._import_dump(staging_db, dump_path)
        self._run_anonymization(staging_db)

        anon_path = run_dir / "anonymized_dump.sql"
        self._export_dump(staging_db, anon_path)
        self._drop_db(staging_db)

        anon_hash = hashlib.sha256(anon_path.read_bytes()).hexdigest()

        self._create_db(test_db)
        self._import_dump(test_db, anon_path)

        return test_db, anon_hash

    def destroy(self, test_db: str) -> None:
        self._drop_db(test_db)

    # ── DB helpers ──────────────────────────────────────────────────────

    def _client_args(self, db: Optional[str] = None) -> list[str]:
        args = [
            f"--host={self.db_config['host']}",
            f"--port={self.db_config.get('port', 3306)}",
            f"--user={self.db_config['user']}",
            f"--password={self.db_config['password']}",
        ]
        if db:
            args.append(db)
        return args

    def _create_db(self, name: str) -> None:
        subprocess.run(
            ["mariadb"] + self._client_args() + [
                "-e", f"CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci",
            ],
            check=True, capture_output=True,
        )

    def _drop_db(self, name: str) -> None:
        subprocess.run(
            ["mariadb"] + self._client_args() + ["-e", f"DROP DATABASE IF EXISTS `{name}`"],
            check=True, capture_output=True,
        )

    def _dump_source(self, run_dir: Path) -> Path:
        out = run_dir / "source_dump.sql"
        with open(out, "w") as f:
            subprocess.run(
                ["mariadb-dump"] + self._client_args() + [
                    "--single-transaction", "--routines", self.db_config["name"],
                ],
                stdout=f, check=True,
            )
        return out

    def _import_dump(self, db: str, dump_path: Path) -> None:
        with open(dump_path) as f:
            subprocess.run(
                ["mariadb"] + self._client_args(db),
                stdin=f, check=True, capture_output=True,
            )

    def _export_dump(self, db: str, out_path: Path) -> None:
        with open(out_path, "w") as f:
            subprocess.run(
                ["mariadb-dump"] + self._client_args() + ["--single-transaction", db],
                stdout=f, check=True,
            )

    # ── anonymization ───────────────────────────────────────────────────

    def _run_anonymization(self, db: str) -> None:
        import mariadb as mdb
        conn = mdb.connect(
            host=self.db_config["host"],
            port=int(self.db_config.get("port", 3306)),
            user=self.db_config["user"],
            password=self.db_config["password"],
            database=db,
        )
        try:
            for rule in self.anon_config.get("rules", []):
                table = rule["table"]
                for field_name, field_cfg in rule.get("fields", {}).items():
                    self._anonymize_field(conn, table, field_name, field_cfg)
            conn.commit()
        finally:
            conn.close()

    def _anonymize_field(self, conn, table: str, field: str, cfg: dict) -> None:
        strategy = cfg["strategy"]
        cur = conn.cursor()

        if strategy == "constant":
            cur.execute(f"UPDATE `{table}` SET `{field}` = ?", (cfg["value"],))

        elif strategy == "suppress":
            cur.execute(f"UPDATE `{table}` SET `{field}` = NULL")

        elif strategy in ("deterministic_name", "deterministic_prefix"):
            prefix = cfg.get("prefix", "Item")
            cur.execute(f"SELECT id, `{field}` FROM `{table}`")
            for row_id, original in cur.fetchall():
                if original:
                    mapped = self._det_map(table, field, str(original), prefix)
                    conn.cursor().execute(
                        f"UPDATE `{table}` SET `{field}` = ? WHERE id = ?", (mapped, row_id)
                    )

        elif strategy == "deterministic_email":
            domain = cfg.get("domain", "example.test")
            cur.execute(f"SELECT id, `{field}` FROM `{table}`")
            for row_id, original in cur.fetchall():
                if original:
                    local = self._det_map(table, field, str(original), "user").lower()
                    conn.cursor().execute(
                        f"UPDATE `{table}` SET `{field}` = ? WHERE id = ?",
                        (f"{local}@{domain}", row_id),
                    )

        elif strategy == "sequential":
            prefix = cfg.get("prefix", "Item")
            cur.execute(f"SELECT id FROM `{table}` ORDER BY id")
            for i, (row_id,) in enumerate(cur.fetchall(), 1):
                conn.cursor().execute(
                    f"UPDATE `{table}` SET `{field}` = ? WHERE id = ?", (f"{prefix} {i}", row_id)
                )

        elif strategy == "numeric_range":
            lo, hi = cfg.get("min", 0), cfg.get("max", 100000)
            decimal_places = int(cfg.get("decimal_places", 0))
            scale = 10 ** decimal_places
            lo_int = int(round(lo * scale))
            hi_int = int(round(hi * scale))
            cur.execute(f"SELECT id, `{field}` FROM `{table}`")
            for row_id, original in cur.fetchall():
                if original is not None:
                    h = int(hashlib.sha256(
                        f"{self.seed}:{table}:{field}:{original}".encode()
                    ).hexdigest(), 16)
                    raw = lo_int + h % (hi_int - lo_int)
                    value = round(raw / scale, decimal_places) if decimal_places > 0 else raw
                    conn.cursor().execute(
                        f"UPDATE `{table}` SET `{field}` = ? WHERE id = ?",
                        (value, row_id),
                    )

        elif strategy == "preserve_format":
            # Scramble digits, keep non-digit chars (e.g. INV-2026-001 → INV-8312-647)
            cur.execute(f"SELECT id, `{field}` FROM `{table}`")
            for row_id, original in cur.fetchall():
                if not original:
                    continue
                idx = 0

                def _next_digit(m: re.Match) -> str:
                    nonlocal idx
                    h = int(hashlib.sha256(
                        f"{self.seed}:{idx}:{original}".encode()
                    ).hexdigest(), 16)
                    idx += 1
                    return str(h % 10)

                scrambled = re.sub(r"\d", _next_digit, str(original))
                conn.cursor().execute(
                    f"UPDATE `{table}` SET `{field}` = ? WHERE id = ?", (scrambled, row_id)
                )

        elif strategy == "fake_iban":
            cur.execute(f"UPDATE `{table}` SET `{field}` = 'CH5604835012345678009'")

        elif strategy == "fake_phone":
            cur.execute(f"UPDATE `{table}` SET `{field}` = '+41000000000'")

    def _det_map(self, table: str, field: str, original: str, prefix: str) -> str:
        """Return the same anonymized value for the same original within this run."""
        key = f"{table}:{field}"
        if key not in self._maps:
            self._maps[key] = {}
        if original not in self._maps[key]:
            h = int(hashlib.sha256(
                f"{self.seed}:{key}:{original}".encode()
            ).hexdigest(), 16)
            self._maps[key][original] = f"{prefix}_{h % 9000 + 1000}"
        return self._maps[key][original]
