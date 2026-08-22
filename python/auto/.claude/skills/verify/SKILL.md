---
name: verify
description: Verify changes to the web dashboard (python/auto/dashboard.py) by driving the HTTP server in isolation with a stub data source.
---

# Verify dashboard.py

The `Dashboard` HTTP server (port 40006) is self-contained — it does not
import the TDX/IBKR stack, so it can be driven standalone with a stub
`pdf` object. Its only data dependency is `pdf.GetDisplayDataFrame()`.

## Launch

```bash
cd python/auto
python - <<'PY'
import pandas as pd, time
from dashboard import Dashboard
class StubPDF:
    def GetDisplayDataFrame(self):
        return pd.DataFrame([{'代码':'SZ162411','对冲代码':'XOP','方向':'买入','时间':'09:30',
            '溢价':'0.5%','数量':100,'价格':1.5,'对冲数量':50,'对冲价格':136.47,'补充内容':''}])
Dashboard(StubPDF(), host='127.0.0.1', port=40206, token='tok').start()
time.sleep(3600)
PY
```

## Drive (raw socket, to control the `Host` header)

Send requests with a raw socket so you can set the `Host` header and
exercise the two behaviors this server implements:

1. **Local token bypass** — `Host` of `127.0.0.1` / `localhost` / `[::1]`
   returns `200` with no token; non-local `Host` (e.g.
   `xxx.trycloudflare.com`, `192.168.1.5`) returns `401` without
   `?token=`, and `200` with the correct `?token=tok`.
2. **Static hedge list** — `GET /` HTML must contain `var HEDGE_NAMES = {`
   (the injected mapping) and must NOT contain the `__HEDGE_NAMES_JSON__`
   placeholder.

## Frontend filter logic (Node)

The `<script>` block in the served HTML implements the category/hedge
filter. Extract it and drive it under Node with a tiny DOM stub (elements
backed by real `innerHTML`/`textContent`/`value` properties) — `eval` the
script, then set `allRows` to sample rows and call `populateCategoryFilter`,
`populateFilter`, `applyCategory`, `applyFilter`, asserting on the element
strings. Node `--check` also catches JS syntax errors before the harness.

## Gotchas

- The Windows console prints Chinese as garbled GBK; assert with
  `'标普油气2倍做空ETF' in body` rather than reading stdout.
- `python -m py_compile dashboard.py` is fine as a sanity check but the
  real evidence is the HTTP responses above.
