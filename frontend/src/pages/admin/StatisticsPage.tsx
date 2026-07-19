import { useState, useEffect } from "react";
import { Card, Typography, Row, Col, Statistic, Select, Spin, Empty, Tag, Table, Progress, Divider, Space } from "antd";
import { FileTextOutlined, WarningOutlined, BookOutlined, BarChartOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { apiGet } from "../../services/api";
import { DIFFICULTY_LABELS, SUBJECT_COLORS } from "../../types";
import type { Document_, DocumentListResponse, DocumentAnalysis } from "../../types";

const { Title, Text } = Typography;

interface Statistics {
  total_questions: number;
  total_wrong_questions: number;
  subject_distribution: Record<string, number>;
  error_type_distribution: Record<string, number>;
  difficulty_distribution: Record<string, number>;
  top_weak_knowledge_points: { question_id: number; error_type: string; wrong_count: number }[];
  time_range: string;
}

interface WeakPointRow {
  question_id: number;
  error_type: string;
  wrong_count: number;
}

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}

export default function StatisticsPage() {
  const [stats, setStats] = useState<Statistics | null>(null);
  const [loading, setLoading] = useState(false);
  const [timeRange, setTimeRange] = useState("all");

  useEffect(() => {
    fetchStats();
  }, [timeRange]);

  const fetchStats = async () => {
    setLoading(true);
    try {
      const data = await apiGet<Statistics>(`/api/admin/statistics?time_range=${timeRange}`);
      setStats(data || null);
    } catch {
      setStats(null);
    } finally {
      setLoading(false);
    }
  };

  // ── Document Analysis State ──
  const [allDocs, setAllDocs] = useState<Document_[]>([]);
  const [selectedDocId, setSelectedDocId] = useState<number | undefined>();
  const [analysis, setAnalysis] = useState<DocumentAnalysis | null>(null);
  const [analysisLoading, setAnalysisLoading] = useState(false);

  useEffect(() => {
    apiGet<DocumentListResponse>("/api/admin/documents?limit=1000")
      .then((d) => setAllDocs(d.documents || []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!selectedDocId) {
      setAnalysis(null);
      return;
    }
    setAnalysisLoading(true);
    apiGet<DocumentAnalysis>(`/api/admin/documents/${selectedDocId}/analyze`)
      .then((d) => setAnalysis(d))
      .catch(() => setAnalysis(null))
      .finally(() => setAnalysisLoading(false));
  }, [selectedDocId]);

  const errorColumns: ColumnsType<{ type: string; count: number }> = [
    { title: "错误类型", dataIndex: "type", key: "type", render: (t: string) => <Tag>{t}</Tag> },
    { title: "数量", dataIndex: "count", key: "count" },
  ];

  const difficultyColumns: ColumnsType<{ difficulty: string; count: number }> = [
    { title: "难度", dataIndex: "difficulty", key: "difficulty", render: (d: string) => <Tag>{d}</Tag> },
    { title: "数量", dataIndex: "count", key: "count" },
  ];

  const weakColumns: ColumnsType<WeakPointRow> = [
    { title: "题目 ID", dataIndex: "question_id", key: "question_id", width: 100 },
    { title: "错误类型", dataIndex: "error_type", key: "error_type", render: (t: string) => <Tag>{t}</Tag> },
    { title: "错误次数", dataIndex: "wrong_count", key: "wrong_count", render: (c: number) => <Tag color={c > 5 ? "red" : "orange"}>{c}</Tag> },
  ];

  const errorData = stats ? Object.entries(stats.error_type_distribution).map(([type, count]) => ({ type, count })) : [];
  const difficultyData = stats ? Object.entries(stats.difficulty_distribution).map(([level, count]) => ({ difficulty: DIFFICULTY_LABELS[Number(level)] || level, count })) : [];
  const weakData = stats?.top_weak_knowledge_points || [];

  // Compute subject distribution with progress bars
  const subjectEntries = stats ? Object.entries(stats.subject_distribution).sort((a, b) => b[1] - a[1]) : [];
  const maxSubjectCount = subjectEntries.length > 0 ? Math.max(...subjectEntries.map(([, c]) => c), 1) : 1;

  return (
    <div style={{ maxWidth: "var(--page-max-width)", margin: "0 auto", padding: "var(--page-padding)" }}>
      <Title level={3}>使用统计</Title>
      <Select value={timeRange} onChange={setTimeRange} style={{ width: 200, marginBottom: 16 }}>
        <Select.Option value="all">全部时间</Select.Option>
        <Select.Option value="today">今天</Select.Option>
        <Select.Option value="week">最近 7 天</Select.Option>
        <Select.Option value="month">最近 30 天</Select.Option>
      </Select>
      <Spin spinning={loading}>
        {stats ? (
          <>
            <Row gutter={16} style={{ marginBottom: 24 }}>
              <Col span={8}>
                <Card className="card-hover-lift"><Statistic title="题目总数" value={stats.total_questions} prefix={<FileTextOutlined />} /></Card>
              </Col>
              <Col span={8}>
                <Card className="card-hover-lift"><Statistic title="错题总数" value={stats.total_wrong_questions} prefix={<WarningOutlined style={{ color: "var(--color-error)" }} />} /></Card>
              </Col>
              <Col span={8}>
                <Card className="card-hover-lift"><Statistic title="涉及学科" value={subjectEntries.length} prefix={<BookOutlined />} /></Card>
              </Col>
            </Row>

            {/* Subject distribution with visual bar chart */}
            {subjectEntries.length > 0 && (
              <Card title="学科分布" style={{ marginBottom: 16 }}>
                {subjectEntries.map(([subject, count]) => (
                  <div key={subject} style={{ display: "flex", alignItems: "center", marginBottom: 8 }}>
                    <Tag color={SUBJECT_COLORS[subject] || "#666"} style={{ minWidth: 72, textAlign: "center" }}>
                      {subject}
                    </Tag>
                    <Progress
                      percent={Math.round((count / maxSubjectCount) * 100)}
                      format={() => String(count)}
                      strokeColor={SUBJECT_COLORS[subject] || "#1890ff"}
                      style={{ flex: 1, margin: "0 8px" }}
                    />
                  </div>
                ))}
              </Card>
            )}

            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={12}>
                <Card title="难度分布" size="small">
                  <Table dataSource={difficultyData} columns={difficultyColumns} rowKey="difficulty" pagination={false} size="small" />
                </Card>
              </Col>
              <Col span={12}>
                <Card title="错误类型分布" size="small">
                  <Table dataSource={errorData} columns={errorColumns} rowKey="type" pagination={false} size="small" />
                </Card>
              </Col>
            </Row>

            <Card title="高频错误知识点">
              <Table dataSource={weakData} columns={weakColumns} rowKey="question_id" pagination={false} />
            </Card>
          </>
        ) : (
          <Empty description="暂无统计数据" />
        )}
      </Spin>

      <Divider />

      {/* ── Document Analysis ── */}
      <Card
        title={
          <Space>
            <BarChartOutlined />
            <span>文档分析</span>
          </Space>
        }
        style={{ marginTop: 16 }}
      >
        <Select
          showSearch
          allowClear
          placeholder="选择要分析的文档..."
          value={selectedDocId}
          onChange={(val) => setSelectedDocId(val)}
          style={{ width: "100%", marginBottom: 16 }}
          filterOption={(input, option) =>
            (option?.label as string)?.toLowerCase().includes(input.toLowerCase())
          }
          options={allDocs.map((doc) => ({
            value: doc.id,
            label: `${doc.filename}${doc.subject ? ` (${doc.subject}·${doc.grade || ""}·${doc.category || ""})` : ""}`,
          }))}
        />

        <Spin spinning={analysisLoading}>
          {analysis ? (
            <>
              <Row gutter={16} style={{ marginBottom: 16 }}>
                <Col span={8}>
                  <Statistic
                    title="题目数量"
                    value={analysis.questions_count}
                    prefix={<FileTextOutlined />}
                  />
                </Col>
                <Col span={8}>
                  <Statistic
                    title="文档大小"
                    value={formatSize(analysis.document.file_size)}
                    prefix={<FileTextOutlined />}
                  />
                </Col>
                <Col span={8}>
                  <Statistic
                    title="处理状态"
                    value={analysis.document.processing_status}
                    prefix={<FileTextOutlined />}
                  />
                </Col>
              </Row>

              <Card title="难度分布" size="small" style={{ marginBottom: 16 }}>
                <Table
                  dataSource={Object.entries(analysis.difficulty_distribution)
                    .sort(([a], [b]) => Number(a) - Number(b))
                    .map(([level, count]) => ({
                      difficulty: level === "0" ? "未分级" : DIFFICULTY_LABELS[Number(level)] || level,
                      count,
                    }))}
                  columns={[
                    { title: "难度", dataIndex: "difficulty", key: "difficulty", render: (d: string) => <Tag>{d}</Tag> },
                    { title: "数量", dataIndex: "count", key: "count" },
                  ]}
                  rowKey="difficulty"
                  pagination={false}
                  size="small"
                />
              </Card>

              {analysis.comparison && analysis.comparison.length > 0 && (
                <Card title="文档对比" size="small">
                  {analysis.comparison.map((comp, idx) => (
                    <div key={idx} style={{ marginBottom: 12 }}>
                      <Text strong>
                        {comp.document.filename}
                      </Text>
                      <Text type="secondary">
                        {" "}— {comp.questions_count} 题
                      </Text>
                      <div style={{ marginTop: 4 }}>
                        {Object.entries(comp.difficulty_distribution)
                          .sort(([a], [b]) => Number(a) - Number(b))
                          .map(([level, count]) => (
                            <Tag key={level}>
                              {level === "0" ? "未分级" : DIFFICULTY_LABELS[Number(level)] || level}: {count}
                            </Tag>
                          ))}
                      </div>
                    </div>
                  ))}
                </Card>
              )}
            </>
          ) : (
            <Empty description="选择文档以查看分析" />
          )}
        </Spin>
      </Card>
    </div>
  );
}
