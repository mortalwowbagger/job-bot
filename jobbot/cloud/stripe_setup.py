"""One-time Stripe setup for job-bot Pro. Safe to re-run (finds what exists).

  python -m jobbot.cloud.stripe_setup            # uses STRIPE_SECRET_KEY from .env (sk_test_... or sk_live_...)

Creates the "job-bot Pro" product and its monthly/yearly prices (from config.yaml
cloud.plans.pro), a billing-portal configuration, and the webhook endpoint; stores
the secret key and webhook signing secret in Secret Manager; writes the price ids
into config.yaml. Run once in test mode, and again with live keys when going live.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

import stripe
import yaml
from dotenv import load_dotenv

PROJECT = "job-bot-app"
SITE = "https://job-bot-app.web.app"
EVENTS = ["checkout.session.completed", "customer.subscription.created", "customer.subscription.updated",
          "customer.subscription.deleted", "customer.subscription.paused", "customer.subscription.resumed",
          "invoice.paid", "invoice.payment_failed"]


def secret(name, value):
    """Create or add a version of a Secret Manager secret (value passed on stdin, never printed)."""
    exists = subprocess.run(["gcloud", "secrets", "describe", name, "--project", PROJECT],
                            capture_output=True).returncode == 0
    cmd = (["gcloud", "secrets", "versions", "add", name] if exists else
           ["gcloud", "secrets", "create", name, "--replication-policy=automatic"])
    subprocess.run(cmd + ["--project", PROJECT, "--data-file=-", "--quiet"], input=value.encode(),
                   check=True, capture_output=True)
    sa = f"jobbot-runner@{PROJECT}.iam.gserviceaccount.com"
    subprocess.run(["gcloud", "secrets", "add-iam-policy-binding", name, "--project", PROJECT, "--quiet",
                    f"--member=serviceAccount:{sa}", "--role=roles/secretmanager.secretAccessor"],
                   check=True, capture_output=True)


def main():
    load_dotenv(".env")
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key.startswith(("sk_test_", "sk_live_", "rk_test_", "rk_live_")):
        sys.exit("Put your Stripe secret key in .env as STRIPE_SECRET_KEY=sk_test_... first.")
    mode = "LIVE" if "_live_" in key else "test"
    client = stripe.StripeClient(key).v1
    cfg_path = Path("config.yaml")
    cfg = yaml.safe_load(cfg_path.read_text())
    pro = cfg["cloud"]["plans"]["pro"]
    print(f"Stripe {mode} mode")

    prices = {}
    for interval, amount, lookup in (("month", pro["price_monthly_usd"], "jobbot_pro_monthly"),
                                     ("year", pro["price_yearly_usd"], "jobbot_pro_yearly")):
        found = client.prices.list(params={"lookup_keys": [lookup], "active": True}).data
        if found and found[0].unit_amount == int(amount * 100):
            price = found[0]
        else:
            product = next((p for p in client.products.list(params={"active": True, "limit": 100}).data
                            if (p.metadata or {}).get("app") == "job-bot"), None) or client.products.create(params={
                "name": "job-bot Pro", "metadata": {"app": "job-bot"},
                "description": "Daily job search, more tailored resumes and cover letters, and the browser extension."})
            price = client.prices.create(params={"product": product.id, "currency": "usd",
                                                 "unit_amount": int(amount * 100), "recurring": {"interval": interval},
                                                 "lookup_key": lookup, "transfer_lookup_key": True})
        prices[interval] = price
        print(f"  price {interval:5s} ${amount} -> {price.id}")

    portal = client.billing_portal.configurations.create(params={
        "business_profile": {"headline": "Manage your job-bot Pro subscription"},
        "features": {"customer_update": {"enabled": True, "allowed_updates": ["email"]},
                     "invoice_history": {"enabled": True}, "payment_method_update": {"enabled": True},
                     "subscription_cancel": {"enabled": True, "mode": "at_period_end"},
                     "subscription_update": {"enabled": True, "default_allowed_updates": ["price"],
                                             "proration_behavior": "create_prorations",
                                             "products": [{"product": prices["month"].product,
                                                           "prices": [prices["month"].id, prices["year"].id]}]}}})
    print(f"  billing portal -> {portal.id}")

    url = f"{SITE}/api/stripe/webhook"
    for ep in client.webhook_endpoints.list(params={"limit": 100}).data:
        if ep.url == url:  # the signing secret is only shown at creation, so replace it
            client.webhook_endpoints.delete(ep.id)
    ep = client.webhook_endpoints.create(params={"url": url, "enabled_events": EVENTS,
                                                 "description": "job-bot subscriptions"})
    print(f"  webhook -> {url}")

    secret("stripe-secret-key", key)
    secret("stripe-webhook-secret", ep.secret)
    print("  keys stored in Secret Manager (stripe-secret-key, stripe-webhook-secret)")

    text = cfg_path.read_text()
    for k, v in (("price_monthly", prices["month"].id), ("price_yearly", prices["year"].id), ("portal_config", portal.id)):
        if re.search(rf"^    {k}:", text, re.M):
            text = re.sub(rf'^    {k}:.*$', f'    {k}: "{v}"', text, flags=re.M)
        else:
            text = text.replace("  stripe:", f'  stripe:\n    {k}: "{v}"', 1)
    text = re.sub(r"^  stripe:.*$", f"  stripe:                       # {mode} mode ids, written by jobbot.cloud.stripe_setup",
                  text, count=1, flags=re.M)
    cfg_path.write_text(text)
    print("  config.yaml updated. Next: bash deploy/deploy.sh")


if __name__ == "__main__":
    main()
