import { useState } from "react";
import { Card, Input, Button, Typography, Space, Spin, Empty, Steps, Divider } from "antd";
import { SearchOutlined, CheckCircleOutlined } from "@ant-design/icons";
import { apiGet } from "../services/api";
import type { SolutionData } from "../types";
import type { QuestionImage } from "../components/QuestionImagesRenderer";
import MathRenderer from "../components/MathRenderer";
import QuestionImagesRenderer from "../components/QuestionImagesRenderer";

const { Title, Text, Paragraph } = Typography;

export default function SolutionPage() {
  const [questionId, setQuestionId] = useState<string>("");
  const [solution, setSolution] = useState<SolutionData | null>(null);
  const [questionImages, setQuestionImages] = useState<QuestionImage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchSolution = async () => {
    if (!questionId) return;
    setLoading(true);
    setError(null);
    setSolution(null);
    setQuestionImages([]);
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
          question_images?: QuestionImage[];
        };
      }>(`/api/solutions/${questionId}`);
      if (data.data) {
        setSolution({
          final_answer: data.data.final_answer || data.data.answer || "",
          solution_steps: data.data.solution_steps || data.data.steps || [],
          explanation: data.data.explanation || data.data.summary || "",
        });
        // S#173: Extract placement-aware images
        setQuestionImages(data.data.question_images || []);
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
            {/* ── 答案区（仅最终答案）────────────────────────── */}
            <Title level={5}>
              <CheckCircleOutlined style={{ color: "var(--color-info)", marginRight: "var(--radius)" }} />
              答案
            </Title>
            <Paragraph strong>
              <MathRenderer content={solution.final_answer || "(无)"} />
            </Paragraph>

            {/* ── 解题步骤（分析过程）────────────────────────── */}
            {solution.solution_steps.length > 0 && (
              <>
                <Divider />
                <Title level={5}>解题步骤</Title>
                <Steps
                  direction="vertical"
                  current={-1}
                  items={solution.solution_steps.map((s) => ({
                    title: `步骤 ${s.step}`,
                    description: <MathRenderer content={s.description} />,
                  }))}
                />
              </>
            )}

            {/* ── 讲解区（详解分析）──────────────────────────── */}
            {solution.explanation && (
              <>
                <Divider />
                <Title level={5}>讲解</Title>
                <Paragraph>
                  <MathRenderer content={solution.explanation} />
                </Paragraph>
              </>
            )}
            {/* S#173: Explanation + page_context images */}
            <QuestionImagesRenderer images={questionImages} placements={["explanation", "page_context"]} />
          </Card>
        ) : (
          !error && !loading && <Empty description="请输入题目 ID 查询" />
        )}
      </Spin>
    </div>
  );
}
