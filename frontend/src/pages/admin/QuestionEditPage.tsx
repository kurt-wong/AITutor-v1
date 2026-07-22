import { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Card, Typography, Input, Select, Button, Space, Spin, Alert, message, Tag, Divider, Image,
} from "antd";
import { EditOutlined, SaveOutlined, DeleteOutlined, PictureOutlined } from "@ant-design/icons";
import { apiGet, apiPutForm, apiDelete } from "../../services/api";
import { DIFFICULTY_LABELS } from "../../types";
import MathRenderer from "../../components/MathRenderer";

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;

interface QuestionImage {
  image_id: number;
  image_key: string;
  image_type: string;
  description: string | null;
  created_at: string;
}

interface QuestionDetail {
  id: number;
  document_id: number | null;
  subject_id: number | null;
  subject_name: string | null;
  question_number: string | null;
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
            <Tag color="blue">#{question.id}</Tag>
            <Paragraph style={{ marginTop: 8 }}><MathRenderer content={question.content || ""} /></Paragraph>
            {question.subject_name && <Tag>{question.subject_name}</Tag>}
            {question.images && question.images.length > 0 && (
              <>
                <Divider />
                <Title level={5}><PictureOutlined style={{ marginRight: "var(--radius)" }} />关联图片</Title>
                <Space wrap>
                  {question.images.map((img) => (
                    <div key={img.image_id} style={{ textAlign: "center" }}>
                      <Image
                        src={`/api/documents/images/${img.image_key}`}
                        alt={img.description || `图片 ${img.image_id}`}
                        width={200}
                        style={{ borderRadius: 8, border: "1px solid #f0f0f0" }}
                      />
                      <div style={{ fontSize: 12, color: "#999", marginTop: 4 }}>
                        {img.image_type} · {img.description || ""}
                      </div>
                    </div>
                  ))}
                </Space>
              </>
            )}
            <Divider />
            <Space>
              <Text strong>难度:</Text>
              <Select value={difficulty} onChange={setDifficulty} options={difficultyOptions} style={{ width: 120 }} />
              <Button type="primary" icon={<SaveOutlined />} onClick={handleSaveMeta} loading={saving}>保存</Button>
            </Space>
            <Divider />
            <Title level={5}>解答</Title>
            <Text strong>答案:</Text>
            <TextArea value={editAnswer} onChange={(e) => setEditAnswer(e.target.value)} rows={2} style={{ marginBottom: 8 }} />
            <Text strong>步骤 (JSON):</Text>
            <TextArea value={editSteps} onChange={(e) => setEditSteps(e.target.value)} rows={4} style={{ marginBottom: 8 }} />
            <Text strong>讲解:</Text>
            <TextArea value={editExplanation} onChange={(e) => setEditExplanation(e.target.value)} rows={3} style={{ marginBottom: 8 }} />
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
