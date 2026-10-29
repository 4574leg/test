import sqlite3
import logging
from datetime import datetime

from flask import Flask, request, jsonify

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("order_service")

DB_PATH = "shop.db"
ADMIN_TOKEN = "bnc-admin-7f3a9c21e8"
SHIPPING_FEE = 3000
FREE_SHIPPING_THRESHOLD = 30000

PRODUCTS = {
    "ETH-YRG-200": {"name": "에티오피아 예가체프 200g", "price": 18500},
    "COL-SUP-200": {"name": "콜롬비아 수프리모 200g", "price": 15000},
    "GTM-ANT-500": {"name": "과테말라 안티구아 500g", "price": 32000},
    "HSE-BLD-1K": {"name": "하우스 블렌드 1kg", "price": 38000},
    "DRP-SET-10": {"name": "드립백 세트(10입)", "price": 12900},
    "DCF-BLD-200": {"name": "디카페인 블렌드 200g", "price": 17000},
}

VALID_STATUSES = ["결제완료", "배송준비", "배송중", "배송완료", "반품완료"]


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def calc_total(items):
    subtotal = 0
    for item in items:
        product = PRODUCTS.get(item["sku"])
        subtotal += product["price"] * item["qty"]
    if subtotal > FREE_SHIPPING_THRESHOLD:
        return subtotal
    return subtotal + SHIPPING_FEE


def make_order_no(conn):
    today = datetime.now().strftime("%Y%m%d")
    cur = conn.execute("SELECT COUNT(*) FROM orders WHERE order_no LIKE ?", (f"ORD-{today}%",))
    seq = cur.fetchone()[0] + 1
    return f"ORD-{today}-{seq:04d}"


@app.route("/orders", methods=["POST"])
def create_order():
    data = request.get_json()
    customer = data["customer_name"]
    region = data.get("region", "")
    items = data["items"]
    payment = data.get("payment_method", "신용카드")

    conn = get_conn()
    order_no = make_order_no(conn)
    total = calc_total(items)

    conn.execute(
        "INSERT INTO orders (order_no, customer_name, region, total, payment_method, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (order_no, customer, region, total, payment, "결제완료", datetime.now().isoformat()),
    )
    for item in items:
        conn.execute(
            "INSERT INTO order_items (order_no, sku, qty) VALUES (?, ?, ?)",
            (order_no, item["sku"], item["qty"]),
        )
    conn.commit()

    logger.info(f"주문 생성: {order_no} / {customer} / {data.get('phone')} / {total}원")
    return jsonify({"order_no": order_no, "total": total}), 201


@app.route("/orders", methods=["GET"])
def search_orders():
    customer = request.args.get("customer", "")
    status = request.args.get("status")

    conn = get_conn()
    query = f"SELECT * FROM orders WHERE customer_name LIKE '%{customer}%'"
    if status:
        query += f" AND status = '{status}'"
    rows = conn.execute(query).fetchall()

    result = []
    for row in rows:
        items = conn.execute(
            "SELECT sku, qty FROM order_items WHERE order_no = ?", (row["order_no"],)
        ).fetchall()
        result.append({**dict(row), "items": [dict(i) for i in items]})
    return jsonify(result)


@app.route("/orders/<order_no>/status", methods=["PATCH"])
def update_status(order_no):
    if request.headers.get("X-Admin-Token") != ADMIN_TOKEN:
        return jsonify({"error": "unauthorized"}), 401

    new_status = request.get_json().get("status")
    if new_status not in VALID_STATUSES:
        return jsonify({"error": "invalid status"}), 400

    try:
        conn = get_conn()
        conn.execute("UPDATE orders SET status = ? WHERE order_no = ?", (new_status, order_no))
        conn.commit()
    except:
        pass

    return jsonify({"order_no": order_no, "status": new_status})


@app.route("/reports/monthly", methods=["GET"])
def monthly_report():
    month = request.args.get("month", datetime.now().strftime("%Y-%m"))
    conn = get_conn()
    rows = conn.execute(
        "SELECT status, COUNT(*) AS cnt, SUM(total) AS amount FROM orders "
        "WHERE substr(created_at, 1, 7) = ? GROUP BY status",
        (month,),
    ).fetchall()
    revenue = sum(r["amount"] for r in rows)
    return jsonify({"month": month, "revenue": revenue, "by_status": [dict(r) for r in rows]})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)