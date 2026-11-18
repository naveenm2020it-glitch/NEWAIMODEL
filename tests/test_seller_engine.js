const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const sources = [
  "mobile_app/www/js/bsm_engine.js",
  "mobile_app/www/js/nse_parser.js",
  "mobile_app/www/js/seller_engine.js"
].map(path => fs.readFileSync(path, "utf8"));

const context = {};
vm.runInNewContext(
  sources.join("\n") +
  "\nthis.NSEParser = NSEParser; this.SellerEngine = SellerEngine;",
  context
);

// Synthetic fixture is used only for deterministic regression testing;
// production sync/import continues to require genuine NSE EOD files.
const rows = context.NSEParser.generateDemo22Sessions();
const report = context.SellerEngine.analyze(rows);

assert.ok(Number.isFinite(report.spot_close) && report.spot_close > 0);
assert.ok(Number.isFinite(report.atr_14) && report.atr_14 > 0);
assert.ok(Number.isFinite(report.atm_iv_pct));
assert.ok(Number.isFinite(report.regime.corridor_pts));
assert.equal(
  report.regime.corridor_pts,
  report.regime.box_high - report.regime.box_low
);
assert.ok(report.strike_table.length > 0);

// The same EOD snapshot must produce identical levels regardless of CSV row order.
const reversedReport = context.SellerEngine.analyze([...rows].reverse());
for (const key of ["primary_resistance", "major_resistance", "primary_support", "major_support"]) {
  assert.equal(reversedReport[key].strike, report[key].strike, key + " must be order-invariant");
  assert.equal(reversedReport[key].option_type, report[key].option_type, key + " option side must be stable");
}
assert.equal(reversedReport.regime.box_high, report.regime.box_high);
assert.equal(reversedReport.regime.box_low, report.regime.box_low);

const putOnlyRows = rows.filter(row => row.option_type === "PE");
assert.throws(
  () => context.SellerEngine.analyze(putOnlyRows),
  /No eligible CE resistance candidates/
);
const callOnlyRows = rows.filter(row => row.option_type === "CE");
assert.throws(
  () => context.SellerEngine.analyze(callOnlyRows),
  /No eligible PE support candidates/
);

console.log("Seller engine report regression tests passed.");
