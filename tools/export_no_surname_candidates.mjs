import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const __filename = fileURLToPath(import.meta.url);
const projectRoot = path.resolve(path.dirname(__filename), "..");
const runtimeDir = path.join(projectRoot, "runtime");
const inputPath = path.join(runtimeDir, "no-surname-candidates-all-stages.json");
const outputPath = path.join(runtimeDir, "no-surname-candidates-all-stages.xlsx");

const report = JSON.parse(await fs.readFile(inputPath, "utf8"));
const rows = Array.isArray(report.rows) ? report.rows : [];

function dateOrBlank(value) {
  if (!value) return "";
  const match = String(value).match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return value;
  return new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
}

function colName(index) {
  let name = "";
  let current = index + 1;
  while (current > 0) {
    const rem = (current - 1) % 26;
    name = String.fromCharCode(65 + rem) + name;
    current = Math.floor((current - 1) / 26);
  }
  return name;
}

const labels = {
  not_found_by_surname_any_stage: "не найден вообще",
  found_in_other_stage_high_confidence: "найден в другой стадии",
  possible_in_other_stage_typo: "возможная опечатка в другой стадии",
  weak_candidates_in_other_stages: "есть слабые кандидаты",
  found_eligible_after_all_stage_search: "найден в нужной стадии",
};

const workbook = Workbook.create();
const summarySheet = workbook.worksheets.add("Сводка");
const detailSheet = workbook.worksheets.add("67 по всем стадиям");

const summaryRows = [
  ["Результат", "Количество"],
  ["Всего проверено", rows.length],
  ["Не найден вообще", report.summary?.not_found_by_surname_any_stage || 0],
  ["Найден в другой стадии", report.summary?.found_in_other_stage_high_confidence || 0],
  ["Возможная опечатка в другой стадии", report.summary?.possible_in_other_stage_typo || 0],
  ["Есть слабые кандидаты", report.summary?.weak_candidates_in_other_stages || 0],
];

summarySheet.getRangeByIndexes(0, 0, summaryRows.length, 2).values = summaryRows;
summarySheet.getRange("A1:B1").format = {
  fill: "#1F4E78",
  font: { name: "Arial", bold: true, color: "#FFFFFF", size: 10 },
};
summarySheet.getRangeByIndexes(0, 0, summaryRows.length, 2).format.font = { name: "Arial", size: 10 };
summarySheet.getRangeByIndexes(0, 0, summaryRows.length, 2).format.borders = {
  preset: "all",
  style: "thin",
  color: "#D9D9D9",
};
summarySheet.getRange("A:A").format.columnWidth = 38;
summarySheet.getRange("B:B").format.columnWidth = 14;
summarySheet.showGridLines = false;

const headers = [
  "Результат",
  "ФИО из графика",
  "Фамилия",
  "Смен",
  "Первая смена",
  "Последняя смена",
  "Источники",
  "Кандидатов всего",
  "Кандидатов в других стадиях",
  "Лучший ID",
  "Лучшее ФИО в Битриксе",
  "Стадия",
  "Похожесть",
  "Вариант 2",
  "Вариант 2 стадия",
  "Вариант 2 похожесть",
  "Вариант 3",
  "Вариант 3 стадия",
  "Вариант 3 похожесть",
];

const data = rows.map((row) => {
  const matches = Array.isArray(row.bestOutsideMatches) ? row.bestOutsideMatches : [];
  const first = matches[0] || {};
  const second = matches[1] || {};
  const third = matches[2] || {};
  return [
    labels[row.allStagesDiagnosis] || row.allStagesDiagnosis || "",
    row.employee || "",
    row.surname || "",
    row.shiftCount ?? "",
    dateOrBlank(row.firstShiftDate),
    dateOrBlank(row.lastShiftDate),
    Array.isArray(row.sources) ? row.sources.join(", ") : "",
    row.allStagesCandidateCount ?? "",
    row.outsideCandidateCount ?? "",
    first.dealId || "",
    first.title || "",
    first.stageId || "",
    first.score ?? "",
    second.title || "",
    second.stageId || "",
    second.score ?? "",
    third.title || "",
    third.stageId || "",
    third.score ?? "",
  ];
});

detailSheet.getRangeByIndexes(0, 0, 1, headers.length).values = [headers];
if (data.length) {
  detailSheet.getRangeByIndexes(1, 0, data.length, headers.length).values = data;
}

const usedRows = Math.max(data.length + 1, 1);
const usedRange = detailSheet.getRangeByIndexes(0, 0, usedRows, headers.length);
usedRange.format.font = { name: "Arial", size: 10 };
usedRange.format.borders = { preset: "all", style: "thin", color: "#D9D9D9" };
detailSheet.getRangeByIndexes(0, 0, 1, headers.length).format = {
  fill: "#1F4E78",
  font: { name: "Arial", bold: true, color: "#FFFFFF", size: 10 },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
};
detailSheet.getRangeByIndexes(1, 3, Math.max(data.length, 1), 1).format.numberFormat = "#,##0";
detailSheet.getRangeByIndexes(1, 4, Math.max(data.length, 1), 2).format.numberFormat = "yyyy-mm-dd";
detailSheet.getRangeByIndexes(1, 7, Math.max(data.length, 1), 2).format.numberFormat = "#,##0";
detailSheet.getRangeByIndexes(1, 12, Math.max(data.length, 1), 1).format.numberFormat = "0.000";
detailSheet.getRangeByIndexes(1, 15, Math.max(data.length, 1), 1).format.numberFormat = "0.000";
detailSheet.getRangeByIndexes(1, 18, Math.max(data.length, 1), 1).format.numberFormat = "0.000";
detailSheet.freezePanes.freezeRows(1);
detailSheet.freezePanes.freezeColumns(2);
detailSheet.tables.add(`A1:${colName(headers.length - 1)}${usedRows}`, true, "NoSurnameAllStagesTable");
[
  28, 32, 18, 10, 13, 13, 38, 14, 18, 12,
  32, 16, 12, 32, 16, 12, 32, 16, 12,
].forEach((width, index) => {
  detailSheet.getRangeByIndexes(0, index, usedRows, 1).format.columnWidth = width;
});
detailSheet.getRangeByIndexes(1, 0, Math.max(data.length, 1), headers.length).format.wrapText = true;
detailSheet.getRangeByIndexes(1, 0, Math.max(data.length, 1), headers.length).format.verticalAlignment = "top";
detailSheet.showGridLines = false;

const inspect = await workbook.inspect({
  kind: "table",
  range: "67 по всем стадиям!A1:S10",
  include: "values",
  tableMaxRows: 10,
  tableMaxCols: 19,
  maxChars: 5000,
});
console.log(inspect.ndjson);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
});
console.log(errors.ndjson);

await fs.mkdir(path.dirname(outputPath), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(JSON.stringify({ outputPath, rows: rows.length }, null, 2));
