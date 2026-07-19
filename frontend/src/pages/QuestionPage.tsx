import { useState, useEffect } from "react";
import { Card, List, Tag, Typography, Select, Space, Empty, Spin } from "antd";
import { FileTextOutlined } from "@ant-design/icons";
import { apiGetParams } from "../services/api";
import type { Question } from "../types";
import { DIFFICULTY_COLORS } from "../types";

const { Title, Text, Paragraph } = Typography;

const SUBJECT_OPTIONS = [
  { value: 1, label: "数学" }, { value: 2, label: "物理" },
  { value: 3, label: "化学" }, { value: 4, label: "英语" }, { value: 5, label: "语文" },
];

export default function QuestionPage() {
  const [questions, setQuestions] = useState<Question[]>([]);
  const [loading, setLoading] = useState(false);
  const [subjectFilter, setSubjectFilter] = useState<number | undefined>();

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
                  <Paragraph style={{ marginTop: 8 }}>{q.content}</Paragraph>
                  <Text type="secondary">{q.source_type}</Text>
                </Card>
              </List.Item>
            )}
          />
        )}
      </Spin>
    </div>
  );
}
