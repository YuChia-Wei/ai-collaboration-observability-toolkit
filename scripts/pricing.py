"""Validate, archive and render deployable Prometheus rate cards."""
from __future__ import annotations

from contextlib import contextmanager
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

import yaml

from scripts import session_usage as usage

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "config/pricing/public-2026-10-07.json"
RULES = ROOT / "config/prometheus/rules"
API_RECORD = "ai_agent_active_token_price_usd_per_million"
CREDIT_RECORD = "ai_agent_active_token_credit_per_million"
INFO = "ai_agent_rate_card_info"
CLASSES = {"input_uncached", "input_cached", "input_cache_write", "output"}


def validate_card(card: dict) -> None:
    if (not isinstance(card, dict)
            or set(card) != {"schema_version", "version", "api_usd", "codex_credits", "credits_official_effective_from"}
            or card["schema_version"] != "ai-agent-rate-card/v1"
            or not isinstance(card["version"], str)
            or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", card["version"])):
        raise ValueError("invalid deployment rate card")
    api = card["api_usd"]
    if (not isinstance(api, dict)
            or set(api) != {"version", "verified_on", "source", "scope", "unit", "official_effective_from", "models"}
            or not isinstance(api["version"], str)
            or not re.fullmatch(r"openai-api-[0-9]{4}-[0-9]{2}-[0-9]{2}(-r[1-9][0-9]*)?", api["version"])
            or api["unit"] != "USD_per_million_tokens" or api["scope"] != "base_standard_context"
            or api["source"] != "https://developers.openai.com/api/docs/models/"
            or not isinstance(api["models"], dict)):
        raise ValueError("invalid API rate card")
    if not isinstance(api["verified_on"], str):
        raise ValueError("missing API verification date")
    dt.date.fromisoformat(api["verified_on"])
    for date in (card["credits_official_effective_from"], api["official_effective_from"]):
        if date is not None:
            if not isinstance(date, str):
                raise ValueError("invalid official effective date")
            dt.date.fromisoformat(date)
    for name, rates in api["models"].items():
        if (usage.normalize_model(name) == "unmapped" or not isinstance(rates, dict)
                or not rates or not rates.keys() <= CLASSES):
            raise ValueError("invalid API rate row")
        for value in rates.values():
            usage._decimal(value)
    credits = usage._validate_card(card["codex_credits"])
    if credits.get("operation_policy") != usage.load_rate_card()["operation_policy"]:
        raise ValueError("unsupported operation pricing policy for online estimates")


def load(path: Path) -> dict:
    card = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=usage.unique_keys)
    validate_card(card)
    return card


def price_rules(card: dict) -> dict:
    # Keep pricing joins, policy exemptions and the historical v2 contract owned by the engine.
    group = yaml.safe_load((RULES / "ai-agent-interval-cost.yml").read_text(encoding="utf-8"))["groups"][0]
    calculations = [r for r in group["rules"] if r["record"] not in (API_RECORD, CREDIT_RECORD, INFO)]
    facts = []
    for record, section, source, unit in (
        (API_RECORD, card["api_usd"], "official_openai_model_pages", {"currency": "USD"}),
        (CREDIT_RECORD, card["codex_credits"], "official_codex_pricing", {"credit_unit": "credits"}),
    ):
        for model, rates in sorted(section["models"].items()):
            for token_class, price in sorted(rates.items()):
                facts.append({"record": record, "expr": f"vector({price})", "labels": {
                    "ai_agent_provider": "openai", "model_id": model, "usage_class": token_class,
                    "rate_card_version": section["version"], "rate_card_source": source,
                    "pricing_scope": section["scope"], "snapshot_read_at": section["verified_on"], **unit}})
    facts.append({"record": INFO, "expr": "vector(1)", "labels": {"rate_card_version": card["version"]}})
    return {"groups": [{**group, "rules": facts + calculations}]}


def packed(data: dict) -> bytes:
    return (json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def publish(directory: Path, files: dict[str, bytes]) -> None:
    """Publish a complete directory exactly once, including across concurrent preparations."""
    directory.parent.mkdir(parents=True, exist_ok=True)
    if directory.is_dir() and set(p.name for p in directory.iterdir()) == set(files):
        if all((directory / name).read_bytes() == content for name, content in files.items()):
            return
        raise ValueError("existing version has different content: " + directory.name)
    with tempfile.TemporaryDirectory(dir=directory.parent) as tmp:
        candidate = Path(tmp) / "candidate"
        candidate.mkdir()
        for name, content in files.items():
            (candidate / name).write_bytes(content)
        try:
            candidate.rename(directory)
            return
        except OSError:
            if not directory.is_dir():
                raise
    if (set(p.name for p in directory.iterdir()) != set(files)
            or any((directory / name).read_bytes() != content for name, content in files.items())):
        raise ValueError("existing version has different content: " + directory.name)


def prepare(path: Path, store: Path, promtool: list[str]) -> tuple[dict, Path]:
    card = load(path)
    generated = yaml.safe_dump(price_rules(card), sort_keys=False).encode()
    legacy = (RULES / "ai-agent-cost.yml").read_bytes()
    for content in (generated, legacy):
        subprocess.run(promtool + ["check", "rules", "/dev/stdin"], input=content, check=True)
    # Reserve published identifiers, including the bundled/archived cards, before adding overrides.
    artifacts = {}
    for old in (ROOT / "config/session-usage/archives").glob("*.json"):
        archived = usage.load_rate_card(old)
        artifacts[store / "cards/codex_credits" / archived["version"]] = {"card.json": packed(archived)}
    for snapshot in (load(DEFAULT), card):
        for key in ("api_usd", "codex_credits"):
            section = snapshot[key]
            destination = store / "cards" / key / section["version"]
            files = {"card.json": packed(section)}
            if artifacts.setdefault(destination, files) != files:
                raise ValueError("conflicting published component version")
        destination = store / "snapshots" / snapshot["version"]
        files = {"card.json": packed(snapshot)}
        if artifacts.setdefault(destination, files) != files:
            raise ValueError("conflicting published snapshot version")
    digest = hashlib.sha256(generated + legacy).hexdigest()
    directory = store / "rules" / digest
    artifacts[directory] = {"ai-agent-cost.yml": legacy, "ai-agent-interval-cost.yml": generated}
    store.mkdir(parents=True, exist_ok=True)
    with deployment_lock(store):
        for dest, files in artifacts.items():
            if dest.exists() and any(not (dest / k).is_file() or (dest / k).read_bytes() != v for k, v in files.items()):
                raise ValueError("existing version has different content: " + dest.name)
        for dest, files in artifacts.items():
            publish(dest, files)
    return card, directory


def command(args, toolkit) -> None:
    toolkit.load_env_file()
    store = args.store.resolve()
    if store.is_relative_to(RULES.resolve()):
        raise ValueError("select a deployment store outside the provisioned rules directory")
    compose = toolkit.require_compose() + toolkit.compose_args(args.mode)
    spec = json.loads(subprocess.check_output(compose + ["config", "--format", "json"], cwd=ROOT))
    image = spec["services"]["prometheus"]["image"]
    env = os.environ.copy()
    remount = False
    if args.action == "deploy":
        # A pricing-only operation retains the existing TSDB and running image.
        container = subprocess.check_output(compose + ["ps", "-q", "prometheus"], cwd=ROOT, text=True).strip()
        if not container:
            raise ValueError("start this Compose project's Prometheus service before deploying a price card")
        image = subprocess.check_output(["docker", "inspect", "--format", "{{.Config.Image}}", container], text=True).strip()
        env["PROMETHEUS_IMAGE"] = image
        mounts = json.loads(subprocess.check_output(["docker", "inspect", "--format", "{{json .Mounts}}", container]))
        data = next(m for m in spec["services"]["prometheus"]["volumes"] if m["target"] == "/prometheus")
        expected_volume = spec["volumes"][data["source"]]["name"]
        if not any(m["Destination"] == "/prometheus" and m.get("Name") == expected_volume for m in mounts):
            raise ValueError("the running Prometheus data volume differs from the selected Compose project")
        running_args = json.loads(subprocess.check_output(
            ["docker", "inspect", "--format", "{{json .Config.Cmd}}", container]))
        if running_args != spec["services"]["prometheus"]["command"]:
            raise ValueError("Prometheus startup or retention settings differ; reconcile them before a price-only change")
        # Compose labels identify the resolved service configuration across Docker Desktop path translations.
        desired = subprocess.check_output(compose + ["config", "--hash", "prometheus"], env=env, cwd=ROOT, text=True).split()[-1]
        current_hash = subprocess.check_output(["docker", "inspect", "--format",
            '{{index .Config.Labels "com.docker.compose.config-hash"}}', container], text=True).strip()
        remount = current_hash != desired
    promtool = ["docker", "run", "--rm", "-i", "--network", "none", "--entrypoint", "/bin/promtool", image]
    card, directory = prepare(args.card, store, promtool)
    digest = hashlib.sha256(packed(card)).hexdigest()
    print(f"Validated {card['version']} sha256={digest}\nPrepared rules: {directory.as_posix()}", flush=True)
    if args.action == "prepare":
        return
    active = store / "active"
    mount = next(m for m in spec["services"]["prometheus"]["volumes"] if m["target"] == "/etc/prometheus/rules")
    if mount["type"] != "bind" or Path(mount["source"]).resolve() != active or not mount["read_only"]:
        raise ValueError(f"set PROMETHEUS_RULES_DIR={active.as_posix()} in the deployment environment")
    with deployment_lock(store):
        active.mkdir(exist_ok=True)
        legacy = active / "ai-agent-cost.yml"
        historical = (directory / legacy.name).read_bytes()
        if legacy.exists() and legacy.read_bytes() != historical:
            raise ValueError("legacy rules conflict with the engine version")
        if not legacy.exists():
            replace_file(legacy, historical)
        current = active / "ai-agent-interval-cost.yml"
        previous = current.read_bytes() if current.exists() else (RULES / current.name).read_bytes()
        candidate = (directory / current.name).read_bytes()
        start = time.time()
        replace_file(current, candidate)
        changed_service = False
        try:
            # Validate the actual Docker mount before touching a running service.
            # A host can read locations that Docker Desktop cannot bind-mount.
            subprocess.run([
                "docker", "run", "--rm", "--network", "none", "--entrypoint", "/bin/promtool",
                "--mount", f"type=bind,source={active},target=/selected,readonly", image,
                "check", "rules", "/selected/" + current.name, "/selected/" + legacy.name,
            ], check=True)
            changed_service = True
            if remount:
                subprocess.run(compose + ["up", "-d", "--no-deps", "prometheus"], env=env, cwd=ROOT, check=True)
            subprocess.run(compose + ["kill", "-s", "SIGHUP", "prometheus"], cwd=ROOT, check=True)
            # Query the selected container, independent of Grafana credentials or host ports.
            query = f'timestamp({INFO}{{rate_card_version="{card["version"]}"}}) >= {start}'
            def observed():
                output = subprocess.check_output(compose + [
                    "exec", "-T", "prometheus", "/bin/promtool", "query", "instant",
                    "--format=json", "http://127.0.0.1:9090", query], cwd=ROOT, text=True)
                return json.loads(output)
            rows = toolkit.retry("active rate card evaluation", observed, lambda r: len(r) == 1, timeout=120)
        except (RuntimeError, OSError, subprocess.SubprocessError):
            replace_file(current, previous)
            if changed_service:
                subprocess.run(compose + ["kill", "-s", "SIGHUP", "prometheus"], cwd=ROOT, check=True)
            raise
        sample = float(rows[0]["value"][1])
        receipt = {"project": spec["name"], "version": card["version"], "sha256": digest,
                   "requested_at": dt.datetime.fromtimestamp(start, dt.timezone.utc).isoformat(),
                   "observed_evaluation_at": dt.datetime.fromtimestamp(sample, dt.timezone.utc).isoformat(),
                   "rules_digest": directory.name}
        publish(store / "activations" / f"{time.time_ns()}", {"receipt.json": packed(receipt)})
        print(json.dumps(receipt))


def replace_file(path: Path, content: bytes) -> None:
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        tmp = Path(stream.name)
        stream.write(content)
    try:
        tmp.chmod(0o644)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


@contextmanager
def deployment_lock(store: Path):
    # Advisory OS locks are released even if the applying process exits unexpectedly.
    with (store / "deploy.lock").open("a+b") as lock:
        if os.name == "nt":
            import msvcrt
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
