import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const __filename = fileURLToPath(import.meta.url);
const projectRoot = path.resolve(path.dirname(__filename), "..");
const runtimeDir = path.join(projectRoot, "runtime");
const inputPath = process.env.NOT_FOUND_REVIEW_JSON || path.join(runtimeDir, "not-found-review.json");
const outputPath = process.env.NOT_FOUND_REVIEW_XLSX || path.join(runtimeDir, "not-found-review.xlsx");

const sourceText = await fs.readFile(inputPath, "utf8");
const source = JSON.parse(sourceText);
const rows = Array.isArray(source.rows) ? source.rows : [];

function valueOrBlank(value) {
  if (value === undefined || value === null) return "";
  return value;
}

function dateOrBlank(value) {
  if (!value) return "";
  const match = String(value).match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return value;
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  return Number.isNaN(date.getTime()) ? value : date;
}

function suggestionValue(suggestions, index, key) {
  const suggestion = suggestions[index];
  if (!suggestion) return "";
  return valueOrBlank(suggestion[key]);
}

function suggestionScore(suggestions, index) {
  const suggestion = suggestions[index];
  if (!suggestion || suggestion.score === undefined || suggestion.score === null) return "";
  return Math.round(Number(suggestion.score) * 1000) / 1000;
}

function columnName(index) {
  let name = "";
  let current = index + 1;
  while (current > 0) {
    const remainder = (current - 1) % 26;
    name = String.fromCharCode(65 + remainder) + name;
    current = Math.floor((current - 1) / 26);
  }
  return name;
}

const workbook = Workbook.create();
const reviewSheet = workbook.worksheets.add("Разбор");
const summarySheet = workbook.worksheets.add("Сводка");

const headers = [
  "ФИО из графика",
  "Смен",
  "Первая смена",
  "Последняя смена",
  "Есть заселение",
  "Даты заселения",
  "Источники",
  "Вариант 1 ID",
  "Вариант 1 ФИО",
  "Вариант 1 стадия",
  "Вариант 1 похожесть",
  "Вариант 2 ID",
  "Вариант 2 ФИО",
  "Вариант 2 стадия",
  "Вариант 2 похожесть",
  "Вариант 3 ID",
  "Вариант 3 ФИО",
  "Вариант 3 стадия",
  "Вариант 3 похожесть",
  "Вариант 4 ID",
  "Вариант 4 ФИО",
  "Вариант 4 стадия",
  "Вариант 4 похожесть",
  "Вариант 5 ID",
  "Вариант 5 ФИО",
  "Вариант 5 стадия",
  "Вариант 5 похожесть",
];

const data = rows.map((row) => {
  const suggestions = Array.isArray(row.suggestions) ? row.suggestions : [];
  const settlementDates = Array.isArray(row.settlementDates) ? row.settlementDates.join(", ") : "";
  const sourceIds = Array.isArray(row.sources) ? row.sources.join(", ") : "";
  const values = [
    valueOrBlank(row.employee),
    valueOrBlank(row.shiftCount),
    dateOrBlank(row.firstShiftDate),
    dateOrBlank(row.lastShiftDate),
    row.hasSettlement ? "да" : "нет",
    settlementDates,
    sourceIds,
  ];
  for (let i = 0; i < 5; i += 1) {
    values.push(
      suggestionValue(suggestions, i, "dealId"),
      suggestionValue(suggestions, i, "title"),
      suggestionValue(suggestions, i, "stage"),
      suggestionScore(suggestions, i),
    );
  }
  return values;
});

reviewSheet.getRangeByIndexes(0, 0, 1, headers.length).values = [headers];
if (data.length > 0) {
  reviewSheet.getRangeByIndexes(1, 0, data.length, headers.length).values = data;
}

const usedReviewRows = Math.max(data.length + 1, 1);
const reviewRange = reviewSheet.getRangeByIndexes(0, 0, usedReviewRows, headers.length);
reviewRange.format.font = { name: "Arial", size: 10 };
reviewSheet.getRangeByIndexes(0, 0, 1, headers.length).format = {
  fill: "#1F4E78",
  font: { name: "Arial", bold: true, color: "#FFFFFF", size: 10 },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
};
reviewSheet.getRangeByIndexes(1, 1, Math.max(data.length, 1), 1).format.numberFormat = "#,##0";
reviewSheet.getRangeByIndexes(1, 2, Math.max(data.length, 1), 2).format.numberFormat = "yyyy-mm-dd";
for (const col of [10, 14, 18, 22, 26]) {
  reviewSheet.getRangeByIndexes(1, col, Math.max(data.length, 1), 1).format.numberFormat = "0.000";
}
reviewRange.format.borders = { preset: "all", style: "thin", color: "#D9D9D9" };
reviewSheet.freezePanes.freezeRows(1);
reviewSheet.freezePanes.freezeColumns(1);
reviewSheet.showGridLines = false;
reviewSheet.tables.add(
  `A1:${columnName(headers.length - 1)}${usedReviewRows}`,
  true,
  "NotFoundReviewTable",
);

const widths = [
  32, 10, 13, 13, 14, 24, 38,
  12, 32, 24, 14,
  12, 32, 24, 14,
  12, 32, 24, 14,
  12, 32, 24, 14,
  12, 32, 24, 14,
];
widths.forEach((width, index) => {
  reviewSheet.getRangeByIndexes(0, index, usedReviewRows, 1).format.columnWidth = width;
});
reviewSheet.getRangeByIndexes(1, 0, Math.max(data.length, 1), headers.length).format.wrapText = true;
reviewSheet.getRangeByIndexes(1, 0, Math.max(data.length, 1), headers.length).format.verticalAlignment = "top";

const topScores = rows.map((row) => {
  const suggestions = Array.isArray(row.suggestions) ? row.suggestions : [];
  return suggestions[0] ? Number(suggestions[0].score || 0) : 0;
});
const high = topScores.filter((score) => score >= 0.9).length;
const mid = topScores.filter((score) => score >= 0.8 && score < 0.9).length;
const low = topScores.filter((score) => score < 0.8).length;
const generatedAt = new Date();

const summaryData = [
  ["Показатель", "Значение"],
  ["Всего ФИО не найдено", rows.length],
  ["Похожесть 0.900 и выше", high],
  ["Похожесть 0.800–0.899", mid],
  ["Похожесть ниже 0.800", low],
  ["Источник", path.basename(inputPath)],
  ["Сформировано", generatedAt],
];
summarySheet.getRangeByIndexes(0, 0, summaryData.length, 2).values = summaryData;
summarySheet.getRange("A1:B1").format = {
  fill: "#1F4E78",
  font: { name: "Arial", bold: true, color: "#FFFFFF", size: 10 },
};
summarySheet.getRangeByIndexes(1, 1, 4, 1).format.numberFormat = "#,##0";
summarySheet.getRange("B7").format.numberFormat = "yyyy-mm-dd hh:mm";
summarySheet.getRangeByIndexes(0, 0, summaryData.length, 2).format.font = { name: "Arial", size: 10 };
summarySheet.getRangeByIndexes(0, 0, summaryData.length, 2).format.borders = {
  preset: "all",
  style: "thin",
  color: "#D9D9D9",
};
summarySheet.getRange("A:A").format.columnWidth = 28;
summarySheet.getRange("B:B").format.columnWidth = 28;
summarySheet.showGridLines = false;

const inspect = await workbook.inspect({
  kind: "table",
  range: "Разбор!A1:AA10",
  include: "values",
  tableMaxRows: 10,
  tableMaxCols: 27,
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
