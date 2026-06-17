import duckdb, os
db = "/tmp/aegis_demo.db"
if os.path.exists(db): os.remove(db)
con = duckdb.connect(db)
con.execute("CREATE TABLE orders AS SELECT i AS order_id, 'placed' AS status, i * 9.99 AS revenue FROM range(1, 10001) t(i)")
con.execute("UPDATE orders SET order_id = NULL WHERE order_id % 200 = 0")
con.execute("UPDATE orders SET revenue = -5.00 WHERE order_id % 500 = 0")
print("Demo DB ready — 10,000 orders, 50 nulls, 20 bad revenue rows")
con.close()
