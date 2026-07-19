import { useState, useEffect } from "react";
import { Card, List, Tag, Typography, Space, Statistic, Row, Col, Spin, Empty } from "antd";
import { WarningOutlined } from "@ant-design/icons";
import { apiGet } from "../services/api";
import type { WrongQuestion } from "../types";
import { ERROR_COLORS } from "../types";

const { Title, Text } = Typography;

interface WrongQuestionResponse {
  wrong_questions: WrongQuestion[];
  total: number;
}

export default function WrongQuestionPage() {
  const [questions, setQuestions] = useState<WrongQuestion[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    fetchWrongQuestions();
  }, []);

  const fetchWrongQuestions = async () => {
    setLoading(true);
    try {
      const data = await apiGet<WrongQuestionResponse>("/api/wrong-questions/");
      setQuestions(data.wrong_questions || []);
      setTotal(data.total || 0);
    } catch {
      setQuestions([]);
    } finally {
      setLoading(false);
    }
  };

  const avgWrongCount = questions.length > 0
    ? (questions.reduce((sum, q) => sum + q.wrong_count, 0) / questions.length).toFixed(1)
    : "0";

  return (
    <div>
      <Title level={4}>错题面板</Title>
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={8}>
          <Card>
            <Statistic
              title="错题总数"
              value={total}
              prefix={<WarningOutlined style={{ color: "var(--color-error)" }} />}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic title="平均错误次数" value={avgWrongCount} />
          </Card>
        </Col>
      </Row>
      <Spin spinning={loading}>
        {questions.length === 0 && !loading ? (
          <Empty description="暂无错题" />
        ) : (
          <List
            dataSource={questions}
            renderItem={(q) => (
              <List.Item>
                <Card size="small" style={{ width: "100%" }}>
                  <Space>
                    <Tag color={ERROR_COLORS[q.error_type]}>{q.error_type}</Tag>
                    <Text type="secondary">错误 {q.wrong_count} 次</Text>
                    <Text type="secondary">题目 #{q.question_id}</Text>
                  </Space>
                </Card>
              </List.Item>
            )}
          />
        )}
      </Spin>
    </div>
  );
}
