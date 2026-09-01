"""Сличительная ведомость бара -> обезличенная витрина для страницы кейса.

Исходный файл — реальная выгрузка заведения. В репозиторий он не попадает:
скрипт принимает путь к нему аргументом, а наружу отдаёт только доли и проценты.

Что убирается: название организации и предприятия, абсолютные суммы и цены.
Все деньги пересчитаны в проценты от стоимости учётного остатка склада,
поэтому по витрине нельзя восстановить ни закупочные цены, ни обороты.

    python3 case-bar/prepare.py "путь/к/ведомости.xlsx"
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent / "output"
COLS = ["n", "name", "code", "unit", "price", "fact_qty", "fact_sum",
        "calc_qty", "calc_sum", "surp_qty", "surp_sum", "short_qty", "short_sum", "comment"]

CATEGORIES = [
    ("Чай", lambda n: n.startswith("чай")),
    ("Кофе", lambda n: "кофе" in n),
    ("Алкоголь", lambda n: any(k in n for k in (
        "вино", "виски", "ром ", "джин", "водка", "текила", "ликер", "ликёр",
        "вермут", "коньяк", "бренди", "настойка", "пиво", "сидр", "игр."))),
    ("Молочное", lambda n: any(k in n for k in ("молоко", "сливки", "молочн", "йогурт", "сыр"))),
    ("Сиропы и добавки", lambda n: any(k in n for k in ("сироп", "кислота", "сахар", "мед", "мёд", "пюре"))),
    ("Безалкогольные", lambda n: any(k in n for k in (
        "булл", "напиток", "кола", "тоник", "вода", "сок", "лимонад", "швепс"))),
    ("Фрукты, ягоды и прочее", lambda n: True),
]

# комментарии кладовщика — свободный текст; сводим к причине, сам текст наружу не отдаём
CAUSES = [
    ("Списание проведено после закрытия смены", lambda c: "списали" in c and "час" in c),
    ("Приход не внесён в систему", lambda c: "пришел" in c or "пришёл" in c),
    ("Не списано на проработку или комплимент", lambda c: "проработ" in c or "комплимент" in c),
    ("Расхождение с прошлой инвентаризацией", lambda c: "инвент" in c),
]


def category(name):
    low = name.lower()
    return next(label for label, rule in CATEGORIES if rule(low))


def cause(comment):
    low = str(comment).lower()
    return next((label for label, rule in CAUSES if rule(low)), None)


def main():
    src = Path(sys.argv[1] if len(sys.argv) > 1 else
               Path(__file__).resolve().parents[2] / "Бар на пересчёт Июль.xlsx")
    d = pd.read_excel(src, header=None, skiprows=12, names=COLS)
    d = d[d["code"].notna()].copy()
    d[["surp_sum", "short_sum"]] = d[["surp_sum", "short_sum"]].fillna(0)

    # валовое расхождение — сумма модулей: излишки и недостачи не гасят друг друга
    d["gross"] = d["surp_sum"] + d["short_sum"]
    d["net"] = d["surp_sum"] - d["short_sum"]
    d["cat"] = d["name"].map(category)

    stock = d["calc_sum"].sum()          # стоимость учётного остатка = база индекса, 100%
    share = lambda v: round(100 * v / stock, 2)

    by_cat = d.groupby("cat").agg(
        items=("name", "count"), stock=("calc_sum", "sum"),
        gross=("gross", "sum"), net=("net", "sum")).reset_index()
    by_cat = by_cat.sort_values("gross", ascending=False)

    negative = d[d["calc_qty"] < 0].sort_values("calc_sum")
    causes = [c for c in d["comment"].dropna().map(cause) if c]

    findings = {
        "totals": {
            "items": len(d),
            "with_gap": int((d["gross"] > 0).sum()),
            "gross_share": share(d["gross"].sum()),
            "net_share": share(d["net"].sum()),
            "surplus_share": share(d["surp_sum"].sum()),
            "shortage_share": share(d["short_sum"].sum()),
            "negative_stock": int((d["calc_qty"] < 0).sum()),
        },
        "top": [
            {"name": r["name"], "cat": r["cat"], "share": share(r["gross"]),
             "kind": "излишки" if r["net"] > 0 else "недостача",
             "of_own": None if r["calc_sum"] <= 0 else round(100 * r["gross"] / r["calc_sum"], 1)}
            for _, r in d.nlargest(12, "gross").iterrows()
        ],
        "top_concentration": round(100 * d.nlargest(10, "gross")["gross"].sum() / d["gross"].sum()),
        "categories": [
            {"cat": r["cat"], "items": int(r["items"]), "stock_share": share(r["stock"]),
             "gap_share": round(100 * r["gross"] / d["gross"].sum(), 1),
             "net_share": share(r["net"]),
             "of_own": None if r["stock"] <= 0 else round(100 * r["gross"] / r["stock"], 1)}
            for _, r in by_cat.iterrows()
        ],
        "negative": [
            {"name": r["name"], "qty": round(r["calc_qty"], 3), "unit": r["unit"],
             "share": share(abs(r["calc_sum"]))}
            for _, r in negative.iterrows()
        ],
        "causes": [{"cause": c, "items": causes.count(c)} for c in dict.fromkeys(causes)],
        "commented": int(d["comment"].notna().sum()),
    }

    OUT.mkdir(exist_ok=True)
    payload = json.dumps(findings, ensure_ascii=False)
    (OUT / "findings.js").write_text("window.BAR = " + payload + ";\n", encoding="utf-8")

    t = findings["totals"]
    print(f"позиций: {t['items']}, с расхождением: {t['with_gap']}")
    print(f"валовое расхождение: {t['gross_share']}% стоимости остатка (нетто {t['net_share']}%)")
    print(f"отрицательных учётных остатков: {t['negative_stock']}")
    print(f"топ-10 позиций дают {findings['top_concentration']}% расхождения")
    for c in findings["causes"]:
        print(f"  {c['items']} × {c['cause']}")
    print(f"\nвитрина: {(OUT / 'findings.js').relative_to(OUT.parents[1])}")


if __name__ == "__main__":
    main()
