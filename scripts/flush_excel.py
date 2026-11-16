import json
import openpyxl

EXCEL_PATH = "/Users/cenbusi/Desktop/2743.xlsx"
PROGRESS_PATH = "/tmp/pdd_sourcing_progress.json"

wb = openpyxl.load_workbook(EXCEL_PATH)
ws = wb["门店商品"]
progress = json.load(open(PROGRESS_PATH))

count = 0
for row in range(49, 2792):
    r = progress.get(str(row))
    if r and r.get("status") == "MATCHED":
        ws.cell(row=row, column=3, value=r.get("main_pic", ""))
        ws.cell(row=row, column=6, value=r.get("goods_url", ""))
        ws.cell(row=row, column=7, value=r.get("sku_specs", ""))
        ws.cell(row=row, column=8, value=r.get("checkout_url", ""))
        ws.cell(row=row, column=9, value=int(r.get("ratio", 1)))
        ws.cell(row=row, column=10, value=round(float(r.get("group_price", 0)), 2))
        ws.cell(row=row, column=11, value=f"=ROUND(J{row}/I{row}, 2)")
        count += 1
    else:
        for col in [3, 6, 7, 8, 9, 10, 11]:
            ws.cell(row=row, column=col).value = None

wb.save(EXCEL_PATH)
print(f"[Excel] Synced {count} clean matched rows to {EXCEL_PATH} (cols={ws.max_column}).")
