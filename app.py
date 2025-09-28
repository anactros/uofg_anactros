import streamlit as st
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Optional
import itertools
import threading
import time

st.set_page_config(page_title="Live LOB Classroom", layout="wide")

# ---------- Core data models ----------
order_id_counter = itertools.count(1)
trade_id_counter = itertools.count(1)

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
        # For correct priority we keep sort keys inside the order book
        self.sort_index = self.ts

@dataclass
class Trade:
    id: int
    price: float
    qty: int
    buy_order_id: int
    sell_order_id: int
    ts: float

# ---------- LOB engine with price then time priority and partial fills ----------
class OrderBook:
    def __init__(self):
        self.lock = threading.Lock()
        self.bids: List[Order] = []    # sorted by price desc then time asc
        self.asks: List[Order] = []    # sorted by price asc then time asc
        self.trades: List[Trade] = []
        self.active = True
        self.instructor_pin = "1234"   # change in class

    def _sort_books(self):
        self.bids.sort(key=lambda o: (-o.price, o.ts))
        self.asks.sort(key=lambda o: (o.price, o.ts))

    def reset(self):
        with self.lock:
            self.bids.clear()
            self.asks.clear()
            self.trades.clear()

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

    def cancel_order(self, order_id: int, user: Optional[str] = None, force: bool = False) -> bool:
        with self.lock:
            for book in (self.bids, self.asks):
                for i, o in enumerate(book):
                    if o.id == order_id and (force or user is None or o.user == user):
                        del book[i]
                        return True
        return False

    def _match(self):
        # While best bid crosses best ask execute trades
        self._sort_books()
        while self.bids and self.asks and self.bids[0].price >= self.asks[0].price:
            buy = self.bids[0]
            sell = self.asks[0]
            qty = min(buy.qty, sell.qty)
            price = sell.price if sell.ts <= buy.ts else sell.price  # pay ask by default

            t = Trade(
                id=next(trade_id_counter),
                price=price,
                qty=qty,
                buy_order_id=buy.id,
                sell_order_id=sell.id,
                ts=time.time()
            )
            self.trades.insert(0, t)  # newest first

            buy.qty -= qty
            sell.qty -= qty

            if buy.qty == 0:
                self.bids.pop(0)
            if sell.qty == 0:
                self.asks.pop(0)

            self._sort_books()

    # Convenience views
    def bids_df(self):
        with self.lock:
            return pd.DataFrame(
                [{"ID": o.id, "Trader": o.user, "Price": o.price, "Qty": o.qty, "Time": pd.to_datetime(o.ts, unit="s")} for o in self.bids]
            )

    def asks_df(self):
        with self.lock:
            return pd.DataFrame(
                [{"ID": o.id, "Trader": o.user, "Price": o.price, "Qty": o.qty, "Time": pd.to_datetime(o.ts, unit="s")} for o in self.asks]
            )

    def trades_df(self, limit=30):
        with self.lock:
            rows = self.trades[:limit]
            return pd.DataFrame(
                [{"Trade": t.id, "Price": t.price, "Qty": t.qty, "Buy ID": t.buy_order_id, "Sell ID": t.sell_order_id, "Time": pd.to_datetime(t.ts, unit="s")} for t in rows]
            )

# A single shared book for the whole app session
@st.cache_resource
def get_order_book():
    return OrderBook()

book = get_order_book()

# ---------- UI ----------
st.title("Live Limit Order Book")

# Left column for order entry, right columns for live book and trades
c1, c2 = st.columns([1, 2])

with c1:
    st.subheader("Submit order")
    user = st.text_input("Your name or alias")
    side = st.selectbox("Side", ["BUY", "SELL"])
    price = st.number_input("Limit price", min_value=0.0, value=100.0, step=0.5)
    qty = st.number_input("Quantity", min_value=1, value=1, step=1)
    if st.button("Place order", use_container_width=True, disabled=(not user)):
        book.add_order(user=user.strip() or "Anon", side=side, price=price, qty=qty)
        st.success("Order accepted")

    st.divider()
    st.subheader("Cancel your order")
    cancel_id = st.number_input("Order ID to cancel", min_value=1, step=1)
    if st.button("Cancel order", use_container_width=True):
        ok = book.cancel_order(int(cancel_id), user=user or None, force=False)
        st.success("Order cancelled") if ok else st.warning("Order not found or not yours")

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
    st.subheader("Order book")
    b1, b2 = st.columns(2)
    with b1:
        st.caption("Bids highest price first")
        bids_df = book.bids_df()
        st.dataframe(bids_df, use_container_width=True, height=350)
    with b2:
        st.caption("Asks lowest price first")
        asks_df = book.asks_df()
        st.dataframe(asks_df, use_container_width=True, height=350)

    st.subheader("Recent trades")
    st.dataframe(book.trades_df(), use_container_width=True, height=260)

# Light auto refresh so the screen updates while students trade
from streamlit_autorefresh import st_autorefresh

# Auto-refresh every 2 seconds (2000 ms)
st_autorefresh(interval=2000, limit=None, key="refresh")

