import { useState, useEffect } from "react";
import { Card, List, Tag, Typography, Select, Space, Empty, Spin, Button } from "antd";
import { FileTextOutlined, EyeOutlined, LoadingOutlined } from "@ant-design/icons";
import { apiGetParams, apiGet } from "../services/api";
import type { Question } from "../types";
import { DIFFICULTY_COLORS } from "../types";
import MathRenderer from "../components/MathRenderer";
import QuestionImagesRenderer, { type QuestionImage } from "../components/QuestionImagesRenderer";

const { Title, Text, Paragraph } = Typography;

const SUBJECT_OPTIONS = [
  { value: 1, label: "数学" }, { value: 2, label: "物理" },
  { value: 3, label: "化学" }, { value: 4, label: "英语" }, { value: 5, label: "语文" },
];

export default function QuestionPage() {
  const [questions, setQuestions] = useState<Question[]>([]);
  const [loading, setLoading] = useState(false);
  const [subjectFilter, setSubjectFilter] = useState<number | undefined>();
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [expandedImages, setExpandedImages] = useState<QuestionImage[]>([]);
  const [imagesLoading, setImagesLoading] = useState(false);

  useEffect(() => {
    fetchQuestions();
  }, [subjectFilter]);

  const fetchQuestions = async () => {
    setLoading(true);
    try {
      const data = await apiGetParams<{ questions: Question[] }>("/api/questions/", {
        subject_id: subjectFilter,
      });
      setQuestions(data.questions || []);
    } catch {
      setQuestions([]);
    } finally {
      setLoading(false);
    }
  };

  const toggleExpand = async (q: Question) => {
    if (expandedId === q.id) {
      setExpandedId(null);
      setExpandedImages([]);
      return;
    }
    setExpandedId(q.id);
    setImagesLoading(true);
    setExpandedImages([]);
    try {
      const data = await apiGet<{ question_images?: QuestionImage[] }>(`/api/questions/${q.id}`);
      setExpandedImages(data.question_images || []);
    } catch {
      setExpandedImages([]);
    } finally {
      setImagesLoading(false);
    }
  };

  return (
    <div>
      <Title level={4}>题目浏览</Title>
      <Space style={{ marginBottom: 16 }}>
        <Text>学科筛选:</Text>
        <Select
          allowClear
          placeholder="全部学科"
          style={{ width: 200 }}
          options={SUBJECT_OPTIONS}
          onChange={(v) => setSubjectFilter(v)}
        />
      </Space>
      <Spin spinning={loading}>
        {questions.length === 0 && !loading ? (
          <Empty description="暂无题目" />
        ) : (
          <List
            grid={{ gutter: 16, column: 1 }}
            dataSource={questions}
            renderItem={(q) => (
              <List.Item>
                <Card size="small">
                  <Space>
                    <FileTextOutlined />
                    <Tag color="blue">#{q.id}</Tag>
                    {q.difficulty && <Tag color={DIFFICULTY_COLORS[q.difficulty]}>{q.difficulty}</Tag>}
                  </Space>
                  <Paragraph style={{ marginTop: 8, whiteSpace: "pre-wrap" }}><MathRenderer content={q.content || ""} /></Paragraph>
                  <Text type="secondary">{q.source_type}</Text>
                  <Button
                    type="link"
                    icon={imagesLoading && expandedId === q.id ? <LoadingOutlined /> : <EyeOutlined />}
                    onClick={() => toggleExpand(q)}
                    style={{ padding: 0, marginTop: 4 }}
                  >
                    {expandedId === q.id ? "收起图片" : "查看配图"}
                  </Button>
                  {/* S#173: Stem images when expanded */}
                  {expandedId === q.id && expandedImages.length > 0 && (
                    <div style={{ marginTop: 8 }}>
                      <QuestionImagesRenderer images={expandedImages} placements={["stem"]} />
                    </div>
                  )}
                </Card>
              </List.Item>
            )}
          />
        )}
      </Spin>
    </div>
  );
}
