/**
 * DocumentsPage — 原始文档管理页面
 *
 * 列表视图：支持按年级、科目、类别快速筛选
 */

import { useState, useEffect, useCallback, useMemo } from "react";
import { Card, Typography, Button, Space, Spin, Empty, Tag, message, Table, Select, Input } from "antd";
import {
  FilePdfOutlined,
  FileImageOutlined,
  FileOutlined,
  DownloadOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { apiGet } from "../../services/api";
import type { Document_, DocumentListResponse } from "../../types";

const { Title } = Typography;

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}

function fileIcon(fileType: string) {
  if (fileType.includes("pdf")) return <FilePdfOutlined style={{ color: "var(--color-error)" }} />;
  if (fileType.includes("image") || /\.(png|jpg|jpeg|gif|bmp|tiff?)$/i.test(fileType))
    return <FileImageOutlined style={{ color: "var(--color-info)" }} />;
  return <FileOutlined />;
}

const STATUS_COLORS: Record<string, string> = {
  completed: "green",
  processing: "blue",
  pending: "default",
  failed: "red",
};

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<Document_[]>([]);
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState<number | null>(null);

  // ── Filters ──
  const [filterSubject, setFilterSubject] = useState<string>("");
  const [filterGrade, setFilterGrade] = useState<string>("");
  const [filterCategory, setFilterCategory] = useState<string>("");
  const [searchText, setSearchText] = useState("");

  const fetchDocuments = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiGet<DocumentListResponse>(
        "/api/admin/documents?limit=10000"
      );
      setDocuments(data.documents || []);
    } catch {
      message.error("加载文档列表失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments]);

  const handleDownload = async (docId: number, filename: string) => {
    setDownloading(docId);
    try {
      const adminKey = localStorage.getItem("admin_key") || "";
      const res = await fetch(`/api/admin/documents/${docId}/download`, {
        headers: { "X-Admin-Key": adminKey },
      });
      if (!res.ok) {
        message.error("下载失败");
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      message.error("下载失败，请检查网络");
    } finally {
      setDownloading(null);
    }
  };

  // ── Derived filter options ──
  const { subjects, grades, categories } = useMemo(() => {
    const s = new Set<string>();
    const g = new Set<string>();
    const c = new Set<string>();
    documents.forEach((doc) => {
      if (doc.subject) s.add(doc.subject);
      if (doc.grade) g.add(doc.grade);
      if (doc.category) c.add(doc.category);
    });
    return {
      subjects: Array.from(s).sort(),
      grades: Array.from(g).sort(),
      categories: Array.from(c).sort(),
    };
  }, [documents]);

  // ── Filtered documents ──
  const filteredDocs = useMemo(() => {
    return documents.filter((doc) => {
      if (filterSubject && doc.subject !== filterSubject) return false;
      if (filterGrade && doc.grade !== filterGrade) return false;
      if (filterCategory && doc.category !== filterCategory) return false;
      if (searchText) {
        const lower = searchText.toLowerCase();
        if (!doc.filename.toLowerCase().includes(lower)) return false;
      }
      return true;
    });
  }, [documents, filterSubject, filterGrade, filterCategory, searchText]);

  // ── Table columns ──
  const columns: ColumnsType<Document_> = [
    {
      title: "文件名",
      dataIndex: "filename",
      key: "filename",
      render: (_: string, record: Document_) => (
        <Space>
          {fileIcon(record.file_type)}
          <span>{record.filename}</span>
        </Space>
      ),
    },
    {
      title: "科目",
      dataIndex: "subject",
      key: "subject",
      width: 100,
      render: (v: string | null) => v ? <Tag>{v}</Tag> : <Tag color="default">未分类</Tag>,
    },
    {
      title: "年级",
      dataIndex: "grade",
      key: "grade",
      width: 100,
      render: (v: string | null) => v || "—",
    },
    {
      title: "类别",
      dataIndex: "category",
      key: "category",
      width: 100,
      render: (v: string | null) => v || "—",
    },
    {
      title: "大小",
      dataIndex: "file_size",
      key: "file_size",
      width: 100,
      render: (v: number) => formatSize(v),
    },
    {
      title: "状态",
      dataIndex: "processing_status",
      key: "processing_status",
      width: 100,
      render: (v: string) => (
        <Tag color={STATUS_COLORS[v] || "default"}>{v}</Tag>
      ),
    },
    {
      title: "操作",
      key: "actions",
      width: 100,
      render: (_: unknown, record: Document_) => (
        <Button
          type="link"
          size="small"
          icon={<DownloadOutlined />}
          loading={downloading === record.id}
          onClick={() => handleDownload(record.id, record.filename)}
        >
          下载
        </Button>
      ),
    },
  ];

  return (
    <div style={{ maxWidth: "var(--page-max-width)", margin: "0 auto", padding: "var(--page-padding)" }}>
      <Title level={3}>原始文档</Title>

      {/* ── Filter bar ── */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select
            allowClear
            placeholder="科目筛选"
            value={filterSubject || undefined}
            onChange={(val) => setFilterSubject(val || "")}
            style={{ minWidth: 120 }}
            options={subjects.map((s) => ({ value: s, label: s }))}
          />
          <Select
            allowClear
            placeholder="年级筛选"
            value={filterGrade || undefined}
            onChange={(val) => setFilterGrade(val || "")}
            style={{ minWidth: 120 }}
            options={grades.map((g) => ({ value: g, label: g }))}
          />
          <Select
            allowClear
            placeholder="类别筛选"
            value={filterCategory || undefined}
            onChange={(val) => setFilterCategory(val || "")}
            style={{ minWidth: 120 }}
            options={categories.map((c) => ({ value: c, label: c }))}
          />
          <Input
            allowClear
            placeholder="搜索文件名..."
            prefix={<SearchOutlined />}
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            style={{ width: 240 }}
          />
          <Tag>{filteredDocs.length} / {documents.length} 个文档</Tag>
        </Space>
      </Card>

      {/* ── Document table ── */}
      <Spin spinning={loading}>
        {documents.length > 0 ? (
          <Card>
            <Table
              dataSource={filteredDocs}
              columns={columns}
              rowKey="id"
              size="middle"
              pagination={{ pageSize: 50, showSizeChanger: true, showTotal: (t) => `共 ${t} 个文档` }}
            />
          </Card>
        ) : (
          <Empty description="暂无文档" />
        )}
      </Spin>
    </div>
  );
}
