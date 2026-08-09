import { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Card, Typography, Input, Select, Button, Space, Spin, Alert, message, Tag, Divider, Segmented,
} from "antd";
import { EditOutlined, SaveOutlined, DeleteOutlined } from "@ant-design/icons";
import { apiGet, apiPutForm, apiDelete } from "../../services/api";
import { DIFFICULTY_LABELS } from "../../types";
import MathRenderer from "../../components/MathRenderer";
import QuestionImagesRenderer, { type QuestionImage } from "../../components/QuestionImagesRenderer";

const { Title, Text, Paragraph } = Typography;

interface QuestionDetail {
  id: number;
  document_id: number | null;
  subject_id: number | null;
  subject_name: string | null;
  question_number: string | null;
  display_number?: number;  // Session #130
  passage_text?: string | null;  // Session #130
  content: string;
  difficulty: number | null;
  source_type: string | null;
  created_at: string;
  images: QuestionImage[];
  solution: {
    id: number;
    final_answer: string;
    solution_steps: { step: number; description: string }[];
    explanation: string;
  } | null;
}

interface QuestionAnnotationData {
  annotation: {
    id: number;
    annotation_type: string;
    model_name: string | null;
    payload: Record<string, unknown> | null;
  } | null;
  ocr_markdown: string | null;
  rendered: {
    stem: string;
    options: string[];
    answer: string;
    explanation: string;
    passage: string;
  } | null;
}

export default function QuestionEditPage() {
  const [searchParams] = useSearchParams();
  const [questionId, setQuestionId] = useState(searchParams.get("id") || "");
  const [question, setQuestion] = useState<QuestionDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [difficulty, setDifficulty] = useState<number | undefined>();
  const [editAnswer, setEditAnswer] = useState("");
  const [editSteps, setEditSteps] = useState("");
  const [editExplanation, setEditExplanation] = useState("");
  const [annotationData, setAnnotationData] = useState<QuestionAnnotationData | null>(null);
  const [renderMode, setRenderMode] = useState<"db" | "mirror">("db");

  // Auto-fetch when navigated with ?id= param
  useEffect(() => {
    const id = searchParams.get("id");
    if (id && id !== questionId) {
      setQuestionId(id);
    }
  }, [searchParams]);

  useEffect(() => {
    if (questionId && !question) {
      fetchQuestion();
    }
  }, [questionId]);

  const fetchQuestion = async () => {
    if (!questionId.trim()) return;
    setLoading(true);
    try {
      const data = await apiGet<QuestionDetail>(`/api/admin/questions/${questionId}`);
      if (data && (data as any).id) {
        const q = data as QuestionDetail;
        setQuestion(q);
        setDifficulty(q.difficulty ?? undefined);
        setEditAnswer(q.solution?.final_answer ?? "");
        setEditSteps(q.solution?.solution_steps ? JSON.stringify(q.solution.solution_steps, null, 2) : "");
        setEditExplanation(q.solution?.explanation ?? "");
        try {
          const ann = await apiGet<QuestionAnnotationData>(`/api/admin/questions/${questionId}/annotation`);
          setAnnotationData(ann);
          setRenderMode(ann?.rendered ? "mirror" : "db");
        } catch {
          setAnnotationData(null);
          setRenderMode("db");
        }
      } else {
        message.error("题目未找到");
      }
    } catch {
      message.error("获取题目失败");
    } finally {
      setLoading(false);
    }
  };

  const handleSaveMeta = async () => {
    if (!question) return;
    setSaving(true);
    try {
      const formData = new FormData();
      if (difficulty !== undefined) formData.append("difficulty", String(difficulty));
      await apiPutForm(`/api/admin/questions/${question.id}`, formData);
      message.success("保存成功");
    } catch {
      message.error("保存失败");
    } finally {
      setSaving(false);
    }
  };

  const handleSaveSolution = async () => {
    if (!question) return;
    setSaving(true);
    try {
      const formData = new FormData();
      if (editAnswer) formData.append("final_answer", editAnswer);
      if (editSteps) formData.append("solution_steps", editSteps);
      if (editExplanation) formData.append("explanation", editExplanation);
      await apiPutForm(`/api/admin/questions/${question.id}/solution`, formData);
      message.success("解题步骤保存成功");
    } catch {
      message.error("保存解题步骤失败");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!question) return;
    if (!confirm("确定删除该题目？此操作不可撤销。")) return;
    try {
      await apiDelete(`/api/admin/questions/${question.id}`);
      message.success("已删除");
      setQuestion(null);
      setQuestionId("");
    } catch {
      message.error("删除失败");
    }
  };

  const difficultyOptions = Object.entries(DIFFICULTY_LABELS).map(([k, v]) => ({ value: Number(k), label: v }));

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "var(--page-padding)" }}>
      <Title level={3}><EditOutlined style={{ marginRight: "var(--radius)" }} />题目编辑</Title>
      <Card size="small" style={{ marginBottom: "var(--card-gap)" }}>
        <Space>
          <Input placeholder="输入题目 ID" value={questionId} onChange={(e) => setQuestionId(e.target.value)} style={{ width: 160 }} />
          <Button type="primary" onClick={fetchQuestion} loading={loading}>查询</Button>
        </Space>
      </Card>
      <Spin spinning={loading}>
        {question ? (
          <Card>
            <Space style={{ marginBottom: 8 }}>
              <Tag color="blue">#{question.display_number || question.id}</Tag>
              {question.question_number && (
                <Tag color="default">卷面题号: {question.question_number}</Tag>
              )}
            </Space>
            {annotationData?.rendered && (
              <div style={{ marginBottom: 12 }}>
                <Segmented
                  value={renderMode}
                  onChange={(value) => setRenderMode(value as "db" | "mirror")}
                  options={[
                    { label: "题库内容", value: "db" },
                    { label: "L1+L2 标注渲染", value: "mirror" },
                  ]}
                />
              </div>
            )}
            {renderMode === "mirror" && annotationData?.rendered ? (
              <div style={{
                marginTop: 8, padding: 12, borderRadius: 6,
                background: "#fafafa", border: "1px solid #f0f0f0",
              }}>
                {annotationData.rendered.passage && (
                  <Paragraph style={{
                    padding: 10, whiteSpace: "pre-wrap",
                    background: "#f5f5f5", borderRadius: 6,
                    borderLeft: "3px solid #1890ff",
                  }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>阅读材料</Text>
                    <br />
                    <MathRenderer content={annotationData.rendered.passage} />
                  </Paragraph>
                )}
                <Paragraph style={{ whiteSpace: "pre-wrap" }}>
                  <MathRenderer content={annotationData.rendered.stem || ""} />
                </Paragraph>
                {annotationData.rendered.options.map((option, index) => (
                  <Paragraph key={index} style={{ marginBottom: 4, whiteSpace: "pre-wrap" }}>
                    <Text strong>{String.fromCharCode(65 + index)}.</Text>{" "}
                    <MathRenderer content={option} />
                  </Paragraph>
                ))}
                {annotationData.rendered.answer && (
                  <Paragraph style={{ whiteSpace: "pre-wrap" }}>
                    <Text strong>答案：</Text>
                    <MathRenderer content={annotationData.rendered.answer} />
                  </Paragraph>
                )}
                {annotationData.rendered.explanation && (
                  <Paragraph style={{ whiteSpace: "pre-wrap" }}>
                    <Text strong>讲解：</Text>
                    <MathRenderer content={annotationData.rendered.explanation} />
                  </Paragraph>
                )}
                {annotationData.annotation && (
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    标注类型：{annotationData.annotation.annotation_type} · 模型：{annotationData.annotation.model_name || "unknown"}
                  </Text>
                )}
              </div>
            ) : (
              <>
                {question.passage_text && (
                  <Paragraph style={{
                    marginTop: 8, padding: 12, whiteSpace: "pre-wrap",
                    background: "#f5f5f5", borderRadius: 6, borderLeft: "3px solid #1890ff",
                  }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>阅读材料</Text>
                    <br />
                    <MathRenderer content={question.passage_text} />
                  </Paragraph>
                )}
                <Paragraph style={{ marginTop: 8, whiteSpace: "pre-wrap" }}><MathRenderer content={question.content || ""} /></Paragraph>
              </>
            )}
            {question.subject_name && <Tag>{question.subject_name}</Tag>}
            {/* S#173: Stem images via shared renderer */}
            <QuestionImagesRenderer images={question.images} placements={["stem"]} />
            <Divider />
            <Space>
              <Text strong>难度:</Text>
              <Select value={difficulty} onChange={setDifficulty} options={difficultyOptions} style={{ width: 120 }} />
              <Button type="primary" icon={<SaveOutlined />} onClick={handleSaveMeta} loading={saving}>保存</Button>
            </Space>
            <Divider />
            <Title level={5}>解答</Title>
            <Text strong>答案:</Text>
            <Paragraph style={{ background: "#fafafa", padding: 8, borderRadius: 4, minHeight: 32, whiteSpace: "pre-wrap", overflowWrap: "break-word", wordBreak: "break-word", maxWidth: "100%" }}>
              <MathRenderer content={editAnswer || (question?.solution?.final_answer || "")} />
            </Paragraph>
            <Text strong>讲解:</Text>
            <Paragraph style={{ background: "#fafafa", padding: 8, borderRadius: 4, minHeight: 32, whiteSpace: "pre-wrap", overflowWrap: "break-word", wordBreak: "break-word", maxWidth: "100%" }}>
              <MathRenderer content={editExplanation || (question?.solution?.explanation || "")} />
            </Paragraph>
            {/* S#173: Explanation + page_context images via shared renderer */}
            <QuestionImagesRenderer images={question.images} placements={["explanation", "page_context"]} />
            <Space>
              <Button type="primary" icon={<SaveOutlined />} onClick={handleSaveSolution} loading={saving}>保存解答</Button>
              <Button danger icon={<DeleteOutlined />} onClick={handleDelete}>删除题目</Button>
            </Space>
          </Card>
        ) : (
          <Alert message="请输入题目 ID 查询" type="info" />
        )}
      </Spin>
    </div>
  );
}
