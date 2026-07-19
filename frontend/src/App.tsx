import { BrowserRouter, Routes, Route, Link, useLocation, useNavigate, Outlet } from "react-router-dom";
import { useEffect, useState } from "react";
import { setAdminKey } from "./services/api";
import { Layout, Menu, Typography, Segmented, Button, Modal, Input } from "antd";
import {
  HomeOutlined,
  SettingOutlined,
  UploadOutlined,
  FileTextOutlined,
  BulbOutlined,
  WarningOutlined,
  BookOutlined,
  RobotOutlined,
  DollarOutlined,
  ExperimentOutlined,
  BarChartOutlined,
  EditOutlined,
  FolderOutlined,
  SunOutlined,
  MoonOutlined,
} from "@ant-design/icons";
import SettingsPage from "./pages/admin/SettingsPage";
import { useThemeMode } from "./hooks/useThemeMode";

// Student pages
import AskPage from "./pages/student/AskPage";
import WrongBookPage from "./pages/student/WrongBookPage";
import NotFoundPage from "./pages/NotFoundPage";
import ErrorBoundary from "./components/ErrorBoundary";

// Admin pages
import QuestionTreePage from "./pages/admin/QuestionTreePage";
import QuestionEditPage from "./pages/admin/QuestionEditPage";
import BatchUploadPage from "./pages/admin/BatchUploadPage";
import StatisticsPage from "./pages/admin/StatisticsPage";
import DocumentsPage from "./pages/admin/DocumentsPage";

// Phase 1 legacy pages
import UploadPage from "./pages/UploadPage";
import QuestionPage from "./pages/QuestionPage";
import SolutionPage from "./pages/SolutionPage";
import TutorChatPage from "./pages/TutorChatPage";
import WrongQuestionPage from "./pages/WrongQuestionPage";
import KnowledgePage from "./pages/KnowledgePage";
import CostPage from "./pages/CostPage";
import TrainingPage from "./pages/TrainingPage";
import ExamPage from "./pages/ExamPage";

const { Header, Content, Sider } = Layout;
const { Title } = Typography;

// ═══ Student Layout ═══

const studentMenuItems = [
  { key: "/", icon: <HomeOutlined />, label: <Link to="/">提问</Link> },
  { key: "/wrong-book", icon: <WarningOutlined />, label: <Link to="/wrong-book">错题本</Link> },
];

function StudentLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const { mode, toggleTheme } = useThemeMode();
  const selectedKey = "/" + location.pathname.split("/").filter(Boolean)[0] || "/";

  const currentRole = location.pathname.startsWith("/admin") ? "admin" : "student";

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0 24px",
          background: "#000000",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 24 }}>
          <Title level={3} style={{ margin: 0, color: "#ffffff", fontWeight: 600, fontSize: 21 }}>
            AI Tutor
          </Title>
          <Segmented
            size="small"
            value={currentRole}
            onChange={(val) => navigate(val === "admin" ? "/admin" : "/")}
            options={[
              { label: "🎓 学生端", value: "student" },
              { label: "⚙️ 管理端", value: "admin" },
            ]}
          />
        </div>
        <Button
          type="text"
          icon={mode === "dark" ? <SunOutlined /> : <MoonOutlined />}
          onClick={toggleTheme}
          title={mode === "dark" ? "切换浅色模式" : "切换深色模式"}
          style={{ color: "#ffffff" }}
        />
      </Header>
      <Layout>
        <Sider
          width={200}
          style={{ background: "#f5f5f7" }}
        >
          <Menu
            mode="inline"
            selectedKeys={[selectedKey === "/" ? "/" : selectedKey]}
            style={{ height: "100%", borderRight: 0, background: "transparent" }}
            items={studentMenuItems}
          />
        </Sider>
        <Content style={{ padding: 16, background: "#ffffff" }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}

// ═══ Admin Layout ═══

const adminMenuItems = [
  { key: "/admin", icon: <FolderOutlined />, label: <Link to="/admin">题库目录</Link> },
  { key: "/admin/documents", icon: <FileTextOutlined />, label: <Link to="/admin/documents">原始文档</Link> },
  { key: "/admin/edit", icon: <EditOutlined />, label: <Link to="/admin/edit">题目编辑</Link> },
  { key: "/admin/batch-upload", icon: <UploadOutlined />, label: <Link to="/admin/batch-upload">批量上传</Link> },
  { key: "/admin/statistics", icon: <BarChartOutlined />, label: <Link to="/admin/statistics">使用统计</Link> },
  { key: "/admin/settings", icon: <SettingOutlined />, label: <Link to="/admin/settings">系统设置</Link> },
];

function AdminLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const { mode, toggleTheme } = useThemeMode();
  const [keyModalOpen, setKeyModalOpen] = useState(false);
  const [adminKeyInput, setAdminKeyInput] = useState("");

  useEffect(() => {
    const stored = localStorage.getItem("admin_key");
    if (stored) {
      setAdminKey(stored);
    } else {
      setKeyModalOpen(true);
    }
  }, []);

  const handleKeySubmit = () => {
    const trimmed = adminKeyInput.trim();
    if (trimmed) {
      localStorage.setItem("admin_key", trimmed);
      setAdminKey(trimmed);
      setKeyModalOpen(false);
      setAdminKeyInput("");
    }
  };

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0 24px",
          background: "#000000",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 24 }}>
          <Title level={3} style={{ margin: 0, color: "#ffffff", fontWeight: 600, fontSize: 21 }}>
            AI Tutor — 管理后台
          </Title>
          <Segmented
            size="small"
            value="admin"
            onChange={(val) => navigate(val === "admin" ? "/admin" : "/")}
            options={[
              { label: "🎓 学生端", value: "student" },
              { label: "⚙️ 管理端", value: "admin" },
            ]}
          />
        </div>
        <Button
          type="text"
          icon={mode === "dark" ? <SunOutlined /> : <MoonOutlined />}
          onClick={toggleTheme}
          title={mode === "dark" ? "切换浅色模式" : "切换深色模式"}
          style={{ color: "#ffffff" }}
        />
      </Header>
      <Layout>
        <Sider
          width={200}
          style={{ background: "#f5f5f7" }}
        >
          <Menu
            mode="inline"
            selectedKeys={[location.pathname]}
            style={{ height: "100%", borderRight: 0, background: "transparent" }}
            items={adminMenuItems}
          />
        </Sider>
        <Content style={{ padding: 16, background: "#ffffff" }}>
          <Outlet />
        </Content>
      </Layout>
      <Modal
        title="管理员认证"
        open={keyModalOpen}
        onOk={handleKeySubmit}
        onCancel={() => navigate("/")}
        okText="确认"
        cancelText="返回学生端"
        closable={false}
        maskClosable={false}
      >
        <p style={{ marginBottom: 12 }}>请输入管理员密钥以访问管理后台：</p>
        <Input.Password
          placeholder="X-Admin-Key"
          value={adminKeyInput}
          onChange={(e) => setAdminKeyInput(e.target.value)}
          onPressEnter={handleKeySubmit}
        />
      </Modal>
    </Layout>
  );
}

// ═══ Legacy Layout (Phase 1 pages) ═══

const legacyMenuItems = [
  { key: "/legacy/upload", icon: <UploadOutlined />, label: <Link to="/legacy/upload">Upload</Link> },
  { key: "/legacy/questions", icon: <FileTextOutlined />, label: <Link to="/legacy/questions">Questions</Link> },
  { key: "/legacy/solutions", icon: <BulbOutlined />, label: <Link to="/legacy/solutions">Solutions</Link> },
  { key: "/legacy/wrong", icon: <WarningOutlined />, label: <Link to="/legacy/wrong">Wrong Qs</Link> },
  { key: "/legacy/knowledge", icon: <BookOutlined />, label: <Link to="/legacy/knowledge">Knowledge</Link> },
  { key: "/legacy/tutor", icon: <RobotOutlined />, label: <Link to="/legacy/tutor">Tutor</Link> },
  { key: "/legacy/training", icon: <ExperimentOutlined />, label: <Link to="/legacy/training">Training</Link> },
  { key: "/legacy/exam", icon: <FileTextOutlined />, label: <Link to="/legacy/exam">Exam</Link> },
  { key: "/legacy/cost", icon: <DollarOutlined />, label: <Link to="/legacy/cost">Cost</Link> },
];

function LegacyLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const { mode, toggleTheme } = useThemeMode();

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0 24px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 24 }}>
          <Title level={3} style={{ margin: 0 }}>
            AI Tutor — Legacy
          </Title>
          <Segmented
            size="small"
            value="legacy"
            onChange={(val) => {
              if (val === "student") navigate("/");
              else if (val === "admin") navigate("/admin");
            }}
            options={[
              { label: "🎓 学生端", value: "student" },
              { label: "⚙️ 管理端", value: "admin" },
              { label: "📦 Legacy", value: "legacy" },
            ]}
          />
        </div>
        <Button
          type="text"
          icon={mode === "dark" ? <SunOutlined /> : <MoonOutlined />}
          onClick={toggleTheme}
          title={mode === "dark" ? "切换浅色模式" : "切换深色模式"}
        />
      </Header>
      <Layout>
        <Sider width={200}>
          <Menu
            mode="inline"
            selectedKeys={[location.pathname]}
            style={{ height: "100%", borderRight: 0 }}
            items={legacyMenuItems}
          />
        </Sider>
        <Content style={{ padding: 16 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}

// ═══ App ═══

function AppRoutes() {
  return (
    <Routes>
      {/* Student routes */}
      <Route element={<StudentLayout />}>
        <Route path="/" element={<AskPage />} />
        <Route path="/wrong-book" element={<WrongBookPage />} />
      </Route>

      {/* Admin routes */}
      <Route path="/admin" element={<AdminLayout />}>
        <Route index element={<QuestionTreePage />} />
        <Route path="edit" element={<QuestionEditPage />} />
        <Route path="question-edit" element={<QuestionEditPage />} />
        <Route path="batch-upload" element={<BatchUploadPage />} />
        <Route path="documents" element={<DocumentsPage />} />
        <Route path="statistics" element={<StatisticsPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>

      {/* Legacy routes */}
      <Route path="/legacy" element={<LegacyLayout />}>
        <Route path="upload" element={<UploadPage />} />
        <Route path="questions" element={<QuestionPage />} />
        <Route path="solutions" element={<SolutionPage />} />
        <Route path="wrong" element={<WrongQuestionPage />} />
        <Route path="knowledge" element={<KnowledgePage />} />
        <Route path="tutor" element={<TutorChatPage />} />
        <Route path="training" element={<TrainingPage />} />
        <Route path="exam" element={<ExamPage />} />
        <Route path="cost" element={<CostPage />} />
      </Route>

      {/* 404 catch-all */}
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}

export default function App() {
  useEffect(() => {
    const adminKey = localStorage.getItem("admin_key");
    if (adminKey) {
      import("./services/api").then(({ setAdminKey }) => setAdminKey(adminKey));
    }
  }, []);

  return (
    <ErrorBoundary>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </ErrorBoundary>
  );
}
