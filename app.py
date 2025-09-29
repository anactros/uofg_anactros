import streamlit as st
import pandas as pd
from dataclasses import dataclass, field
from typing import List
import itertools
import threading
import time

st.set_page_config(page_title="Live LOB Classroom", layout="wide")
from streamlit_autorefresh import st_autorefresh

# Refresh every 3 seconds
st_autorefresh(interval=5000, key="orderbook_refresh")


# ---------- Simulation Parameters ----------
START_CASH = 300.0
START_ASSETS = 3
FUNDAMENTAL_DEFAULT = 100.0

# ---------- IDs ----------
order_id_counter = itertools.count(1)
trade_id_counter = itertools.count(1)

# ---------- Core data models ----------
@dataclass(order=True)
class Order:
    sort_index: float = field(init=False, repr=False)
    id: int
    user: str
    side: str           # "BUY" or "SELL"
    price: float
    qty: int
    ts: float           # submit time

    def __post_init__(self):
        self.sort_index = self.ts

@dataclass
class Trade:
    id: int
    price: float
    qty: int
    buy_order_id: int
    sell_order_id: int
    ts: float

# ---------- Holdings (cash + assets) ----------
@st.cache_resource
def get_holdings():
    return {}

holdings = get_holdings()

def ensure_user(user):
    if user not in holdings:
        holdings[user] = {"cash": START_CASH, "assets": START_ASSETS}

def update_holdings(buy_user, sell_user, price, qty):
    ensure_user(buy_user)
    ensure_user(sell_user)

    # Buyer
    holdings[buy_user]["cash"] -= price * qty
    holdings[buy_user]["assets"] += qty

    # Seller
    holdings[sell_user]["cash"] += price * qty
    holdings[sell_user]["assets"] -= qty

# ---------- OrderBook ----------
class OrderBook:
    def __init__(self):
        self.lock = threading.Lock()
        self.bids: List[Order] = []
        self.asks: List[Order] = []
        self.trades: List[Trade] = []
        self.instructor_pin = "010308"   # change for class

    def _sort_books(self):
        self.bids.sort(key=lambda o: (-o.price, o.ts))
        self.asks.sort(key=lambda o: (o.price, o.ts))

    def reset(self):
        with self.lock:
            self.bids.clear()
            self.asks.clear()
            self.trades.clear()
            holdings.clear()

    def add_order(self, user: str, side: str, price: float, qty: int) -> Order:
        with self.lock:
            o = Order(
                id=next(order_id_counter),
                user=user,
                side=side.upper(),
                price=float(price),
                qty=int(qty),
                ts=time.time()
            )
            book = self.bids if o.side == "BUY" else self.asks
            book.append(o)
            self._sort_books()
            self._match()
            return o


    def _match(self):
        self._sort_books()
        while self.bids and self.asks and self.bids[0].price >= self.asks[0].price:
            buy = self.bids[0]
            sell = self.asks[0]
            qty = min(buy.qty, sell.qty)
            price = sell.price  # trade at the ask

            t = Trade(
                id=next(trade_id_counter),
                price=price,
                qty=qty,
                buy_order_id=buy.id,
                sell_order_id=sell.id,
                ts=time.time()
            )
            self.trades.insert(0, t)

            # Update holdings
            update_holdings(buy.user, sell.user, price, qty)

            buy.qty -= qty
            sell.qty -= qty

            if buy.qty == 0:
                self.bids.pop(0)
            if sell.qty == 0:
                self.asks.pop(0)

            self._sort_books()

    # Views
    def bids_df(self):
        return pd.DataFrame(
            [{"ID": o.id, "Trader": o.user, "Price": o.price, "Qty": o.qty,
              "Time": pd.to_datetime(o.ts, unit="s")} for o in self.bids]
        )

    def asks_df(self):
        return pd.DataFrame(
            [{"ID": o.id, "Trader": o.user, "Price": o.price, "Qty": o.qty,
              "Time": pd.to_datetime(o.ts, unit="s")} for o in self.asks]
        )

    def trades_df(self, limit=30):
        rows = self.trades[:limit]
        return pd.DataFrame(
            [{"Trade": t.id, "Price": t.price, "Qty": t.qty,
              "Buy ID": t.buy_order_id, "Sell ID": t.sell_order_id,
              "Time": pd.to_datetime(t.ts, unit="s")} for t in rows]
        )

# Shared book instance
@st.cache_resource
def get_order_book():
    return OrderBook()

book = get_order_book()

# ---------- UI ----------
st.title("Live LOB ECON5143")

c1, c2 = st.columns([1, 2])

with c1:
    st.subheader("Submit Order")
    user = st.text_input("Your alias")
    side = st.selectbox("Side", ["BUY", "SELL"])
    price = st.number_input("Limit price", min_value=0.0, value=100.0, step=0.5)
    qty = 1  # fixed to 1
    if st.button("Place order", use_container_width=True, disabled=(not user)):
        book.add_order(user=user.strip() or "Anon", side=side, price=price, qty=qty)
        st.success("Order accepted")


    st.divider()
    with st.expander("Instructor controls"):
        pin = st.text_input("PIN", type="password")
        if st.button("Reset book", use_container_width=True):
            if pin == book.instructor_pin:
                book.reset()
                st.success("Order book reset")
            else:
                st.error("Wrong PIN")

with c2:
    st.subheader("Order Book")
    b1, b2 = st.columns(2)
    with b1:
        st.caption("Bids (highest price first)")
        st.dataframe(book.bids_df(), use_container_width=True, height=350)
    with b2:
        st.caption("Asks (lowest price first)")
        st.dataframe(book.asks_df(), use_container_width=True, height=350)

    st.subheader("Recent Trades")
    st.dataframe(book.trades_df(), use_container_width=True, height=260)

    st.subheader("Price Chart")
    if book.trades:
        df_chart = pd.DataFrame(
            [{"Time": pd.to_datetime(t.ts, unit="s"), "Price": t.price}
             for t in reversed(book.trades)]  # reversed = chronological order
        )
        st.line_chart(df_chart.set_index("Time"), height=250)
    else:
        st.info("No trades yet")


# ---------- Leaderboard ----------
st.divider()
with st.expander("Instructor Leaderboard (PIN required)"):
    pin = st.text_input("PIN", type="password", key="leaderboard_pin")
    if pin == book.instructor_pin:
        st.subheader("Leaderboard")
        fundamental_value = st.number_input(
            "Reveal fundamental value",
            min_value=0.0,
            value=FUNDAMENTAL_DEFAULT,
            step=0.1
        )
        if st.button("Compute Final Wealth"):
            initial_wealth = START_CASH + START_ASSETS * fundamental_value
            results = []
            for user, h in holdings.items():
                wealth = h["cash"] + h["assets"] * fundamental_value
                profit = wealth - initial_wealth
                results.append({
                    "Trader": user,
                    "Cash": round(h["cash"], 2),
                    "Assets": h["assets"],
                    "Final Wealth": round(wealth, 2),
                    "Profit": round(profit, 2)
                })
            df = pd.DataFrame(results).sort_values("Final Wealth", ascending=False)
            st.dataframe(df, use_container_width=True)
