import { useState, useEffect } from "react";
import { Card, List, Tag, Typography, Space, Select, Spin, Empty, Button, Divider, message } from "antd";
import { WarningOutlined, FilterOutlined, EyeOutlined, LoadingOutlined } from "@ant-design/icons";
import { apiGetParams, apiGet } from "../../services/api";
import { DIFFICULTY_LABELS, ERROR_COLORS } from "../../types";

const { Title, Text, Paragraph } = Typography;

interface WrongQuestion {
  id: number;
  question_id: number;
  question_content: string;
  error_type: string;
  wrong_count: number;
  image_key: string | null;
  mastery_level: number;
  review_count: number;
  subject: string | null;
  difficulty: number | null;
  created_at: string | null;
}

interface SolutionData {
  final_answer: string;
  solution_steps: { step: number; description: string }[];
  explanation: string;
}

export default function WrongBookPage() {
  const [questions, setQuestions] = useState<WrongQuestion[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [subjectFilter, setSubjectFilter] = useState<string | undefined>();
  const [errorTypeFilter, setErrorTypeFilter] = useState<string | undefined>();
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [solution, setSolution] = useState<SolutionData | null>(null);
  const [solutionLoading, setSolutionLoading] = useState(false);

  useEffect(() => {
    fetchQuestions();
  }, [page, subjectFilter, errorTypeFilter]);

  const fetchQuestions = async () => {
    setLoading(true);
    try {
      const params: Record<string, string | number> = {
        skip: page * 20,
        limit: 20,
      };
      if (subjectFilter) params.subject = subjectFilter;
      if (errorTypeFilter) params.error_type = errorTypeFilter;

      const data = await apiGetParams<{ data?: { wrong_questions: WrongQuestion[]; total: number } }>(
        "/api/student/wrong-questions",
        params,
      );
      setQuestions(data.data?.wrong_questions || []);
      setTotal(data.data?.total || 0);
    } catch {
      message.error("获取错题列表失败");
      setQuestions([]);
    } finally {
      setLoading(false);
    }
  };

  const viewSolution = async (questionId: number) => {
    if (expandedId === questionId) {
      setExpandedId(null);
      setSolution(null);
      return;
    }
    setExpandedId(questionId);
    setSolutionLoading(true);
    setSolution(null);
    try {
      const data = await apiGet<{ data?: { solution?: SolutionData } }>(
        `/api/student/solution/${questionId}`,
      );
      setSolution(data.data?.solution || null);
    } catch {
      message.error("获取解答失败");
    } finally {
      setSolutionLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: "var(--page-max-width)", margin: "0 auto", padding: "var(--page-padding)" }}>
      <Title level={3}>
        <WarningOutlined style={{ marginRight: "var(--radius)" }} />
        错题本
      </Title>

      {/* Filters */}
      <Card size="small" style={{ marginBottom: "var(--card-gap)" }}>
        <Space wrap>
          <FilterOutlined />
          <Select
            placeholder="学科筛选"
            allowClear
            style={{ width: 120 }}
            value={subjectFilter}
            onChange={setSubjectFilter}
            options={[
              { value: "数学", label: "数学" },
              { value: "物理", label: "物理" },
              { value: "化学", label: "化学" },
              { value: "英语", label: "英语" },
              { value: "语文", label: "语文" },
            ]}
          />
          <Select
            placeholder="错误类型"
            allowClear
            style={{ width: 140 }}
            value={errorTypeFilter}
            onChange={setErrorTypeFilter}
            options={[
              { value: "conceptual", label: "概念错误" },
              { value: "calculation", label: "计算错误" },
              { value: "careless", label: "粗心错误" },
              { value: "未分类", label: "未分类" },
            ]}
          />
          <Text type="secondary">共 {total} 题</Text>
        </Space>
      </Card>

      {loading ? (
        <div style={{ textAlign: "center", padding: 40 }}><Spin /></div>
      ) : questions.length === 0 ? (
        <Empty description="暂无错题记录" />
      ) : (
        <List
          dataSource={questions}
          renderItem={(item) => (
            <List.Item>
              <Card style={{ width: "100%" }} size="small">
                <Space style={{ marginBottom: 8 }}>
                  <Tag color={ERROR_COLORS[item.error_type] || "default"}>
                    {item.error_type || "未分类"}
                  </Tag>
                  {item.subject && <Tag color="blue">{item.subject}</Tag>}
                  {item.difficulty != null && item.difficulty > 0 && (
                    <Tag color="orange">{DIFFICULTY_LABELS[item.difficulty] || `难度${item.difficulty}`}</Tag>
                  )}
                  <Text type="secondary">错误 {item.wrong_count} 次</Text>
                </Space>
                <Paragraph ellipsis={{ rows: 2 }}>{item.question_content}</Paragraph>
                <Button
                  type="link"
                  icon={solutionLoading && expandedId === item.id ? <LoadingOutlined /> : <EyeOutlined />}
                  onClick={() => viewSolution(item.id)}
                  style={{ padding: 0, marginTop: 4 }}
                >
                  {expandedId === item.id ? "收起解答" : "查看解答"}
                </Button>
                {expandedId === item.id && solution && (
                  <div style={{ background: "var(--bg-solution)", padding: 12, borderRadius: "var(--radius)", marginTop: 8 }}>
                    <Text strong>答案：</Text><Text>{solution.final_answer}</Text>
                    <Divider style={{ margin: "8px 0" }} />
                    {solution.solution_steps.map((s) => (
                      <Paragraph key={s.step} style={{ marginBottom: 4 }}>
                        <Tag color="blue">{s.step}</Tag> {s.description}
                      </Paragraph>
                    ))}
                    {solution.explanation && (
                      <>
                        <Divider style={{ margin: "8px 0" }} />
                        <Text type="secondary">{solution.explanation}</Text>
                      </>
                    )}
                  </div>
                )}
              </Card>
            </List.Item>
          )}
          pagination={{
            current: page + 1,
            pageSize: 20,
            total,
            onChange: (p) => setPage(p - 1),
          }}
        />
      )}
    </div>
  );
}
