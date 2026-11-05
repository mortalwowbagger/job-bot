"""Plans and Stripe billing for the hosted app.

Plans live in config.yaml (cloud.plans). Payments use Stripe Checkout (Stripe's
hosted page; job-bot never sees card numbers) and Stripe's billing portal for
managing/cancelling. A webhook keeps users/{uid} in sync:

  plan: "pro" | "free"       subscription_status: Stripe status (active, past_due, canceled, ...)
  current_period_end         cancel_at_period_end       stripe_customer_id     comp (owner-granted Pro)

Webhook events are verified with Stripe's signature, then the subscription's
current state is re-read from Stripe, so duplicate or out-of-order events can't
leave a user on the wrong plan.
"""
from datetime import datetime, timezone

PAID_STATUSES = {"active", "trialing", "past_due"}  # past_due = Stripe is still retrying the card


def plan_name(user):
    if user.get("is_admin"):
        return "owner"
    if user.get("comp"):
        return "pro"
    if user.get("plan") == "pro" and user.get("subscription_status") in PAID_STATUSES:
        return "pro"
    return "free"


def limits(cloud_cfg, user):
    """Effective limits for a user: their plan's numbers (the owner gets the generous defaults)."""
    plans = cloud_cfg.get("plans") or {}
    name = plan_name(user)
    if name == "owner":
        return {"plan": "owner", "label": "Owner", "runs_per_day": cloud_cfg.get("owner_runs_per_day", 10),
                "scheduled": "daily", "max_score_per_run": None, "max_tailor_per_run": None, "extension": True}
    p = plans.get(name) or {}
    return {"plan": name, "label": p.get("label", name.title()), "runs_per_day": p.get("runs_per_day", 1),
            "scheduled": p.get("scheduled", "weekly"), "max_score_per_run": p.get("max_score_per_run"),
            "max_tailor_per_run": p.get("max_tailor_per_run"), "extension": bool(p.get("extension"))}


def runs_today(cloud_cfg, user, now=None):
    """Does the automatic 7am search include this user today?"""
    sched = limits(cloud_cfg, user)["scheduled"]
    return sched == "daily" or (now or datetime.now()).weekday() == 0  # weekly = Mondays


# ---------------------------------------------------------------- Stripe

def _stripe(key):
    import stripe
    return stripe.StripeClient(key)


def _v1(client):
    """Stripe's current API namespace (StripeClient.v1); test fakes may not have it."""
    return getattr(client, "v1", client)


def customer_for(client, store, uid, user):
    """Reuse the user's Stripe customer, or create one tagged with their job-bot id."""
    if user.get("stripe_customer_id"):
        return user["stripe_customer_id"]
    cust = _v1(client).customers.create(params={"email": user.get("email"), "metadata": {"uid": uid}})
    store.update_user(uid, stripe_customer_id=cust.id)
    store.set_stripe_customer(cust.id, uid)
    return cust.id


def checkout_url(client, store, uid, user, price_id, base_url):
    session = _v1(client).checkout.sessions.create(params={
        "mode": "subscription", "customer": customer_for(client, store, uid, user),
        "line_items": [{"price": price_id, "quantity": 1}], "client_reference_id": uid,
        "subscription_data": {"metadata": {"uid": uid}}, "allow_promotion_codes": True,
        "success_url": f"{base_url}/?billing=success", "cancel_url": f"{base_url}/?billing=cancelled"})
    return session.url


def portal_url(client, store, uid, user, base_url, configuration=None):
    params = {"customer": customer_for(client, store, uid, user), "return_url": f"{base_url}/?settings=1"}
    if configuration:
        params["configuration"] = configuration
    return _v1(client).billing_portal.sessions.create(params=params).url


def apply_subscription(store, uid, sub):
    """Write a Stripe subscription's state onto the user."""
    status = sub.get("status")
    item = ((sub.get("items") or {}).get("data") or [{}])[0]
    end = sub.get("current_period_end") or item.get("current_period_end")
    store.update_user(uid, plan="pro" if status in PAID_STATUSES else "free", subscription_status=status,
                      subscription_id=sub.get("id"), cancel_at_period_end=bool(sub.get("cancel_at_period_end")),
                      current_period_end=(datetime.fromtimestamp(end, tz=timezone.utc).strftime("%Y-%m-%d")
                                          if end else None),
                      billing_interval=((item.get("price") or {}).get("recurring") or {}).get("interval"))


SUBSCRIPTION_EVENTS = {"customer.subscription.created", "customer.subscription.updated",
                       "customer.subscription.deleted", "customer.subscription.paused",
                       "customer.subscription.resumed", "checkout.session.completed",
                       "invoice.payment_failed", "invoice.paid"}


def handle_event(client, store, event):
    """Process one verified Stripe event. Returns a short description (for logs)."""
    event = _plain(event)
    etype = event["type"]
    if etype not in SUBSCRIPTION_EVENTS:
        return f"ignored {etype}"
    obj = event["data"]["object"]
    customer = obj.get("customer")
    uid = (obj.get("metadata") or {}).get("uid") or obj.get("client_reference_id") or \
        (customer and store.uid_for_stripe_customer(customer))
    if not uid or not store.get_user(uid):
        return f"no job-bot user for {etype} (customer {customer})"
    if customer and not store.get_user(uid).get("stripe_customer_id"):
        store.update_user(uid, stripe_customer_id=customer)
        store.set_stripe_customer(customer, uid)
    sub_id = obj.get("id") if obj.get("object") == "subscription" else obj.get("subscription")
    if not sub_id:
        return f"{etype}: no subscription"
    sub = _plain(_v1(client).subscriptions.retrieve(sub_id))  # current truth, not the event's (possibly stale) copy
    apply_subscription(store, uid, sub)
    return f"{etype}: {uid} -> {sub.get('status')}"


def _plain(obj):
    """Stripe library objects -> plain dicts (stripe>=10 objects don't support dict.get)."""
    return obj.to_dict() if hasattr(obj, "to_dict") else obj
