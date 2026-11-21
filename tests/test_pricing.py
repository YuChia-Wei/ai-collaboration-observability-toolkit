"""Public pricing snapshot compatibility and publication boundaries."""
import json
from pathlib import Path
import tempfile
import unittest

import yaml

from scripts import pricing, session_usage


class DeploymentPricingTests(unittest.TestCase):
    def test_bundled_json_matches_every_published_active_price(self):
        current = yaml.safe_load((pricing.RULES / "ai-agent-interval-cost.yml").read_text())
        card = pricing.load(pricing.DEFAULT)
        def facts(config):
            return {
                (r["record"], r["labels"]["model_id"], r["labels"]["usage_class"]):
                    (r["expr"].split(")")[0], r["labels"]["rate_card_version"])
                for r in config["groups"][0]["rules"]
                if r["record"] in (pricing.API_RECORD, pricing.CREDIT_RECORD)
            }
        self.assertEqual(facts(current), facts(pricing.price_rules(card)))
        self.assertEqual(session_usage.load_rate_card(pricing.DEFAULT), session_usage.load_rate_card())

    def test_new_model_api_and_credit_coverage_are_independent(self):
        card = pricing.load(pricing.DEFAULT)
        card["api_usd"]["models"]["gpt-6.2-sol"] = {"output": "1.25"}
        card["codex_credits"]["models"]["gpt-6.2-astra"] = {"input_uncached": "1", "input_cached": "0.1", "output": "2"}
        card["codex_credits"]["speed_multipliers"]["fast"] = "3"
        pricing.validate_card(card)
        facts = [r for r in pricing.price_rules(card)["groups"][0]["rules"]
                 if r.get("labels", {}).get("model_id") in ("gpt-6.2-sol", "gpt-6.2-astra")]
        self.assertEqual([(r["record"], r["expr"]) for r in facts if r["labels"]["model_id"] == "gpt-6.2-sol"],
                         [(pricing.API_RECORD, "vector(1.25)")])
        self.assertEqual({r["record"] for r in facts if r["labels"]["model_id"] == "gpt-6.2-astra"}, {pricing.CREDIT_RECORD})

    def test_duplicate_keys_and_invalid_amount_or_schema_are_rejected(self):
        with self.assertRaises(ValueError):
            json.loads('{"output":"2","output":"3"}', object_pairs_hook=session_usage.unique_keys)
        for bad in ("-2", "NaN", 3):
            card = pricing.load(pricing.DEFAULT)
            card["api_usd"]["models"]["gpt-6.2-sol"] = {"output": bad}
            with self.assertRaises(ValueError):
                pricing.validate_card(card)
        card = pricing.load(pricing.DEFAULT)
        card["schema_version"] = "unknown"
        with self.assertRaises(ValueError):
            pricing.validate_card(card)

    def test_archive_is_idempotent_and_refuses_a_reused_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "v1"
            pricing.publish(dst, {"card.json": b"first"})
            pricing.publish(dst, {"card.json": b"first"})
            with self.assertRaises(ValueError):
                pricing.publish(dst, {"card.json": b"second"})
            self.assertEqual((dst / "card.json").read_bytes(), b"first")
