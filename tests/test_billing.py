"""Plans and Stripe billing (Stripe calls are faked; webhook signatures are real HMACs)."""
import hashlib
import hmac
import json
import time
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import yaml

from jobbot.cloud import billing, pipeline
from jobbot.cloud.store import MemoryStore
from jobbot.cloud.webapp import create_app

REPO = Path(__file__).parent.parent
CFG = yaml.safe_load((REPO / "config.yaml").read_text())
CLOUD = {**CFG["cloud"], "stripe": {"price_monthly": "price_m", "price_yearly": "price_y"}}
SECRET = "whsec_test"


class FakeStripe:
    """Records calls; returns objects shaped like StripeClient results."""
    def __init__(self):
        self.calls, self.subs = [], {}
        outer = self

        class Customers:
            def create(self, params):
                outer.calls.append(("customer", params)); return SimpleNamespace(id="cus_1")

        class Sessions:
            def __init__(self, kind): self.kind = kind
            def create(self, params):
                outer.calls.append((self.kind, params)); return SimpleNamespace(url=f"https://stripe.test/{self.kind}")

        class Subs:
            def retrieve(self, sid): return outer.subs[sid]

        self.customers = Customers()
        self.checkout = SimpleNamespace(sessions=Sessions("checkout"))
        self.billing_portal = SimpleNamespace(sessions=Sessions("portal"))
        self.subscriptions = Subs()


def signed(event):
    payload = json.dumps(event)
    ts = str(int(time.time()))
    sig = hmac.new(SECRET.encode(), f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()
    return payload, {"Stripe-Signature": f"t={ts},v1={sig}", "Content-Type": "application/json"}


class TestPlans(unittest.TestCase):
    def test_plan_rules(self):
        self.assertEqual(billing.plan_name({"is_admin": True}), "owner")
        self.assertEqual(billing.plan_name({"comp": True}), "pro")
        self.assertEqual(billing.plan_name({"plan": "pro", "subscription_status": "active"}), "pro")
        self.assertEqual(billing.plan_name({"plan": "pro", "subscription_status": "past_due"}), "pro")   # card retrying
        self.assertEqual(billing.plan_name({"plan": "pro", "subscription_status": "canceled"}), "free")
        self.assertEqual(billing.plan_name({}), "free")
        free, pro = billing.limits(CLOUD, {}), billing.limits(CLOUD, {"comp": True})
        self.assertEqual((free["max_tailor_per_run"], free["extension"], free["scheduled"]), (3, False, "weekly"))
        self.assertEqual((pro["max_tailor_per_run"], pro["extension"], pro["scheduled"]), (10, True, "daily"))

    def test_free_users_get_the_automatic_search_on_mondays_only(self):
        monday, wednesday = datetime(2026, 11, 2, 7), datetime(2026, 11, 4, 7)
        self.assertTrue(billing.runs_today(CLOUD, {}, monday))
        self.assertFalse(billing.runs_today(CLOUD, {}, wednesday))
        self.assertTrue(billing.runs_today(CLOUD, {"comp": True}, wednesday))

    def test_pipeline_caps_follow_the_plan(self):
        cfg = {**CFG, "cloud": CLOUD}
        self.assertEqual(pipeline.user_cfg(cfg, {})["max_score_per_run"], 20)
        self.assertEqual(pipeline.user_cfg(cfg, {"comp": True})["max_score_per_run"], 80)
        self.assertEqual(pipeline.user_cfg(cfg, {"is_admin": True})["max_score_per_run"], CFG["max_score_per_run"])


class TestBillingEndpoints(unittest.TestCase):
    def setUp(self):
        self.store, self.stripe = MemoryStore(), FakeStripe()
        people = {"owner": {"uid": "o", "email": "owner@example.com"}, "friend": {"uid": "f", "email": "friend@example.com"}}
        self.c = create_app(self.store, people.__getitem__, lambda u: None, admin_emails=["owner@example.com"],
                            cloud_cfg=CLOUD, stripe_client=self.stripe, stripe_webhook_secret=SECRET,
                            base_url="https://site.test").test_client()
        self.H = {k: {"Authorization": f"Bearer {k}"} for k in people}
        for k in people:
            self.c.get("/api/me", headers=self.H[k])

    def webhook(self, event):
        payload, headers = signed(event)
        return self.c.post("/api/stripe/webhook", data=payload, headers=headers)

    def test_checkout_then_webhook_makes_the_user_pro(self):
        info = self.c.get("/api/billing", headers=self.H["friend"]).get_json()
        self.assertEqual((info["plan"], info["payments_enabled"], info["prices"]["month"]), ("free", True, 15))
        r = self.c.post("/api/billing/checkout", json={"interval": "year"}, headers=self.H["friend"])
        self.assertEqual(r.get_json()["url"], "https://stripe.test/checkout")
        kind, params = self.stripe.calls[-1]
        self.assertEqual((params["mode"], params["line_items"][0]["price"], params["client_reference_id"]),
                         ("subscription", "price_y", "f"))
        self.assertEqual(self.store.get_user("f")["stripe_customer_id"], "cus_1")
        self.stripe.subs["sub_1"] = {"id": "sub_1", "status": "active", "cancel_at_period_end": False,
                                     "items": {"data": [{"current_period_end": 1798761600,
                                                         "price": {"recurring": {"interval": "year"}}}]}}
        r = self.webhook({"type": "checkout.session.completed", "data": {"object": {
            "object": "checkout.session", "customer": "cus_1", "subscription": "sub_1", "client_reference_id": "f"}}})
        self.assertEqual(r.status_code, 200)
        info = self.c.get("/api/billing", headers=self.H["friend"]).get_json()
        self.assertEqual((info["plan"], info["current_period_end"], info["billing_interval"], info["extension"]),
                         ("pro", "2027-01-01", "year", True))
        self.assertEqual(self.c.post("/api/billing/portal", headers=self.H["friend"]).get_json()["url"], "https://stripe.test/portal")

    def test_cancellation_and_unknown_or_forged_events(self):
        self.store.update_user("f", plan="pro", subscription_status="active", stripe_customer_id="cus_1")
        self.store.set_stripe_customer("cus_1", "f")
        self.stripe.subs["sub_1"] = {"id": "sub_1", "status": "canceled", "items": {"data": [{}]}}
        self.webhook({"type": "customer.subscription.deleted", "data": {"object": {"object": "subscription",
                                                                                   "id": "sub_1", "customer": "cus_1"}}})
        self.assertEqual(billing.plan_name(self.store.get_user("f")), "free")
        r = self.c.post("/api/stripe/webhook", data=json.dumps({"type": "x"}),
                        headers={"Stripe-Signature": "t=1,v1=forged", "Content-Type": "application/json"})
        self.assertEqual(r.status_code, 400)                                       # forged: rejected
        self.assertEqual(self.webhook({"type": "charge.refunded", "data": {"object": {}}}).status_code, 200)  # ignored

    def test_free_limits_and_upgrade_prompts(self):
        self.store.set_profile("f", (REPO / "profile.example.yaml").read_text())
        self.c.post("/api/settings", json={"title_keywords": "sdet"}, headers=self.H["friend"])
        self.assertEqual(self.c.post("/api/run", headers=self.H["friend"]).status_code, 200)
        self.store.set_run("f", running=False)
        r = self.c.post("/api/run", headers=self.H["friend"])
        self.assertEqual(r.status_code, 429)
        self.assertTrue(r.get_json()["upgrade"])
        r = self.c.post("/api/ext/connect", headers=self.H["friend"])
        self.assertEqual((r.status_code, r.get_json()["upgrade"]), (403, True))   # extension is Pro

    def test_owner_can_comp_pro(self):
        self.assertEqual(self.c.post("/api/admin/users/f/comp", json={"comp": True}, headers=self.H["owner"]).status_code, 200)
        self.assertEqual(self.c.get("/api/billing", headers=self.H["friend"]).get_json()["plan"], "pro")
        self.assertEqual(self.c.post("/api/admin/users/o/comp", json={"comp": True}, headers=self.H["friend"]).status_code, 403)
        users = {u["email"]: u for u in self.c.get("/api/admin/users", headers=self.H["owner"]).get_json()}
        self.assertEqual((users["friend@example.com"]["plan"], users["friend@example.com"]["comp"]), ("pro", True))
        self.assertEqual(self.c.post("/api/billing/checkout", json={}, headers=self.H["friend"]).status_code, 400)  # already Pro


if __name__ == "__main__":
    unittest.main()
