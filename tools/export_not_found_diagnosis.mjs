import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const __filename = fileURLToPath(import.meta.url);
const projectRoot = path.resolve(path.dirname(__filename), "..");
const runtimeDir = path.join(projectRoot, "runtime");
const inputPath = process.env.NOT_FOUND_DIAGNOSIS_JSON || path.join(runtimeDir, "not-found-diagnosis.json");
const outputPath = process.env.NOT_FOUND_DIAGNOSIS_XLSX || path.join(runtimeDir, "not-found-diagnosis.xlsx");

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

const workbook = Workbook.create();
const summarySheet = workbook.worksheets.add("Сводка");
const reviewSheet = workbook.worksheets.add("Диагностика");

const statusLabels = {
  found_eligible_high_confidence: "найдено уверенно",
  possible_eligible_typo: "похоже на опечатку",
  weak_candidates_only: "есть слабые кандидаты",
  no_candidates_by_surname: "по фамилии нет кандидатов",
};

const summaryRows = [
  ["Результат", "Количество"],
  ["Всего было not_found", rows.length],
  ["Найдено уверенно", report.summary?.found_eligible_high_confidence || 0],
  ["Похоже на опечатку", report.summary?.possible_eligible_typo || 0],
  ["Есть только слабые кандидаты", report.summary?.weak_candidates_only || 0],
  ["По фамилии нет кандидатов", report.summary?.no_candidates_by_surname || 0],
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
summarySheet.getRange("A:A").format.columnWidth = 34;
summarySheet.getRange("B:B").format.columnWidth = 14;
summarySheet.showGridLines = false;

const headers = [
  "Диагноз",
  "ФИО из графика",
  "Фамилия",
  "Смен",
  "Первая смена",
  "Последняя смена",
  "Источники",
  "Кандидатов в нужных стадиях",
  "Лучший ID",
  "Лучшее ФИО в Битриксе",
  "Стадия",
  "Похожесть",
  "Вариант 2",
  "Вариант 2 похожесть",
  "Вариант 3",
  "Вариант 3 похожесть",
];

const data = rows.map((row) => {
  const matches = Array.isArray(row.eligibleMatches) ? row.eligibleMatches : [];
  const first = matches[0] || {};
  const second = matches[1] || {};
  const third = matches[2] || {};
  return [
    statusLabels[row.diagnosis] || row.diagnosis || "",
    row.employee || "",
    row.surname || "",
    row.shiftCount ?? "",
    dateOrBlank(row.firstShiftDate),
    dateOrBlank(row.lastShiftDate),
    Array.isArray(row.sources) ? row.sources.join(", ") : "",
    row.eligibleCandidateCount ?? "",
    first.dealId || "",
    first.title || "",
    first.stageId || "",
    first.score ?? "",
    second.title || "",
    second.score ?? "",
    third.title || "",
    third.score ?? "",
  ];
});

reviewSheet.getRangeByIndexes(0, 0, 1, headers.length).values = [headers];
if (data.length) {
  reviewSheet.getRangeByIndexes(1, 0, data.length, headers.length).values = data;
}
const usedRows = Math.max(data.length + 1, 1);
reviewSheet.getRangeByIndexes(0, 0, 1, headers.length).format = {
  fill: "#1F4E78",
  font: { name: "Arial", bold: true, color: "#FFFFFF", size: 10 },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
};
const tableRange = reviewSheet.getRangeByIndexes(0, 0, usedRows, headers.length);
tableRange.format.font = { name: "Arial", size: 10 };
tableRange.format.borders = { preset: "all", style: "thin", color: "#D9D9D9" };
reviewSheet.getRangeByIndexes(1, 3, Math.max(data.length, 1), 1).format.numberFormat = "#,##0";
reviewSheet.getRangeByIndexes(1, 4, Math.max(data.length, 1), 2).format.numberFormat = "yyyy-mm-dd";
reviewSheet.getRangeByIndexes(1, 7, Math.max(data.length, 1), 1).format.numberFormat = "#,##0";
reviewSheet.getRangeByIndexes(1, 11, Math.max(data.length, 1), 1).format.numberFormat = "0.000";
reviewSheet.getRangeByIndexes(1, 13, Math.max(data.length, 1), 1).format.numberFormat = "0.000";
reviewSheet.getRangeByIndexes(1, 15, Math.max(data.length, 1), 1).format.numberFormat = "0.000";
reviewSheet.freezePanes.freezeRows(1);
reviewSheet.freezePanes.freezeColumns(2);
reviewSheet.tables.add(`A1:${colName(headers.length - 1)}${usedRows}`, true, "NotFoundDiagnosisTable");
[
  24, 32, 18, 10, 13, 13, 38, 16, 12, 32, 18, 12, 32, 12, 32, 12,
].forEach((width, index) => {
  reviewSheet.getRangeByIndexes(0, index, usedRows, 1).format.columnWidth = width;
});
reviewSheet.getRangeByIndexes(1, 0, Math.max(data.length, 1), headers.length).format.wrapText = true;
reviewSheet.getRangeByIndexes(1, 0, Math.max(data.length, 1), headers.length).format.verticalAlignment = "top";
reviewSheet.showGridLines = false;

const inspect = await workbook.inspect({
  kind: "table",
  range: "Диагностика!A1:P10",
  include: "values",
  tableMaxRows: 10,
  tableMaxCols: 16,
  maxChars: 4000,
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
