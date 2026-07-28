import { useState, useEffect } from "react";
import {
  Table, Typography, Spin, message, Tag, Button, Card,
  Input, Radio, Space, Result, Progress, Divider, Empty,
} from "antd";
import {
  PlayCircleOutlined, CheckCircleOutlined,
  CloseCircleOutlined, ArrowLeftOutlined, SendOutlined,
} from "@ant-design/icons";
import { apiGet, apiPost } from "../services/api";
import type { TrainingSet, TrainingQuestion, SubmitResult } from "../types";
import MathRenderer from "../components/MathRenderer";

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;

type ViewMode = "list" | "quiz" | "results";

export default function TrainingPage() {
  const [mode, setMode] = useState<ViewMode>("list");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [trainingSets, setTrainingSets] = useState<TrainingSet[]>([]);
  const [activeSet, setActiveSet] = useState<TrainingSet | null>(null);
  const [questions, setQuestions] = useState<TrainingQuestion[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [result, setResult] = useState<SubmitResult | null>(null);

  useEffect(() => {
    fetchTrainingSets();
  }, []);

  const fetchTrainingSets = async () => {
    try {
      const data = await apiGet<TrainingSet[]>("/api/training/");
      setTrainingSets(data);
    } catch {
      message.error("加载训练列表失败");
    } finally {
      setLoading(false);
    }
  };

  const startQuiz = async (setId: number) => {
    setLoading(true);
    try {
      const data = await apiGet<TrainingSet>(`/api/training/${setId}`);
      if (!data.questions || data.questions.length === 0) {
        message.warning("该训练集暂无题目");
        setLoading(false);
        return;
      }
      setActiveSet(data);
      setQuestions(data.questions);
      setAnswers({});
      setCurrentIndex(0);
      setResult(null);
      setMode("quiz");
    } catch {
      message.error("加载训练集失败");
    } finally {
      setLoading(false);
    }
  };

  const updateAnswer = (qid: number, value: string) => {
    setAnswers((prev) => ({ ...prev, [qid]: value }));
  };

  const goToQuestion = (index: number) => {
    if (index >= 0 && index < questions.length) {
      setCurrentIndex(index);
    }
  };

  const submitAnswers = async () => {
    if (!activeSet) return;
    const payload = {
      answers: questions.map((q) => ({
        question_id: q.question_id,
        student_answer: answers[q.question_id] || "",
      })),
    };
    setSubmitting(true);
    try {
      const data = await apiPost<SubmitResult>(
        `/api/training/${activeSet.id}/submit`,
        payload,
      );
      setResult(data);
      setMode("results");
    } catch {
      message.error("提交失败，请重试");
    } finally {
      setSubmitting(false);
    }
  };

  const backToList = () => {
    setMode("list");
    setActiveSet(null);
    setQuestions([]);
    setResult(null);
  };

  /** Render answer input based on question type */
  const renderAnswerInput = (q: TrainingQuestion) => {
    const value = answers[q.question_id] || "";

    if (q.question_type === "choice") {
      // Extract options from content by splitting on newlines and matching option-prefixed lines.
      // The old regex `[A-D][.、]\s*\S+` truncated at spaces; line-based matching handles multi-word options.
      const optionLines = q.content.split("\n").filter((line) => /^[A-D][.、]/.test(line.trim()));
      if (optionLines.length > 0) {
        return (
          <Radio.Group
            value={value}
            onChange={(e) => updateAnswer(q.question_id, e.target.value)}
            style={{ width: "100%" }}
          >
            <Space direction="vertical">
              {optionLines.map((optLine) => {
                const trimmed = optLine.trim();
                const letter = trimmed.charAt(0);
                const text = trimmed.slice(2).trim();
                return (
                  <Radio key={letter} value={letter}>
                    <b>{letter}.</b> <MathRenderer content={text} />
                  </Radio>
                );
              })}
            </Space>
          </Radio.Group>
        );
      }
    }

    if (q.question_type === "fill") {
      return (
        <Input
          placeholder="输入你的答案..."
          value={value}
          onChange={(e) => updateAnswer(q.question_id, e.target.value)}
          style={{ maxWidth: 400 }}
        />
      );
    }

    // essay / proof / calculation / default
    return (
      <TextArea
        rows={4}
        placeholder="输入你的解答..."
        value={value}
        onChange={(e) => updateAnswer(q.question_id, e.target.value)}
        style={{ maxWidth: 600 }}
      />
    );
  };

  // ═══ LIST VIEW ═══
  if (mode === "list") {
    const columns = [
      { title: "ID", dataIndex: "id", key: "id", width: 80 },
      { title: "名称", dataIndex: "title", key: "title" },
      {
        title: "类型",
        dataIndex: "generation_type",
        key: "type",
        width: 100,
        render: (t: string) => <Tag>{t === "wrong_book" ? "错题训练" : "手动组卷"}</Tag>,
      },
      {
        title: "题目数",
        dataIndex: "question_count",
        key: "count",
        width: 100,
      },
      {
        title: "操作",
        key: "action",
        width: 120,
        render: (_: unknown, record: TrainingSet) => (
          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            onClick={() => startQuiz(record.id)}
            disabled={record.question_count === 0}
          >
            开始训练
          </Button>
        ),
      },
    ];

    return (
      <div>
        <Title level={4}>训练管理</Title>
        <Spin spinning={loading}>
          {trainingSets.length === 0 && !loading ? (
            <Empty description="暂无训练集" />
          ) : (
            <Table dataSource={trainingSets} columns={columns} rowKey="id" />
          )}
        </Spin>
      </div>
    );
  }

  // ═══ QUIZ VIEW ═══
  if (mode === "quiz") {
    const current = questions[currentIndex];
    const answered = questions.filter((q) => answers[q.question_id]?.trim()).length;
    const progress = Math.round((answered / questions.length) * 100);

    return (
      <div>
        <Space style={{ marginBottom: 16 }}>
          <Button icon={<ArrowLeftOutlined />} onClick={backToList}>
            返回列表
          </Button>
          <Title level={4} style={{ margin: 0 }}>
            {activeSet?.title}
          </Title>
        </Space>

        <Card style={{ marginBottom: 16 }}>
          <Space style={{ width: "100%", justifyContent: "space-between" }}>
            <Text>
              第 {currentIndex + 1} / {questions.length} 题
              {current.question_type && (
                <Tag style={{ marginLeft: 8 }}>
                  {current.question_type === "choice"
                    ? "选择题"
                    : current.question_type === "fill"
                      ? "填空题"
                      : "解答题"}
                </Tag>
              )}
            </Text>
            <Text type="secondary">已答 {answered}/{questions.length} 题</Text>
          </Space>
          <Progress percent={progress} size="small" style={{ marginTop: 8 }} />
        </Card>

        <Card>
          <Paragraph style={{ fontSize: 16, whiteSpace: "pre-wrap", marginBottom: 24 }}>
            <b>{currentIndex + 1}.</b> <MathRenderer content={current.content || ""} />
          </Paragraph>
          <Divider />
          <div style={{ marginBottom: 16 }}>
            <Text strong>你的答案：</Text>
          </div>
          {renderAnswerInput(current)}
        </Card>

        <Space style={{ marginTop: 16, width: "100%", justifyContent: "space-between" }}>
          <Button
            disabled={currentIndex === 0}
            onClick={() => goToQuestion(currentIndex - 1)}
          >
            上一题
          </Button>
          <Space>
            {currentIndex < questions.length - 1 ? (
              <Button
                type="primary"
                onClick={() => goToQuestion(currentIndex + 1)}
              >
                下一题
              </Button>
            ) : (
              <Button
                type="primary"
                icon={<SendOutlined />}
                onClick={submitAnswers}
                loading={submitting}
                disabled={answered < questions.length}
              >
                提交答案 ({answered}/{questions.length})
              </Button>
            )}
          </Space>
        </Space>
      </div>
    );
  }

  // ═══ RESULTS VIEW ═══
  if (mode === "results" && result) {
    const pct = Math.round((result.correct / result.total) * 100);
    return (
      <div>
        <Button icon={<ArrowLeftOutlined />} onClick={backToList} style={{ marginBottom: 16 }}>
          返回列表
        </Button>

        <Result
          status={pct >= 60 ? "success" : "warning"}
          title={`${result.correct} / ${result.total} 正确 (${pct}%)`}
          subTitle={pct >= 80 ? "表现优秀！" : pct >= 60 ? "继续加油！" : "需要多加练习！"}
        />

        <Progress
          percent={pct}
          status={pct >= 60 ? "success" : "exception"}
          style={{ marginBottom: 24 }}
        />

        {result.results.map((r) => (
          <Card
            key={r.question_id}
            style={{ marginBottom: 12 }}
            title={
              <Space>
                {r.is_correct ? (
                  <CheckCircleOutlined style={{ color: "#52c41a" }} />
                ) : (
                  <CloseCircleOutlined style={{ color: "#ff4d4f" }} />
                )}
                <Text><MathRenderer content={r.content.slice(0, 80)} />...</Text>
              </Space>
            }
          >
            <p>
              <Text strong>你的答案：</Text>
              <Text type={r.is_correct ? "success" : "danger"}><MathRenderer content={r.student_answer || "（未作答）"} /></Text>
            </p>
            {!r.is_correct && (
              <p>
                <Text strong>正确答案：</Text>
                <Text type="success"><MathRenderer content={r.correct_answer} /></Text>
              </p>
            )}
            {r.explanation && (
              <div style={{ marginTop: 8 }}>
                <Text strong>解析：</Text>
                <Paragraph style={{ whiteSpace: "pre-wrap", marginTop: 4 }}>
                  <MathRenderer content={r.explanation || ""} />
                </Paragraph>
              </div>
            )}
          </Card>
        ))}
      </div>
    );
  }

  return null;
}
