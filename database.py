"""
database.py — MongoDB layer
============================
Drop-in replacement for the SQLite version.
Every function keeps the same name and return type —
no other file needs to change.

Collections:
  users           — wallet, profile
  accounts        — stock (phone + session + status)
  orders          — purchase history + OTP
  payments        — add-funds requests
  country_prices  — price per country

Counters collection stores auto-increment IDs for
accounts, orders, payments (MongoDB has no AUTOINCREMENT).
"""

from datetime import datetime, timezone
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.collection import Collection
from config import MONGO_URI, MONGO_DB

# ── Connection ────────────────────────────────────────────────────────────────
_client: MongoClient = None
_db = None


def get_db():
    global _client, _db
    if _db is None:
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        _db     = _client[MONGO_DB]
    return _db


def col(name: str) -> Collection:
    return get_db()[name]


def normalize_account_doc(doc: dict | None) -> dict | None:
    if not doc:
        return None
    if "account_id" in doc and "id" not in doc:
        doc["id"] = doc["account_id"]
    return doc

# ── Auto-increment helper (replaces SQLite AUTOINCREMENT) ─────────────────────
def next_id(seq_name: str) -> int:
    result = get_db()["counters"].find_one_and_update(
        {"_id": seq_name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True
    )
    return result["seq"]


# ── Indexes (run once on startup) ─────────────────────────────────────────────
def init_db():
    db = get_db()
    db["users"].create_index("user_id", unique=True)
    db["accounts"].create_index([("country", ASCENDING), ("is_sold", ASCENDING), ("status", ASCENDING)])
    db["accounts"].create_index("account_id", unique=True, sparse=True)
    db["orders"].create_index("order_id", unique=True)
    db["orders"].create_index("user_id")
    db["payments"].create_index("pay_id", unique=True)
    db["country_prices"].create_index("country", unique=True)


# ── now() helper ──────────────────────────────────────────────────────────────
def now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ─────────────────────────────────────────────────────────────────────────────
# USERS
# ─────────────────────────────────────────────────────────────────────────────

def upsert_user(user_id: int, username: str, full_name: str):
    col("users").update_one(
        {"user_id": user_id},
        {"$set":      {"username": username, "full_name": full_name},
         "$setOnInsert": {"balance": 0.0, "joined_at": now_str(), "is_banned": 0}},
        upsert=True
    )


def get_user(user_id: int) -> dict | None:
    doc = col("users").find_one({"user_id": user_id}, {"_id": 0})
    return doc


def update_balance(user_id: int, delta: float):
    col("users").update_one(
        {"user_id": user_id},
        {"$inc": {"balance": delta}}
    )


def all_users() -> list[int]:
    docs = col("users").find({"is_banned": 0}, {"user_id": 1, "_id": 0})
    return [d["user_id"] for d in docs]


# ─────────────────────────────────────────────────────────────────────────────
# ACCOUNTS
# ─────────────────────────────────────────────────────────────────────────────

def add_account(country: str, data: str):
    aid = next_id("account_id")
    col("accounts").insert_one({
        "account_id":   aid,
        "id":           aid,
        "country":      country,
        "data":         data,
        "is_sold":      0,
        "status":       "unchecked",
        "last_checked": None,
        "added_at":     now_str()
    })


def bulk_add_accounts(country: str, lines: list[str]):
    docs = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        aid = next_id("account_id")
        docs.append({
            "account_id":   aid,
            "id":           aid,
            "country":      country,
            "data":         line,
            "is_sold":      0,
            "status":       "unchecked",
            "last_checked": None,
            "added_at":     now_str()
        })
    if docs:
        col("accounts").insert_many(docs)


def get_stock_summary() -> list[dict]:
    """Returns [{country, price, cnt}] sorted by price."""
    pipeline = [
        {"$match": {"is_sold": 0, "status": {"$nin": ["dead", "reserved", "sold"]}}},
        {"$group": {"_id": "$country", "cnt": {"$sum": 1}}},
        {"$lookup": {
            "from":         "country_prices",
            "localField":   "_id",
            "foreignField": "country",
            "as":           "price_doc"
        }},
        {"$project": {
            "_id":     0,
            "country": "$_id",
            "cnt":     1,
            "price":   {"$ifNull": [{"$arrayElemAt": ["$price_doc.price", 0]}, 50.0]}
        }},
        {"$sort": {"price": 1}}
    ]
    return list(col("accounts").aggregate(pipeline))


def get_available_account(country: str) -> dict | None:
    """Next available account — prefers verified 'alive' over 'unchecked'."""
    # Try alive first, then unchecked
    for status in ["alive", "unchecked"]:
        doc = col("accounts").find_one(
            {"country": country, "is_sold": 0, "status": status},
            {"_id": 0},
            sort=[("account_id", ASCENDING)]
        )
        if doc:
            return normalize_account_doc(doc)
    return None


def get_account_by_id(account_id: int) -> dict | None:
    return normalize_account_doc(
        col("accounts").find_one({"account_id": account_id}, {"_id": 0})
    )


def get_all_unsold_accounts() -> list[dict]:
    docs = col("accounts").find(
        {"is_sold": 0},
        {"_id": 0},
        sort=[("status", DESCENDING), ("account_id", ASCENDING)]
    )
    return [normalize_account_doc(doc) for doc in docs]


def mark_reserved(account_id: int):
    col("accounts").update_one(
        {"account_id": account_id},
        {"$set": {"status": "reserved"}}
    )


def mark_sold(account_id: int):
    col("accounts").update_one(
        {"account_id": account_id},
        {"$set": {"is_sold": 1, "status": "sold"}}
    )


def unmark_sold(account_id: int):
    col("accounts").update_one(
        {"account_id": account_id},
        {"$set": {"is_sold": 0, "status": "unchecked"}}
    )


def mark_account_dead(account_id: int):
    col("accounts").update_one(
        {"account_id": account_id},
        {"$set": {"status": "dead", "last_checked": now_str()}}
    )


def mark_account_verified(account_id: int):
    col("accounts").update_one(
        {"account_id": account_id},
        {"$set": {"status": "alive", "last_checked": now_str()}}
    )


def get_dead_count() -> int:
    return col("accounts").count_documents({"status": "dead", "is_sold": 0})


def delete_dead_accounts():
    col("accounts").delete_many({"status": "dead", "is_sold": 0})


def delete_account(account_id: int):
    col("accounts").delete_one({"account_id": account_id})


# ─────────────────────────────────────────────────────────────────────────────
# ORDERS
# ─────────────────────────────────────────────────────────────────────────────

def create_order(user_id: int, account_id: int, country: str,
                 price: float, account_data: str = None) -> int:
    oid = next_id("order_id")
    col("orders").insert_one({
        "order_id":    oid,
        "id":          oid,          # alias used by handlers
        "user_id":     user_id,
        "account_id":  account_id,
        "country":     country,
        "price":       price,
        "account_data": account_data or "",
        "status":      "pending",
        "otp_code":    None,
        "otp_sent":    0,
        "otp_verified": 0,
        "ordered_at":  now_str()
    })
    return oid


def get_order(order_id: int) -> dict | None:
    doc = col("orders").find_one(
        {"$or": [{"order_id": order_id}, {"id": order_id}]},
        {"_id": 0}
    )
    return doc


def get_orders(user_id: int) -> list[dict]:
    docs = col("orders").find(
        {"user_id": user_id},
        {"_id": 0},
        sort=[("ordered_at", DESCENDING)],
        limit=20
    )
    return list(docs)


def mark_order_otp_sent(order_id: int, otp_code: str):
    col("orders").update_one(
        {"$or": [{"order_id": order_id}, {"id": order_id}]},
        {"$set": {"otp_code": otp_code, "otp_sent": 1}}
    )


def mark_order_verified(order_id: int):
    col("orders").update_one(
        {"$or": [{"order_id": order_id}, {"id": order_id}]},
        {"$set": {"otp_verified": 1, "status": "delivered"}}
    )


def get_order_by_user_and_code(user_id: int, otp_code: str) -> dict | None:
    return col("orders").find_one(
        {"user_id": user_id, "otp_code": otp_code,
         "otp_sent": 1, "otp_verified": 0, "status": "pending"},
        {"_id": 0}
    )


# ─────────────────────────────────────────────────────────────────────────────
# PAYMENTS
# ─────────────────────────────────────────────────────────────────────────────

def create_payment(user_id: int, amount: float, utr: str | None) -> int:
    pid = next_id("pay_id")
    col("payments").insert_one({
        "pay_id":      pid,
        "id":          pid,          # alias
        "user_id":     user_id,
        "amount":      amount,
        "utr":         utr,
        "status":      "pending",
        "created_at":  now_str(),
        "reviewed_at": None
    })
    return pid


def get_payment(pay_id: int) -> dict | None:
    return col("payments").find_one(
        {"$or": [{"pay_id": pay_id}, {"id": pay_id}]},
        {"_id": 0}
    )


def update_payment_status(pay_id: int, status: str):
    col("payments").update_one(
        {"$or": [{"pay_id": pay_id}, {"id": pay_id}]},
        {"$set": {"status": status, "reviewed_at": now_str()}}
    )




def pending_payments() -> list[dict]:
    docs = col("payments").find(
        {"status": "pending"},
        {"_id": 0},
        sort=[("created_at", ASCENDING)]
    )
    return list(docs)


# ─────────────────────────────────────────────────────────────────────────────
# COUNTRY PRICES
# ─────────────────────────────────────────────────────────────────────────────

def set_country_price(country: str, price: float):
    col("country_prices").update_one(
        {"country": country},
        {"$set": {"price": price}},
        upsert=True
    )


def get_country_price(country: str) -> float:
    doc = col("country_prices").find_one({"country": country}, {"_id": 0})
    return doc["price"] if doc else 50.0


# ── Init on import ────────────────────────────────────────────────────────────
init_db()


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN — NEW FEATURES
# ─────────────────────────────────────────────────────────────────────────────

def get_active_buyers() -> list[dict]:
    """
    All users who have at least one order.
    Returns user profile + total orders + total spent.
    """
    pipeline = [
        {"$group": {
            "_id":         "$user_id",
            "total_orders": {"$sum": 1},
            "total_spent":  {"$sum": "$price"},
            "last_order":   {"$max": "$ordered_at"}
        }},
        {"$lookup": {
            "from":         "users",
            "localField":   "_id",
            "foreignField": "user_id",
            "as":           "user"
        }},
        {"$unwind": {"path": "$user", "preserveNullAndEmptyArrays": True}},
        {"$project": {
            "_id":          0,
            "user_id":      "$_id",
            "full_name":    {"$ifNull": ["$user.full_name", "Unknown"]},
            "username":     {"$ifNull": ["$user.username", ""]},
            "balance":      {"$ifNull": ["$user.balance", 0]},
            "total_orders": 1,
            "total_spent":  1,
            "last_order":   1
        }},
        {"$sort": {"total_orders": -1}}
    ]
    return list(col("orders").aggregate(pipeline))


def get_available_accounts_list() -> list[dict]:
    """All unsold (available/reserved) accounts with full details."""
    docs = col("accounts").find(
        {"is_sold": 0},
        {"_id": 0},
        sort=[("country", ASCENDING), ("account_id", ASCENDING)]
    )
    return list(docs)


def get_sold_accounts_list() -> list[dict]:
    """
    All sold accounts joined with their order details.
    Shows who bought, when, and at what price.
    """
    pipeline = [
        {"$match": {"is_sold": 1}},
        {"$lookup": {
            "from":         "orders",
            "localField":   "account_id",
            "foreignField": "account_id",
            "as":           "order"
        }},
        {"$unwind": {"path": "$order", "preserveNullAndEmptyArrays": True}},
        {"$lookup": {
            "from":         "users",
            "localField":   "order.user_id",
            "foreignField": "user_id",
            "as":           "buyer"
        }},
        {"$unwind": {"path": "$buyer", "preserveNullAndEmptyArrays": True}},
        {"$project": {
            "_id":       0,
            "account_id": 1,
            "country":   1,
            "data":      1,
            "added_at":  1,
            "buyer_id":       {"$ifNull": ["$order.user_id",      "N/A"]},
            "buyer_name":     {"$ifNull": ["$buyer.full_name",    "Unknown"]},
            "buyer_username": {"$ifNull": ["$buyer.username",     ""]},
            "price":          {"$ifNull": ["$order.price",        0]},
            "sold_at":        {"$ifNull": ["$order.ordered_at",   "N/A"]},
            "otp_sent":       {"$ifNull": ["$order.otp_sent",     0]}
        }},
        {"$sort": {"sold_at": DESCENDING}}
    ]
    return list(col("accounts").aggregate(pipeline))


def get_all_country_prices() -> list[dict]:
    """All country prices sorted alphabetically."""
    docs = col("country_prices").find({}, {"_id": 0}, sort=[("country", ASCENDING)])
    return list(docs)


def get_accounts_stats() -> dict:
    """Quick summary counts for admin overview."""
    total     = col("accounts").count_documents({})
    available = col("accounts").count_documents({"is_sold": 0, "status": {"$nin": ["dead", "reserved"]}})
    reserved  = col("accounts").count_documents({"status": "reserved"})
    sold      = col("accounts").count_documents({"is_sold": 1})
    dead      = col("accounts").count_documents({"status": "dead"})
    buyers    = len(col("orders").distinct("user_id"))
    revenue   = col("orders").aggregate([{"$group": {"_id": None, "total": {"$sum": "$price"}}}])
    rev_list  = list(revenue)
    total_rev = rev_list[0]["total"] if rev_list else 0.0
    return {
        "total": total, "available": available, "reserved": reserved,
        "sold": sold, "dead": dead, "buyers": buyers, "revenue": total_rev
    }
