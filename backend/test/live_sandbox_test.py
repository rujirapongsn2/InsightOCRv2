"""
Live sandbox integration tests — requires Docker daemon running.
Run: DOCKER_HOST=unix://$HOME/.docker/run/docker.sock python test/live_sandbox_test.py
"""
import asyncio
import sys
from app.services.code_sandbox import execute_python


async def main():
    passed = 0
    failed = 0

    async def check(name: str, code: str, inputs: dict = None, expect_result=None, expect_error_type: str = None):
        nonlocal passed, failed
        r = await execute_python(code=code, inputs=inputs or {})
        ok = True
        if expect_result is not None:
            if r.get("result") != expect_result:
                print(f"  FAIL: expected result={expect_result}, got {r.get('result')}")
                ok = False
        if expect_error_type is not None:
            err = r.get("error") or {}
            if err.get("type") != expect_error_type:
                print(f"  FAIL: expected error={expect_error_type}, got {err.get('type')}")
                ok = False
        if ok:
            passed += 1
            print(f"  PASS")
        else:
            failed += 1
            print(f"  Full response: {r}")

    print("=== 1. Basic computation ===")
    await check("sum", "result = sum(inputs['nums'])", {"nums": [1,2,3,4,5]}, expect_result=15)

    print("=== 2. String processing ===")
    await check("reverse", "result = inputs['text'].upper()[::-1]", {"text": "hello world"}, expect_result="DLROW OLLEH")

    print("=== 3. Data filtering (quotation workflow) ===")
    await check("filter", """
items = inputs['items']
stock = inputs['stock']
in_stock = [i for i in items if stock[i['sku']]['qty'] >= i['qty']]
out_stock = [i for i in items if stock[i['sku']]['qty'] < i['qty']]
result = {'in_stock': len(in_stock), 'out_of_stock': [i['sku'] for i in out_stock]}
""", {
        "items": [{"sku": "A", "qty": 10}, {"sku": "B", "qty": 5}],
        "stock": {"A": {"qty": 50}, "B": {"qty": 0}},
    }, expect_result={"in_stock": 1, "out_of_stock": ["B"]})

    print("=== 4. User error captured ===")
    await check("value error", "raise ValueError('bad input')", expect_error_type="ValueError")

    print("=== 5. Division by zero with traceback ===")
    r = await execute_python(code="result = 1 / 0")
    err = r.get("error") or {}
    if err.get("type") == "ZeroDivisionError" and "traceback" in err:
        passed += 1
        print("  PASS (traceback captured)")
    else:
        failed += 1
        print(f"  FAIL: {r}")

    print("=== 6. JSON round-trip ===")
    await check("json", """
import json
data = json.loads(inputs['raw'])
data['count'] = len(data['items'])
data['processed'] = True
result = data
""", {"raw": '{"items": [1,2,3], "name": "test"}'},
    expect_result={"items": [1, 2, 3], "name": "test", "count": 3, "processed": True})

    print("=== 7. No result variable ===")
    await check("no result", "x = 1 + 1", expect_result=None)

    print("=== 8. Report generation (quotation workflow) ===")
    await check("report", """
items = inputs['items']
total = sum(i['qty'] * i['price'] for i in items)
lines = []
for i in items:
    lines.append(f"{i['name']}: {i['qty']} x {i['price']} = {i['qty'] * i['price']}")
result = {'report': '\\n'.join(lines), 'total': total}
""", {
        "items": [
            {"name": "Widget A", "qty": 10, "price": 500},
            {"name": "Widget C", "qty": 8, "price": 800},
        ]
    }, expect_result={"report": "Widget A: 10 x 500 = 5000\nWidget C: 8 x 800 = 6400", "total": 11400.0})

    print("=== 9. Large data processing ===")
    await check("large", """
result = {
    'count': len(inputs['records']),
    'sum': sum(r['value'] for r in inputs['records']),
    'avg': sum(r['value'] for r in inputs['records']) / max(len(inputs['records']), 1),
}
""", {"records": [{"value": i} for i in range(1, 1001)]},
    expect_result={"count": 1000, "sum": 500500, "avg": 500.5})

    print("=== 10. Network isolation ===")
    r = await execute_python(code="""
try:
    import urllib.request
    urllib.request.urlopen('http://example.com', timeout=5)
    result = 'NETWORK_ACCESSIBLE'
except Exception as e:
    result = f'BLOCKED: {type(e).__name__}'
""")
    if r.get("result", "").startswith("BLOCKED"):
        passed += 1
        print(f"  PASS: network blocked ({r['result']})")
    else:
        failed += 1
        print(f"  FAIL: network should be blocked, got {r}")

    print()
    print(f"{'='*50}")
    print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
    print(f"{'='*50}")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
