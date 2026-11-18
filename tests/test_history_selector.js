const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const bsmSource = fs.readFileSync("mobile_app/www/js/bsm_engine.js", "utf8");
const engineSource = fs.readFileSync("mobile_app/www/js/seller_engine.js", "utf8");
const context = { console, Math, Date };
vm.runInNewContext(bsmSource + "\n" + engineSource + "\nthis.SellerEngine = SellerEngine;", context);
const engine = context.SellerEngine;

const rows = [];
for (const date of ["2026-11-16", "2026-11-17", "2026-11-18"]) {
  for (const expiry of ["2026-11-26", "2026-12-31"]) {
    for (const strike of [24800, 24900, 25000, 25100, 25200]) {
      for (const optionType of ["CE", "PE"]) {
        const close = Math.max(5, optionType === "CE" ? 120 - (strike - 25000) * 0.35 : 120 + (strike - 25000) * 0.35);
        rows.push({
          trade_date: date, expiry_date: expiry, strike, option_type: optionType,
          open_price: close, high_price: close + 5, low_price: close - 5,
          close_price: close, settle_price: close, prev_close_price: close + (date.endsWith("16") ? 2 : -1),
          spot_close: 25000 + (date.endsWith("16") ? -30 : date.endsWith("17") ? 10 : 40),
          futures_close: 25020, oi: 100000 + strike, chg_in_oi: 1500,
          chg_oi_contracts: 20, oi_contracts: 1000, vol_contracts: 100,
          volume: 10000, turnover: 1000000, vwap: close + 1, lot_size: 75
        });
      }
    }
  }
}

const expiries = engine.getAvailableExpiries(rows, "2026-11-17");
assert.deepEqual(Array.from(expiries), ["2026-11-26", "2026-12-31"]);
assert.equal(engine.getDefaultExpiry(rows, "2026-11-17"), "2026-11-26");

const selected = engine.analyze(rows, null, { date: "2026-11-17", expiry: "2026-12-31" });
assert.equal(selected.as_of_date, "2026-11-17");
assert.equal(selected.expiry_date, "2026-12-31");
assert.equal(selected.sessions_loaded, 2, "future sessions must not leak into historical analysis");

assert.throws(
  () => engine.analyze(rows, null, { date: "2026-11-17", expiry: "2026-11-19" }),
  /selected expiry/i
);
assert.throws(
  () => engine.analyze(rows, null, { date: "2026-11-15" }),
  /no usable NIFTY option records/i
);

console.log("Historical date and expiry selector regression tests passed.");
