"""Считает витрины кейса: SQL -> pandas -> output/findings.json + текстовый отчёт.

Запросы живут в queries.sql и разделены комментарием `-- name: <ключ>`.
Здесь только то, что в SQL выражать неудобно: RFM-сегменты и матрица когорт.
"""
import json
import re
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
DB = ROOT.parent / "data" / "retail.db"
OUT = ROOT / "output"

# RFM: сегмент задаётся парой (recency-балл, объединённый балл frequency+monetary).
# Классическая сетка 5x5, свёрнутая до семи понятных бизнесу групп.
SEGMENTS = [
    ("Чемпионы",        lambda r, fm: r >= 4 and fm >= 4),
    ("Лояльные",        lambda r, fm: r >= 3 and fm >= 3),
    ("Перспективные",   lambda r, fm: r >= 4 and fm <= 2),
    ("Уходящие",        lambda r, fm: r == 3 and fm <= 2),
    ("В зоне риска",    lambda r, fm: r == 2 and fm >= 3),
    ("Спящие",          lambda r, fm: r == 2),
    ("Потерянные",      lambda r, fm: True),
]


def load_queries():
    text = (ROOT / "queries.sql").read_text(encoding="utf-8")
    blocks = re.split(r"^-- name: (\w+)$", text, flags=re.M)[1:]
    return dict(zip(blocks[::2], blocks[1::2]))


def segment(r, fm):
    return next(name for name, rule in SEGMENTS if rule(r, fm))


def rfm_table(rfm):
    q = lambda s, rev: pd.qcut(s.rank(method="first"), 5, labels=range(5, 0, -1) if rev else range(1, 6)).astype(int)
    rfm["r"] = q(rfm["recency"], True)
    rfm["f"] = q(rfm["frequency"], False)
    rfm["m"] = q(rfm["monetary"], False)
    rfm["fm"] = ((rfm["f"] + rfm["m"]) / 2).round().astype(int)
    rfm["segment"] = [segment(r, fm) for r, fm in zip(rfm["r"], rfm["fm"])]

    agg = rfm.groupby("segment").agg(
        customers=("customer_id", "count"),
        revenue=("monetary", "sum"),
        per_customer=("monetary", "mean"),
        recency=("recency", "median"),
    ).round(0).reset_index()
    agg["revenue_share"] = (agg["revenue"] / agg["revenue"].sum()).round(4)
    order = [name for name, _ in SEGMENTS]
    return agg.sort_values("segment", key=lambda s: s.map(order.index))


def cohort_matrix(raw):
    raw["offset"] = (
        (pd.to_datetime(raw["month"]).dt.year - pd.to_datetime(raw["cohort"]).dt.year) * 12
        + (pd.to_datetime(raw["month"]).dt.month - pd.to_datetime(raw["cohort"]).dt.month)
    )
    size = raw[raw["offset"] == 0].set_index("cohort")["customers"]
    raw["retention"] = (raw["customers"] / raw["cohort"].map(size)).round(4)
    wide = raw.pivot(index="cohort", columns="offset", values="retention")
    # последние когорты видны 1-2 месяца — по ним ретеншн не о чем говорить
    wide = wide[size.reindex(wide.index) >= 20]
    wide = wide[wide.drop(columns=0).notna().any(axis=1)]
    return wide, size.reindex(wide.index)


def main():
    q = load_queries()
    with sqlite3.connect(DB) as con:
        data = {k: pd.read_sql(v, con) for k, v in q.items()}
        totals = pd.read_sql("""
            SELECT ROUND(SUM(revenue),2) AS revenue,
                   COUNT(DISTINCT CASE WHEN NOT is_return THEN invoice END) AS invoices,
                   COUNT(DISTINCT customer_id) AS customers,
                   COUNT(DISTINCT stock_code) AS skus,
                   MIN(date(ts)) AS first_day, MAX(date(ts)) AS last_day
            FROM sales""", con).iloc[0].to_dict()

    totals["avg_check"] = round(totals["revenue"] / totals["invoices"], 2)

    abc = data["abc"]
    abc_summary = abc.groupby("class").agg(skus=("stock_code", "count"), revenue=("revenue", "sum")).reset_index()
    abc_summary["sku_share"] = (abc_summary["skus"] / abc_summary["skus"].sum()).round(4)
    abc_summary["revenue_share"] = (abc_summary["revenue"] / abc_summary["revenue"].sum()).round(4)

    rfm = rfm_table(data["rfm"])
    cohorts, cohort_size = cohort_matrix(data["cohorts"])

    ret = data["returns"]
    ret["rate"] = (ret["returned"] / ret["gross"]).round(4)

    OUT.mkdir(exist_ok=True)
    findings = {
        "totals": totals,
        "cleaning": json.loads((OUT / "cleaning.json").read_text(encoding="utf-8")),
        "monthly": data["monthly"].to_dict("records"),
        "pareto": [
            {"rank": int(r.rn), "cum_share": float(r.cum_share)}
            for r in abc.iloc[:: max(1, len(abc) // 300)].itertuples()
        ],
        "abc": abc_summary.to_dict("records"),
        "abc_top": abc.head(10)[["description", "revenue", "class"]].to_dict("records"),
        "rfm": rfm.to_dict("records"),
        "cohorts": {
            "labels": list(cohorts.index),
            "size": [int(x) for x in cohort_size],
            "matrix": [[None if pd.isna(v) else float(v) for v in row] for row in cohorts.values],
        },
        "returns": ret.to_dict("records"),
        "return_top": data["return_top"].assign(
            rate=lambda d: (d["returned"] / d["gross"]).round(4)
        ).head(8).to_dict("records"),
        "weekday_hour": data["weekday_hour"].to_dict("records"),
    }
    payload = json.dumps(findings, ensure_ascii=False)
    (OUT / "findings.json").write_text(payload, encoding="utf-8")
    # копия как js-файл: страница открывается и локально, без сервера
    (OUT / "findings.js").write_text("window.FINDINGS = " + payload + ";\n", encoding="utf-8")

    money = lambda x: f"{x:,.0f}".replace(",", " ")
    print(f"период: {totals['first_day']} — {totals['last_day']}")
    print(f"выручка: £{money(totals['revenue'])} · чеков: {money(totals['invoices'])} "
          f"· клиентов: {money(totals['customers'])} · средний чек: £{totals['avg_check']:.0f}")
    print("\nABC по товарам:")
    for r in abc_summary.itertuples():
        print(f"  {r._1}: {r.skus:>4} SKU ({r.sku_share:.1%} ассортимента) → {r.revenue_share:.1%} выручки")
    print("\nRFM-сегменты:")
    for r in rfm.itertuples():
        print(f"  {r.segment:<15} {r.customers:>5} клиентов · {r.revenue_share:>6.1%} выручки "
              f"· на клиента £{r.per_customer:>7,.0f}".replace(",", " "))
    print(f"\nвозвраты: {ret['returned'].sum() / ret['gross'].sum():.1%} от валовой выручки")
    m2 = cohorts[2].dropna() if 2 in cohorts else pd.Series(dtype=float)
    if len(m2):
        print(f"ретеншн на 3-й месяц: медиана {m2.median():.1%} по {len(m2)} когортам")
    print(f"\nвитрина: {(OUT / 'findings.json').relative_to(ROOT.parent)}")


if __name__ == "__main__":
    main()
