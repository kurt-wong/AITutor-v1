import { useState } from "react";
import { Card, Input, Button, Typography, Space, Spin, Empty, Steps } from "antd";
import { SearchOutlined, CheckCircleOutlined } from "@ant-design/icons";
import { apiGet } from "../services/api";
import type { SolutionData } from "../types";

const { Title, Text, Paragraph } = Typography;

export default function SolutionPage() {
  const [questionId, setQuestionId] = useState<string>("");
  const [solution, setSolution] = useState<SolutionData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchSolution = async () => {
    if (!questionId) return;
    setLoading(true);
    setError(null);
    setSolution(null);
    try {
      const data = await apiGet<{
        data?: {
          id: number;
          final_answer?: string;
          solution_steps?: { step: number; description: string }[];
          explanation?: string;
          answer?: string;
          steps?: { step: number; description: string }[];
          summary?: string;
        };
      }>(`/api/solutions/${questionId}`);
      if (data.data) {
        setSolution({
          final_answer: data.data.final_answer || data.data.answer || "",
          solution_steps: data.data.solution_steps || data.data.steps || [],
          explanation: data.data.explanation || data.data.summary || "",
        });
      } else {
        setError("题目未找到");
      }
    } catch {
      setError("获取解答失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <Title level={4}>解答查看</Title>
      <Text type="secondary">输入题目 ID 查看解答</Text>
      <Space style={{ marginTop: 16, marginBottom: 16 }}>
        <Input
          placeholder="题目 ID"
          value={questionId}
          onChange={(e) => setQuestionId(e.target.value)}
          style={{ width: 200 }}
        />
        <Button
          type="primary"
          icon={<SearchOutlined />}
          onClick={fetchSolution}
          loading={loading}
        >
          查询
        </Button>
      </Space>
      <Spin spinning={loading}>
        {error && (
          <Card style={{ marginBottom: "var(--card-gap)" }}>
            <Text type="danger">{error}</Text>
          </Card>
        )}
        {solution ? (
          <Card>
            <Title level={5}>
              <CheckCircleOutlined style={{ color: "var(--color-info)", marginRight: "var(--radius)" }} />
              解答
            </Title>
            <Paragraph strong>答案: {solution.final_answer}</Paragraph>
            <Steps
              direction="vertical"
              current={-1}
              items={solution.solution_steps.map((s) => ({ title: `步骤 ${s.step}`, description: s.description }))}
            />
            {solution.explanation && (
              <Paragraph style={{ marginTop: 16 }}>{solution.explanation}</Paragraph>
            )}
          </Card>
        ) : (
          !error && !loading && <Empty description="请输入题目 ID 查询" />
        )}
      </Spin>
    </div>
  );
}
