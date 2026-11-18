const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync("mobile_app/www/js/nse_parser.js", "utf8");
const context = {};
vm.runInNewContext(source + "\nthis.NSEParser = NSEParser;", context);

const csv = [
  "\uFEFFTradDt,FinInstrmTp,TckrSymb,XpryDt,StrkPric,OptnTp,OpnPric,HghPric,LwPric,ClsPric,SttlmPric,PrvsClsgPric,UndrlygPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,NewBrdLotQty",
  "2026-11-12,IDO,NIFTY,2026-11-26,25000,CE,100,110,90,105,105,98,24950,100000,5000,20000,2100000,75"
].join("\n");

const rows = context.NSEParser.parseBhavcopyCSV(csv);
assert.equal(rows.length, 1, "BOM-prefixed NSE CSV header should parse");
assert.equal(rows[0].trade_date, "2026-11-12");
assert.equal(rows[0].expiry_date, "2026-11-26");
assert.equal(rows[0].spot_close, 24950);
assert.equal(rows[0].option_type, "CE");

// A partial export must not be accepted as valid market data.
const incompleteCsv = [
  "TradDt,TckrSymb,StrkPric,ClsPric",
  "2026-11-12,NIFTY,25000,105"
].join("\n");
assert.equal(context.NSEParser.parseBhavcopyCSV(incompleteCsv).length, 0);

const participantCsv = [
  "Client Type,Future Index Long,Future Index Short,Option Index Call Long,Option Index Call Short,Option Index Put Long,Option Index Put Short",
  'FII,0,0,"1,200","500","300","700"',
  "Pro,0,0,100,50,200,100"
].join("\n");
const participant = context.NSEParser.parseParticipantCSV(
  participantCsv,
  "fao_participant_oi_13112026.csv"
);
assert.equal(participant.inst_net_call_contracts, 750);
assert.equal(participant.inst_net_put_contracts, -300);
assert.equal(participant.as_of, "2026-11-13");

console.log("NSE parser regression tests passed.");
