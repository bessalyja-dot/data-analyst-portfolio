"""Сырой Excel -> чистая таблица в SQLite.

Датасет: UCI Online Retail II (онлайн-ритейл подарков, Великобритания,
01.12.2009 - 09.12.2011). Файл качается автоматически, в репозиторий не кладётся.

Все правила очистки собраны здесь и печатаются отчётом: сколько строк убрано
и почему. Это единственное место, где данные меняются.
"""
import json
import sqlite3
import urllib.request
from pathlib import Path

import pandas as pd

URL = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"
ROOT = Path(__file__).resolve().parent
RAW = ROOT.parent / "data" / "online_retail_II.xlsx"
DB = ROOT.parent / "data" / "retail.db"

# служебные позиции: доставка, ручные правки, банковские сборы, тесты
SERVICE_CODES = {"POST", "DOT", "D", "M", "C2", "BANK CHARGES", "AMAZONFEE", "S", "B", "CRUK"}


def download():
    if RAW.exists():
        return
    RAW.parent.mkdir(parents=True, exist_ok=True)
    zip_path = RAW.with_suffix(".zip")
    print("качаю датасет (~46 МБ)...")
    urllib.request.urlretrieve(URL, zip_path)
    import zipfile
    with zipfile.ZipFile(zip_path) as z:
        z.extract("online_retail_II.xlsx", RAW.parent)
    zip_path.unlink()


def load():
    sheets = pd.read_excel(RAW, sheet_name=None)
    df = pd.concat(sheets.values(), ignore_index=True)
    return df.rename(columns={
        "Invoice": "invoice", "StockCode": "stock_code", "Description": "description",
        "Quantity": "qty", "InvoiceDate": "ts", "Price": "price",
        "Customer ID": "customer_id", "Country": "country",
    })


def clean(df):
    log = []

    def drop(mask, reason):
        n = int(mask.sum())
        log.append((reason, n))
        return df[~mask]

    df["invoice"] = df["invoice"].astype(str).str.strip()
    df["stock_code"] = df["stock_code"].astype(str).str.strip().str.upper()

    # возврат = чек с префиксом C; помечаем, но не выбрасываем — это отдельный блок анализа
    df["is_return"] = df["invoice"].str.startswith("C")

    df = drop(df["customer_id"].isna(), "нет customer_id (розница без карты)")
    df = drop(df["stock_code"].isin(SERVICE_CODES), "служебные позиции (доставка, правки, сборы)")
    df = drop(df["stock_code"].str.contains("TEST", na=False), "тестовые записи")
    df = drop(df["price"] <= 0, "цена <= 0")
    df = drop((df["qty"] <= 0) & (~df["is_return"]), "нулевое/отрицательное количество вне возврата")
    df = drop(df.duplicated(subset=["invoice", "stock_code", "qty", "price", "ts"]), "полные дубли строк")

    df["customer_id"] = df["customer_id"].astype(int)
    df["revenue"] = (df["qty"] * df["price"]).round(2)
    df["ts"] = pd.to_datetime(df["ts"])
    return df, log


def main():
    download()
    raw = load()
    df, log = clean(raw)

    print(f"\nсырых строк: {len(raw):,}".replace(",", " "))
    for reason, n in log:
        print(f"  -{n:>9,}".replace(",", " ") + f" {reason}")
    kept = len(df) / len(raw)
    print(f"осталось: {len(df):,} ({kept:.1%})".replace(",", " "))

    (ROOT / "output").mkdir(exist_ok=True)
    (ROOT / "output" / "cleaning.json").write_text(json.dumps(
        {"raw": len(raw), "kept": len(df), "dropped": [{"reason": r, "rows": n} for r, n in log]},
        ensure_ascii=False), encoding="utf-8")

    DB.unlink(missing_ok=True)
    with sqlite3.connect(DB) as con:
        df.to_sql("sales", con, index=False)
        con.execute("CREATE INDEX idx_cust ON sales(customer_id)")
        con.execute("CREATE INDEX idx_ts ON sales(ts)")
    print(f"\nбаза: {DB.relative_to(ROOT.parent)}")


if __name__ == "__main__":
    main()
