-- Аналитические запросы кейса. Каждый блок отдаётся в analysis.py по имени
-- в комментарии `-- name: <ключ>`; ниже — обычный SQLite.

-- name: monthly
-- Выручка, чеки и клиенты по месяцам. Возвраты вычитаются из выручки,
-- но не считаются отдельным чеком.
SELECT strftime('%Y-%m', ts)                            AS month,
       ROUND(SUM(revenue), 2)                           AS revenue,
       COUNT(DISTINCT CASE WHEN NOT is_return THEN invoice END) AS invoices,
       COUNT(DISTINCT customer_id)                      AS customers
FROM sales
GROUP BY month
ORDER BY month;

-- name: abc
-- ABC по товарам: накопительная доля выручки через оконную функцию.
-- A — первые 80% выручки, B — до 95%, дальше C.
WITH product AS (
    SELECT stock_code,
           MAX(description)       AS description,
           ROUND(SUM(revenue), 2) AS revenue
    FROM sales
    WHERE NOT is_return
    GROUP BY stock_code
    HAVING revenue > 0
),
ranked AS (
    SELECT *,
           SUM(revenue) OVER (ORDER BY revenue DESC
                             ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
             / SUM(revenue) OVER () AS cum_share,
           ROW_NUMBER() OVER (ORDER BY revenue DESC) AS rn
    FROM product
)
SELECT stock_code, description, revenue, rn, ROUND(cum_share, 4) AS cum_share,
       CASE WHEN cum_share <= 0.80 THEN 'A'
            WHEN cum_share <= 0.95 THEN 'B'
            ELSE 'C' END AS class
FROM ranked
ORDER BY rn;

-- name: rfm
-- RFM: recency в днях от последней даты в базе, frequency — число чеков,
-- monetary — выручка за вычетом возвратов.
WITH last_day AS (SELECT MAX(ts) AS d FROM sales)
SELECT customer_id,
       CAST(julianday((SELECT d FROM last_day)) - julianday(MAX(ts)) AS INT) AS recency,
       COUNT(DISTINCT CASE WHEN NOT is_return THEN invoice END)              AS frequency,
       ROUND(SUM(revenue), 2)                                                AS monetary
FROM sales
GROUP BY customer_id
HAVING frequency > 0 AND monetary > 0;

-- name: cohorts
-- Когорты по месяцу первой покупки: сколько клиентов возвращается на N-й месяц.
WITH first_buy AS (
    SELECT customer_id, MIN(strftime('%Y-%m', ts)) AS cohort
    FROM sales WHERE NOT is_return GROUP BY customer_id
),
activity AS (
    SELECT DISTINCT s.customer_id, f.cohort, strftime('%Y-%m', s.ts) AS month
    FROM sales s JOIN first_buy f USING (customer_id)
    WHERE NOT s.is_return
)
SELECT cohort, month, COUNT(DISTINCT customer_id) AS customers
FROM activity
GROUP BY cohort, month
ORDER BY cohort, month;

-- name: returns
-- Возвраты: доля в деньгах по месяцам и топ товаров, которые возвращают чаще.
SELECT strftime('%Y-%m', ts) AS month,
       ROUND(SUM(CASE WHEN is_return THEN -revenue ELSE 0 END), 2) AS returned,
       ROUND(SUM(CASE WHEN NOT is_return THEN revenue ELSE 0 END), 2) AS gross
FROM sales
GROUP BY month
ORDER BY month;

-- name: return_top
SELECT stock_code,
       MAX(description) AS description,
       ROUND(SUM(CASE WHEN is_return THEN -revenue ELSE 0 END), 2) AS returned,
       ROUND(SUM(CASE WHEN NOT is_return THEN revenue ELSE 0 END), 2) AS gross
FROM sales
GROUP BY stock_code
HAVING gross > 5000
ORDER BY returned * 1.0 / gross DESC
LIMIT 15;

-- name: weekday_hour
-- Когда покупают: день недели x час. Нужен для расписания рассылок и поддержки.
SELECT CAST(strftime('%w', ts) AS INT) AS weekday,
       CAST(strftime('%H', ts) AS INT) AS hour,
       ROUND(SUM(revenue), 2)          AS revenue
FROM sales
WHERE NOT is_return
GROUP BY weekday, hour;
