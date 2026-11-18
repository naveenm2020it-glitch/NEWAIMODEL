const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync("mobile_app/www/js/bsm_engine.js", "utf8");
const context = {};
vm.runInNewContext(source + "\nthis.BSMEngine = BSMEngine;", context);
const bsm = context.BSMEngine;

for (const optionType of ["CE", "PE"]) {
  const F = 25040;
  const K = optionType === "CE" ? 25100 : 24900;
  const T = 5 / 252;
  const sigma = 0.14;
  const premium = bsm.bsmPrice(F, K, T, sigma, optionType);
  const recoveredIv = bsm.impliedVolatility(premium, F, K, T, optionType);
  assert.ok(Math.abs(recoveredIv - sigma) < 0.0002,
    optionType + " IV round-trip failed: " + recoveredIv);

  const stressedIv = sigma + 0.02;
  const dangerPremium = premium * 1.45;
  const basis = 40;
  const dangerSpot = bsm.solveSpotDangerLevel(
    dangerPremium, K, 4 / 252, stressedIv, optionType, basis
  );
  const reconstructedPremium = bsm.bsmPrice(
    dangerSpot + basis, K, Math.max(4 / 252, 0.25 / 252),
    stressedIv, optionType
  );
  assert.ok(Math.abs(reconstructedPremium - dangerPremium) < 0.3,
    optionType + " danger-spot round-trip failed: " + reconstructedPremium +
    " vs " + dangerPremium);
}

console.log("Mobile BSM CE/PE numerical regression tests passed.");
