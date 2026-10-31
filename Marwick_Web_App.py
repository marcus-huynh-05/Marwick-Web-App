import io
import pandas as pd
import streamlit as st
from datetime import date, timedelta

st.set_page_config(page_title="Marwick | Spending Insights", page_icon="◈", layout="wide")

CATEGORIES = [
    "Groceries", "Dining", "Transport", "Shopping", "Bills",
    "Housing", "Entertainment", "Health", "Income", "Transfer",
    "Refund", "Uncategorised"
]

def suggest_category(description: str, amount: float) -> str:
    text = str(description).lower()
    rules = {
        "Groceries": ["woolworths", "coles", "aldi", "iga", "grocery", "supermarket"],
        "Dining": ["restaurant", "cafe", "coffee", "mcdonald", "kfc", "uber eats", "doordash", "bakery"],
        "Transport": ["myki", "ptv", "uber", "taxi", "fuel", "petrol", "parking", "train"],
        "Shopping": ["amazon", "kmart", "target", "big w", "chemist warehouse", "ebay"],
        "Bills": ["electricity", "gas bill", "internet", "phone", "telstra", "optus", "water"],
        "Housing": ["rent", "real estate", "property"],
        "Entertainment": ["netflix", "spotify", "cinema", "movie", "steam"],
        "Health": ["pharmacy", "medical", "doctor", "dental", "chemist"],
        "Transfer": ["transfer", "osko", "payment to", "internal transfer"],
        "Refund": ["refund", "reversal", "return", "cashback"]
    }
    for category, keywords in rules.items():
        if any(keyword in text for keyword in keywords):
            return category
    if amount > 0:
        return "Income"
    return "Uncategorised"

def parse_amount(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.replace(r"[\$,]", "", regex=True)
        .str.replace(r"\((.*?)\)", r"-\1", regex=True)
        .str.strip()
    )
    return pd.to_numeric(cleaned, errors="coerce")

def spending_mask(df: pd.DataFrame) -> pd.Series:
    # Gross spending: count only negative outflows that are not transfers,
    # refunds, or income. Refunds are tracked separately below.
    return (df["amount"] < 0) & (~df["category"].isin(["Transfer", "Refund", "Income"]))


def refund_mask(df: pd.DataFrame) -> pd.Series:
    # A refund is identified by its category, and only positive inflows are
    # counted as money returned. Negative rows labelled Refund are excluded
    # from both spending and refund totals and should be reviewed.
    return (df["category"] == "Refund") & (df["amount"] > 0)


def calculate_period_metrics(frame: pd.DataFrame) -> dict:
    gross = float(frame.loc[spending_mask(frame), "amount"].abs().sum())
    refunds = float(frame.loc[refund_mask(frame), "amount"].sum())
    net = gross - refunds
    transfer_out = float(frame.loc[(frame["category"] == "Transfer") & (frame["amount"] < 0), "amount"].abs().sum())
    transfer_in = float(frame.loc[(frame["category"] == "Transfer") & (frame["amount"] > 0), "amount"].sum())
    income = float(frame.loc[(frame["category"] == "Income") & (frame["amount"] > 0), "amount"].sum())
    return {
        "gross_spending": gross,
        "refunds": refunds,
        "net_spending": net,
        "transfer_out": transfer_out,
        "transfer_in": transfer_in,
        "income": income,
    }


def category_gross_spending(frame: pd.DataFrame) -> pd.Series:
    mask = spending_mask(frame)
    expenses = frame.loc[mask].copy()
    expenses["expense_amount"] = expenses["amount"].abs()
    return expenses.groupby("category")["expense_amount"].sum()


def category_refunds(frame: pd.DataFrame) -> pd.Series:
    refunds = frame.loc[refund_mask(frame)].copy()
    # Refunds are shown under their own Refund category for transparency;
    # this avoids silently guessing which purchase category they belong to.
    if refunds.empty:
        return pd.Series(dtype=float)
    return refunds.assign(refund_amount=refunds["amount"].abs()).groupby("category")["refund_amount"].sum()

def fmt_money(value: float, currency: str) -> str:
    return f"{currency} {value:,.2f}"

st.title("◈ MARWICK")
st.caption("Financial intelligence for everyday life · Prototype v0.4")
st.info(
     "Prototype note: This version processes the uploaded CSV during the current app session. "
    "It does not connect to banks or provide financial advice. Confirm your CSV's amount-sign convention before relying on results. "
    "Net spending is calculated as gross spending minus positive transactions labelled Refund; refunds are assigned by transaction date."
)

with st.sidebar:
    st.header("Analysis settings")
    currency = st.selectbox("Currency for this file", ["AUD", "USD", "GBP", "EUR", "VND"], index=0)
    st.caption("One currency per file. No currency conversion is performed.")

uploaded = st.file_uploader("Upload transaction CSV", type=["csv"], help="CSV should contain transaction date, description and amount columns.")

if uploaded is None:
    st.subheader("Start with a CSV file")
    st.write("Upload a transaction export to compare two periods and see which categories contributed to the change.")
    st.markdown("**Expected fields:** transaction date · description · amount")
    st.markdown("You can try the sample file included in the project folder: `sample_transactions.csv`.")
    st.stop()

try:
    raw = pd.read_csv(uploaded)
except Exception as exc:
    st.error(f"Could not read this CSV. Please check the file format. Details: {exc}")
    st.stop()

if raw.empty:
    st.error("This CSV contains no rows.")
    st.stop()

st.subheader("1. Map your CSV columns")
columns = list(raw.columns)
c1, c2, c3 = st.columns(3)
with c1:
    date_col = st.selectbox("Date column", columns, index=0)
with c2:
    desc_options = columns
    desc_col = st.selectbox("Description column", desc_options, index=min(1, len(columns)-1))
with c3:
    amount_col = st.selectbox("Amount column", columns, index=min(2, len(columns)-1))

df = pd.DataFrame()
# Parse ISO dates (YYYY-MM-DD) first, then fall back to day-first formats
# such as DD/MM/YYYY. This prevents ISO dates from being misinterpreted.
date_values = raw[date_col].astype("string").str.strip()
parsed_dates = pd.to_datetime(date_values, format="%Y-%m-%d", errors="coerce")
needs_fallback = parsed_dates.isna()
if needs_fallback.any():
    parsed_dates.loc[needs_fallback] = pd.to_datetime(
        date_values.loc[needs_fallback], errors="coerce", dayfirst=True
    )
df["transaction_date"] = parsed_dates
df["description"] = raw[desc_col].astype(str).fillna("")
df["amount"] = parse_amount(raw[amount_col])

invalid_date = df["transaction_date"].isna()
invalid_amount = df["amount"].isna()
invalid = invalid_date | invalid_amount

st.write(f"Rows detected: **{len(df):,}** · Rows with invalid date or amount: **{int(invalid.sum()):,}**")
if invalid.any():
    with st.expander("Review rows that cannot be analysed"):
        st.dataframe(pd.concat([raw.loc[invalid].reset_index(drop=True), df.loc[invalid].reset_index(drop=True)], axis=1), use_container_width=True)
    st.warning("Invalid rows are excluded from calculations. Review them before relying on the analysis.")

df = df.loc[~invalid].copy()
if df.empty:
    st.error("No valid transactions remain after validation.")
    st.stop()

# Explicit starter assumption: negative = outflow/expense; positive = inflow.
st.warning("Amount convention: this prototype assumes negative amounts are money out and positive amounts are money in. If your bank uses the opposite convention, do not rely on the results yet.")

df["category"] = [
    suggest_category(desc, amount)
    for desc, amount in zip(df["description"], df["amount"])
]
df["transaction_date"] = df["transaction_date"].dt.date

st.subheader("2. Review and correct categories")
st.caption("Rule-based suggestions only. Review categories, especially Uncategorised, Transfer and Refund.")
edited = st.data_editor(
    df[["transaction_date", "description", "amount", "category"]],
    use_container_width=True,
    hide_index=True,
    num_rows="fixed",
    column_config={
        "transaction_date": st.column_config.DateColumn("Date", disabled=True),
        "description": st.column_config.TextColumn("Description", disabled=True),
        "amount": st.column_config.NumberColumn(f"Amount ({currency})", format="%.2f", disabled=True),
        "category": st.column_config.SelectboxColumn("Category", options=CATEGORIES, required=True),
    },
)
df["category"] = edited["category"].values

min_date = min(df["transaction_date"])
max_date = max(df["transaction_date"])
if min_date == max_date:
    st.error("The file only contains one transaction date. Upload data covering both comparison periods.")
    st.stop()

st.subheader("3. Choose two periods")
col_a, col_b = st.columns(2)
split_date = min_date + (max_date - min_date) // 2
default_a_end = max(min_date, split_date)
default_b_start = min(max_date, default_a_end + timedelta(days=1))
with col_a:
    st.markdown("**Period A — reference period**")
    st.caption("The period you use as the baseline for comparison.")
    a_start = st.date_input("Start date A", value=min_date, min_value=min_date, max_value=max_date, key="a_start")
    a_end = st.date_input("End date A", value=default_a_end, min_value=min_date, max_value=max_date, key="a_end")
with col_b:
    st.markdown("**Period B — comparison period**")
    st.caption("The period you compare against Period A.")
    b_start = st.date_input("Start date B", value=default_b_start, min_value=min_date, max_value=max_date, key="b_start")
    b_end = st.date_input("End date B", value=max_date, min_value=min_date, max_value=max_date, key="b_end")

if a_start > a_end or b_start > b_end:
    st.error("Each period's start date must be on or before its end date.")
    st.stop()
if not (a_end < b_start or b_end < a_start):
    st.error("The two periods overlap. Choose non-overlapping date ranges.")
    st.stop()

days_a = (a_end - a_start).days + 1
days_b = (b_end - b_start).days + 1
if days_a != days_b:
    st.warning(
        f"These periods have different lengths ({days_a} days vs {days_b} days). "
        "Total spending may not be directly comparable. Consider selecting periods of similar length."
    )

period_a = df[(df["transaction_date"] >= a_start) & (df["transaction_date"] <= a_end)].copy()
period_b = df[(df["transaction_date"] >= b_start) & (df["transaction_date"] <= b_end)].copy()

if period_a.empty or period_b.empty:
    st.warning("At least one period has no valid transactions. Choose date ranges that contain transactions in both periods.")
    st.stop()

metrics_a = calculate_period_metrics(period_a)
metrics_b = calculate_period_metrics(period_b)

gross_a = metrics_a["gross_spending"]
gross_b = metrics_b["gross_spending"]
refunds_a = metrics_a["refunds"]
refunds_b = metrics_b["refunds"]
net_a = metrics_a["net_spending"]
net_b = metrics_b["net_spending"]
change = net_b - net_a
pct = None if net_a == 0 else (change / net_a) * 100

cat_gross_a = category_gross_spending(period_a)
cat_gross_b = category_gross_spending(period_b)
cat_refunds_a = category_refunds(period_a)
cat_refunds_b = category_refunds(period_b)
all_categories = sorted(set(cat_gross_a.index) | set(cat_gross_b.index))
gross_comparison = pd.DataFrame(index=all_categories)
gross_comparison["period_a"] = cat_gross_a.reindex(all_categories, fill_value=0)
gross_comparison["period_b"] = cat_gross_b.reindex(all_categories, fill_value=0)
gross_comparison["change"] = gross_comparison["period_b"] - gross_comparison["period_a"]

st.subheader("4. Spending comparison")
st.caption("Net spending = gross spending − refunds. Transfers and income are excluded. Refunds are assigned to the period in which they appear in the CSV.")
m1, m2, m3 = st.columns(3)
m1.metric("Period A net spending", fmt_money(net_a, currency))
m2.metric("Period B net spending", fmt_money(net_b, currency))
m3.metric("Net change", fmt_money(change, currency), None if pct is None else f"{pct:+.1f}%")

detail_metrics = [("Period A gross", gross_a)]
if refunds_a > 0:
    detail_metrics.append(("Period A refund", refunds_a))
detail_metrics.append(("Period B gross", gross_b))
if refunds_b > 0:
    detail_metrics.append(("Period B refund", refunds_b))
detail_cols = st.columns(len(detail_metrics))
for col, (label, value) in zip(detail_cols, detail_metrics):
    col.metric(label, fmt_money(value, currency))

if pct is None:
    st.info("Percentage change is undefined because Period A net spending is zero.")
elif change > 0:
    st.write(f"Net spending increased by **{fmt_money(change, currency)}** ({pct:+.1f}%) from Period A to Period B.")
elif change < 0:
    st.write(f"Net spending decreased by **{fmt_money(abs(change), currency)}** ({pct:+.1f}%) from Period A to Period B.")
else:
    st.write("Net spending was unchanged between the selected periods.")

st.markdown("**Category contribution to gross spending change**")
st.caption("Positive values indicate higher gross outflows; negative values indicate lower gross outflows. Refunds are shown separately and are not silently netted into purchase categories.")
st.dataframe(
    gross_comparison.rename(columns={
        "period_a": f"Period A gross ({currency})",
        "period_b": f"Period B gross ({currency})",
        "change": f"Gross change ({currency})"
    }).style.format({
        f"Period A gross ({currency})": "{:,.2f}",
        f"Period B gross ({currency})": "{:,.2f}",
        f"Gross change ({currency})": "{:,.2f}"
    }),
    use_container_width=True
)

if refunds_a > 0 or refunds_b > 0:
    refund_summary = pd.DataFrame({
        "Period": [period_label for period_label, amount in [("Period A", refunds_a), ("Period B", refunds_b)] if amount > 0],
        f"Refunds ({currency})": [amount for amount in (refunds_a, refunds_b) if amount > 0],
    })
    with st.expander("View refund transactions and totals"):
        st.dataframe(refund_summary.style.format({f"Refunds ({currency})": "{:,.2f}"}), use_container_width=True, hide_index=True)
        refund_evidence = df[refund_mask(df) & (df["transaction_date"].between(a_start, a_end) | df["transaction_date"].between(b_start, b_end))].copy()
        if not refund_evidence.empty:
            refund_evidence["period"] = refund_evidence["transaction_date"].apply(lambda d: "Period A" if a_start <= d <= a_end else "Period B")
            st.dataframe(refund_evidence[["period", "transaction_date", "description", "amount", "category"]].sort_values("transaction_date"), use_container_width=True, hide_index=True)

chart_data = gross_comparison[["period_a", "period_b"]].copy()
chart_data.columns = ["Period A gross", "Period B gross"]
st.bar_chart(chart_data)

st.subheader("5. Evidence")
st.caption("Evidence is linked to the insight it supports. Open an insight below to inspect the underlying transactions and calculation.")

def show_category_evidence(category_name: str):
    evidence = df[
        (df["category"] == category_name)
        & (df["transaction_date"].between(a_start, a_end) | df["transaction_date"].between(b_start, b_end))
    ].copy()
    if evidence.empty:
        st.info("No matching transactions were found in the selected periods.")
        return
    evidence["period"] = evidence["transaction_date"].apply(lambda d: "Period A" if a_start <= d <= a_end else "Period B")
    evidence["amount"] = evidence["amount"].map(lambda x: round(float(x), 2))
    st.dataframe(
        evidence[["period", "transaction_date", "description", "amount", "category"]].sort_values(["period", "transaction_date"]),
        use_container_width=True,
        hide_index=True,
    )

st.subheader("6. Insight Engine v0.4")

if not gross_comparison.empty:
    increases = gross_comparison[gross_comparison["change"] > 0].sort_values("change", ascending=False)
    decreases = gross_comparison[gross_comparison["change"] < 0].sort_values("change", ascending=True)
    insight_cols = st.columns(2)

    if not increases.empty:
        category = str(increases.index[0])
        increase_amount = float(increases.iloc[0]["change"])
        with insight_cols[0]:
            with st.container(border=True):
                st.caption("SPENDING INCREASE")
                st.markdown(f"### {category}")
                st.metric("Gross spending change", fmt_money(increase_amount, currency))
                st.write(f"Gross spending in **{category}** was higher in Period B.")
                if gross_b - gross_a > 0:
                    share = increase_amount / (gross_b - gross_a) * 100
                    st.caption(f"{share:.1f}% of the overall increase in gross spending.")
                with st.expander("View evidence and calculation"):
                    a_value = float(gross_comparison.loc[category, "period_a"])
                    b_value = float(gross_comparison.loc[category, "period_b"])
                    st.write(f"Period A: **{fmt_money(a_value, currency)}** → Period B: **{fmt_money(b_value, currency)}**")
                    st.write(f"Calculation: {fmt_money(b_value, currency)} − {fmt_money(a_value, currency)} = **{fmt_money(increase_amount, currency)}**")
                    show_category_evidence(category)

    if not decreases.empty:
        category = str(decreases.index[0])
        decrease_amount = abs(float(decreases.iloc[0]["change"]))
        with insight_cols[1]:
            with st.container(border=True):
                st.caption("SPENDING DECREASE")
                st.markdown(f"### {category}")
                st.metric("Gross spending change", f"−{fmt_money(decrease_amount, currency)}")
                st.write(f"Gross spending in **{category}** was lower in Period B.")
                with st.expander("View evidence and calculation"):
                    a_value = float(gross_comparison.loc[category, "period_a"])
                    b_value = float(gross_comparison.loc[category, "period_b"])
                    st.write(f"Period A: **{fmt_money(a_value, currency)}** → Period B: **{fmt_money(b_value, currency)}**")
                    st.write(f"Calculation: {fmt_money(b_value, currency)} − {fmt_money(a_value, currency)} = **−{fmt_money(decrease_amount, currency)}**")
                    show_category_evidence(category)

    if gross_b > 0:
        category = str(gross_comparison["period_b"].idxmax())
        category_spend = float(gross_comparison.loc[category, "period_b"])
        share = category_spend / gross_b * 100
        with st.container(border=True):
            st.caption("PERIOD B · LARGEST CATEGORY")
            st.markdown(f"### {category}")
            st.metric("Share of gross spending", f"{share:.1f}%", fmt_money(category_spend, currency))
            with st.expander("View evidence and calculation"):
                st.write(f"{fmt_money(category_spend, currency)} ÷ {fmt_money(gross_b, currency)} = **{share:.1f}%** of Period B gross spending.")
                show_category_evidence(category)

    if refunds_a > 0 or refunds_b > 0:
        refund_change = refunds_b - refunds_a
        with st.container(border=True):
            st.caption("REFUND ACTIVITY")
            st.markdown("### Refunds recorded")
            refund_cols = st.columns(2)
            if refunds_a > 0:
                refund_cols[0].metric("Period A refund", fmt_money(refunds_a, currency))
            if refunds_b > 0:
                refund_cols[1 if refunds_a > 0 else 0].metric("Period B refund", fmt_money(refunds_b, currency))
            st.caption(f"Refund change: {fmt_money(refund_change, currency,)}")
            with st.expander("View refund evidence and calculation"):
                refund_evidence = df[refund_mask(df) & (df["transaction_date"].between(a_start, a_end) | df["transaction_date"].between(b_start, b_end))].copy()
                if not refund_evidence.empty:
                    refund_evidence["period"] = refund_evidence["transaction_date"].apply(lambda d: "Period A" if a_start <= d <= a_end else "Period B")
                    st.dataframe(refund_evidence[["period", "transaction_date", "description", "amount", "category"]].sort_values(["period", "transaction_date"]), use_container_width=True, hide_index=True)
                st.write("Net spending = gross spending − confirmed refunds recorded in the selected period.")
                st.write(f"Period A: {fmt_money(gross_a, currency)} − {fmt_money(refunds_a, currency)} = **{fmt_money(net_a, currency)}**")
                st.write(f"Period B: {fmt_money(gross_b, currency)} − {fmt_money(refunds_b, currency)} = **{fmt_money(net_b, currency)}**")
else:
    st.info("There are no eligible expense categories to compare in these periods.")

uncategorised_count = int((df["category"] == "Uncategorised").sum())
if uncategorised_count:
    st.warning(
        f"{uncategorised_count} transaction(s) remain Uncategorised. "
        "Review them because insights may be incomplete."
    )

st.caption("AI explanations are not connected in v0.3. This prototype first validates the data and calculation pipeline. Do not treat the output as financial advice.")
st.divider()
st.caption("Prototype limitation: this version does not yet implement a verified secure deletion workflow. Do not upload sensitive real financial data until storage, session isolation and deletion have been reviewed.")
