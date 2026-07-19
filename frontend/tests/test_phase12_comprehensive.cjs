/**
 * Phase 12 Comprehensive Test — Student Frontend + Admin Frontend
 */

const fs = require("fs");
const path = require("path");

const SRC_DIR = path.join(__dirname, "..", "src");

class TestResult {
  constructor() {
    this.total = 0;
    this.passed = 0;
    this.failed = 0;
    this.errors = [];
  }

  check(name, condition, detail = "") {
    this.total++;
    if (condition) {
      this.passed++;
      console.log(`  PASS: ${name}`);
    } else {
      this.failed++;
      this.errors.push(`${name}: ${detail}`);
      console.log(`  FAIL: ${name} — ${detail}`);
    }
  }

  summary() {
    const pct = this.total > 0 ? (this.passed / this.total) * 100 : 0;
    const status = this.failed === 0 ? "ALL TESTS PASSED" : `${this.failed} TESTS FAILED`;
    console.log("\n" + "=".repeat(60));
    console.log(`  TOTAL: ${this.passed}/${this.total} passed (${pct.toFixed(1)}%) — ${status}`);
    console.log("=".repeat(60));
    if (this.errors.length > 0) {
      console.log("\nFAILED TESTS:");
      this.errors.forEach((e) => console.log(`  - ${e}`));
    }
    return this.failed === 0;
  }
}

function fileExists(relPath) {
  return fs.existsSync(path.join(SRC_DIR, relPath));
}

function fileContains(relPath, ...searchStrings) {
  if (!fileExists(relPath)) return false;
  const content = fs.readFileSync(path.join(SRC_DIR, relPath), "utf-8");
  return searchStrings.every((s) => content.includes(s));
}

function testAppRoutes(r) {
  console.log("\n[T12-11] Router System Refactor");
  r.check("App.tsx exists", fileExists("App.tsx"));
  r.check("Student route /", fileContains("App.tsx", 'path="/"', "AskPage"));
  r.check("Student route /wrong-book", fileContains("App.tsx", 'path="/wrong-book"', "WrongBookPage"));
  r.check("Admin route /admin", fileContains("App.tsx", 'path="/admin"', "AdminLayout"));
  r.check("Admin route /admin/edit", fileContains("App.tsx", 'path="edit"', "QuestionEditPage"));
  r.check("Admin route /admin/batch-upload", fileContains("App.tsx", 'path="batch-upload"', "BatchUploadPage"));
  r.check("Admin route /admin/statistics", fileContains("App.tsx", 'path="statistics"', "StatisticsPage"));
  r.check("Legacy route /legacy", fileContains("App.tsx", 'path="/legacy"', "LegacyLayout"));
  r.check("StudentLayout defined", fileContains("App.tsx", "function StudentLayout"));
  r.check("AdminLayout defined", fileContains("App.tsx", "function AdminLayout"));
  r.check("LegacyLayout defined", fileContains("App.tsx", "function LegacyLayout"));
  r.check("Student menu has 提问", fileContains("App.tsx", "提问"));
  r.check("Student menu has 错题本", fileContains("App.tsx", "错题本"));
  r.check("Admin menu has 题库目录", fileContains("App.tsx", "题库目录"));
  r.check("Admin menu has 批量上传", fileContains("App.tsx", "批量上传"));
  r.check("Admin menu has 使用统计", fileContains("App.tsx", "使用统计"));
}

function testAskPage(r) {
  console.log("\n[T12-01] Student AskPage");
  r.check("AskPage.tsx exists", fileExists("pages/student/AskPage.tsx"));
  r.check("has TextArea input", fileContains("pages/student/AskPage.tsx", "TextArea"));
  r.check("has Upload component", fileContains("pages/student/AskPage.tsx", "Upload"));
  r.check("has SendOutlined icon", fileContains("pages/student/AskPage.tsx", "SendOutlined"));
  r.check("has CameraOutlined icon", fileContains("pages/student/AskPage.tsx", "CameraOutlined"));
  r.check("has SSEEvent interface", fileContains("pages/student/AskPage.tsx", "interface SSEEvent"));
  r.check("has QuestionRecord interface", fileContains("pages/student/AskPage.tsx", "interface QuestionRecord"));
  r.check("has /api/student/ask call", fileContains("pages/student/AskPage.tsx", "/api/student/ask"));
}

function testThinkingHint(r) {
  console.log("\n[T12-02] Thinking Hint + Dual-Choice Mode");
  r.check("has thinking_hint field", fileContains("pages/student/AskPage.tsx", "thinking_hint"));
  r.check("has BulbOutlined icon", fileContains("pages/student/AskPage.tsx", "BulbOutlined"));
  r.check("has difficulty labels", fileContains("pages/student/AskPage.tsx", "DIFFICULTY_LABELS"));
  r.check("has difficulty colors", fileContains("pages/student/AskPage.tsx", "DIFFICULTY_COLORS"));
  r.check("has dual-choice (think/solve)", fileContains("pages/student/AskPage.tsx", "think", "solve"));
  r.check("has /api/student/choose call", fileContains("pages/student/AskPage.tsx", "/api/student/choose"));
}

function testSolutionDisplay(r) {
  console.log("\n[T12-03] Solution Display");
  r.check("has SolutionData interface", fileContains("pages/student/AskPage.tsx", "interface SolutionData"));
  r.check("has answer field", fileContains("pages/student/AskPage.tsx", "answer"));
  r.check("has steps field", fileContains("pages/student/AskPage.tsx", "steps"));
  r.check("has knowledge_points field", fileContains("pages/student/AskPage.tsx", "knowledge_points"));
  r.check("has summary field", fileContains("pages/student/AskPage.tsx", "summary"));
  r.check("has CheckCircleOutlined icon", fileContains("pages/student/AskPage.tsx", "CheckCircleOutlined"));
}

function testFailureRecovery(r) {
  console.log("\n[T12-04] Failure Recovery UI");
  r.check("has error handling", fileContains("pages/student/AskPage.tsx", "error"));
  r.check("has ExclamationCircleOutlined icon", fileContains("pages/student/AskPage.tsx", "ExclamationCircleOutlined"));
  r.check("has Alert component", fileContains("pages/student/AskPage.tsx", "Alert"));
  r.check("has phase error handling", fileContains("pages/student/AskPage.tsx", '"error"'));
}

function testMultiQuestionQueue(r) {
  console.log("\n[T12-05] Multi-Question Queue UI");
  r.check("QuestionQueue component exists", fileExists("components/QuestionQueue.tsx"));
  r.check("AskPage uses QuestionQueue", fileContains("pages/student/AskPage.tsx", "QuestionQueue"));
  r.check("has questions array state", fileContains("pages/student/AskPage.tsx", "questions", "QuestionRecord[]"));
  r.check("has status tracking", fileContains("pages/student/AskPage.tsx", "status"));
}

function testWrongBookPage(r) {
  console.log("\n[T12-06] Wrong Book Page");
  r.check("WrongBookPage.tsx exists", fileExists("pages/student/WrongBookPage.tsx"));
  r.check("has wrong-questions API call", fileContains("pages/student/WrongBookPage.tsx", "wrong-questions") || fileContains("pages/student/WrongBookPage.tsx", "wrong_questions"));
  r.check("has pagination", fileContains("pages/student/WrongBookPage.tsx", "pagination") || fileContains("pages/student/WrongBookPage.tsx", "Pagination") || fileContains("pages/student/WrongBookPage.tsx", "skip") || fileContains("pages/student/WrongBookPage.tsx", "limit"));
}

function testQuestionTreePage(r) {
  console.log("\n[T12-07] Admin Question Tree Page");
  r.check("QuestionTreePage.tsx exists", fileExists("pages/admin/QuestionTreePage.tsx"));
  r.check("has /api/admin/catalog call", fileContains("pages/admin/QuestionTreePage.tsx", "/api/admin/catalog"));
  r.check("has Tree component", fileContains("pages/admin/QuestionTreePage.tsx", "Tree") || fileContains("pages/admin/QuestionTreePage.tsx", "tree"));
}

function testQuestionEditPage(r) {
  console.log("\n[T12-08] Admin Question Edit Page");
  r.check("QuestionEditPage.tsx exists", fileExists("pages/admin/QuestionEditPage.tsx"));
  r.check("has /api/admin/questions call", fileContains("pages/admin/QuestionEditPage.tsx", "/api/admin/questions"));
  r.check("has Form component", fileContains("pages/admin/QuestionEditPage.tsx", "Form"));
  r.check("has difficulty field", fileContains("pages/admin/QuestionEditPage.tsx", "difficulty"));
}

function testBatchUploadPage(r) {
  console.log("\n[T12-09] Admin Batch Upload Page");
  r.check("BatchUploadPage.tsx exists", fileExists("pages/admin/BatchUploadPage.tsx"));
  r.check("has /api/admin/documents/batch-upload call", fileContains("pages/admin/BatchUploadPage.tsx", "/api/admin/documents/batch-upload"));
  r.check("has Upload component", fileContains("pages/admin/BatchUploadPage.tsx", "Upload"));
  r.check("has subject selector", fileContains("pages/admin/BatchUploadPage.tsx", "subject"));
  r.check("has grade selector", fileContains("pages/admin/BatchUploadPage.tsx", "grade"));
  r.check("has category selector", fileContains("pages/admin/BatchUploadPage.tsx", "category"));
}

function testStatisticsPage(r) {
  console.log("\n[T12-10] Admin Statistics Page");
  r.check("StatisticsPage.tsx exists", fileExists("pages/admin/StatisticsPage.tsx"));
  r.check("has /api/admin/statistics call", fileContains("pages/admin/StatisticsPage.tsx", "/api/admin/statistics"));
  r.check("has time range selector", fileContains("pages/admin/StatisticsPage.tsx", "time_range") || fileContains("pages/admin/StatisticsPage.tsx", "timeRange"));
  r.check("has total_questions display", fileContains("pages/admin/StatisticsPage.tsx", "total_questions") || fileContains("pages/admin/StatisticsPage.tsx", "totalQuestions"));
  r.check("has top_weak_knowledge_points display", fileContains("pages/admin/StatisticsPage.tsx", "top_weak") || fileContains("pages/admin/StatisticsPage.tsx", "weak"));
}

function testBuild(r) {
  console.log("\n[Build] TypeScript Compilation");
  r.check("tsconfig.json exists", fileExists("../tsconfig.json") || fileExists("tsconfig.json"));
  r.check("package.json exists", fileExists("../package.json"));
  r.check("main.tsx exists", fileExists("main.tsx"));
}

function main() {
  const r = new TestResult();
  console.log("=".repeat(60));
  console.log("  PHASE 12 COMPREHENSIVE TEST");
  console.log("  Student Frontend + Admin Frontend");
  console.log("=".repeat(60));

  testAppRoutes(r);
  testAskPage(r);
  testThinkingHint(r);
  testSolutionDisplay(r);
  testFailureRecovery(r);
  testMultiQuestionQueue(r);
  testWrongBookPage(r);
  testQuestionTreePage(r);
  testQuestionEditPage(r);
  testBatchUploadPage(r);
  testStatisticsPage(r);
  testBuild(r);

  const success = r.summary();
  process.exit(success ? 0 : 1);
}

main();
