import { useState, useRef, useEffect } from "react";
import {
  Card, Input, Button, Upload, Typography, Space, Steps,
  Tag, Spin, Alert, Divider, Checkbox, Image,
} from "antd";
import {
  SendOutlined, CameraOutlined, LoadingOutlined,
  CheckCircleOutlined, ExclamationCircleOutlined, BulbOutlined,
} from "@ant-design/icons";
import type { UploadFile } from "antd/es/upload";
import QuestionQueue from "../../components/QuestionQueue";
import type { QuestionStatus } from "../../components/QuestionQueue";
import MathRenderer from "../../components/MathRenderer";
import { useSSEStream } from "../../hooks/useSSEStream";
import type { SSEEvent, QuestionRecord, SolutionData } from "../../types";
import { DIFFICULTY_LABELS, DIFFICULTY_COLORS } from "../../types";

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;

const QUESTIONS_STORAGE_KEY = "aitutor_questions";

function loadQuestions(): QuestionRecord[] {
  try {
    const raw = localStorage.getItem(QUESTIONS_STORAGE_KEY);
    if (!raw) return [];
    const all: QuestionRecord[] = JSON.parse(raw);
    // Only keep finished questions; discard in-progress ones from previous sessions
    return all.filter((q) => q.status === "done" || q.status === "error");
  } catch {
    return [];
  }
}

function saveQuestions(questions: QuestionRecord[]) {
  try {
    localStorage.setItem(QUESTIONS_STORAGE_KEY, JSON.stringify(questions));
  } catch { /* ignore */ }
}

export default function AskPage() {
  const [input, setInput] = useState("");
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [questions, setQuestions] = useState<QuestionRecord[]>(loadQuestions);
  const [loading, setLoading] = useState(false);
  const [selectedExamQuestions, setSelectedExamQuestions] = useState<number[]>([]);
  const chatRef = useRef<HTMLDivElement>(null);
  const idCounterRef = useRef<number>(Date.now());
  const { connect } = useSSEStream();

  // Persist questions to localStorage on change
  useEffect(() => {
    saveQuestions(questions);
  }, [questions]);

  const scrollToBottom = () => {
    setTimeout(() => {
      chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight, behavior: "smooth" });
    }, 100);
  };

  const handleSubmit = async (e?: React.MouseEvent) => {
    e?.preventDefault();
    e?.stopPropagation();
    if (!input.trim() && fileList.length === 0) return;
    if (loading) return;
    setLoading(true);

    const record: QuestionRecord = {
      id: ++idCounterRef.current,
      text: input.trim(),
      image: fileList.length > 0 ? fileList[0].name : null,
      status: "asking",
    };
    setQuestions((prev) => [...prev, record]);

    // Capture form values BEFORE clearing state
    const formData = new FormData();
    const textValue = input.trim();
    const imageFile = fileList.length > 0 ? fileList[0].originFileObj : null;
    if (textValue) formData.append("question_text", textValue);
    if (imageFile) formData.append("image", imageFile);

    // Clear form AFTER capturing
    setInput("");
    setFileList([]);

    let sessionId = "";
    let hint = "";
    let difficulty = 0;
    let _studentQuestionId = 0;

    // Fire-and-forget: all state updates happen via callbacks
    let eventsReceived = false;
    connect("/api/student/ask", formData, {
      onEvent: (data: SSEEvent) => {
        eventsReceived = true;

        if (data.session_id) sessionId = data.session_id;
        if (data.student_question_id != null) _studentQuestionId = data.student_question_id;

        if (data.phase === "processing" || data.phase === "processing_done") {
          setQuestions((prev) =>
            prev.map((q) =>
              q.id === record.id
                ? { ...q, status: "processing", text: record.text || "（图片题目）" }
                : q
            )
          );
        }

        if (data.phase === "question_reveal") {
          const revealText = data.question_text || record.text || "（题目）";
          const examQs = data.questions || [];
          const isExam = data.is_exam === true;
          const imageUrls = data.images || [];

          if (data.student_question_id != null) _studentQuestionId = data.student_question_id;

          setQuestions((prev) =>
            prev.map((q) =>
              q.id === record.id
                ? {
                    ...q,
                    status: "revealing",
                    text: revealText,
                    sessionId,
                    studentQuestionId: _studentQuestionId,
                    examQuestions: isExam ? examQs : undefined,
                    images: imageUrls.length > 0 ? imageUrls : undefined,
                  }
                : q
            )
          );
        }

        if (data.phase === "hint") {
          if (data.thinking_hint) hint = data.thinking_hint;
          if (data.difficulty !== undefined) difficulty = data.difficulty;
          if (data.student_question_id != null) _studentQuestionId = data.student_question_id;
          setQuestions((prev) =>
            prev.map((q) =>
              q.id === record.id
                ? {
                    ...q,
                    status: "hint",
                    sessionId,
                    hint,
                    difficulty,
                    studentQuestionId: _studentQuestionId,
                  }
                : q
            )
          );
        }

        if (data.phase === "done") {
          setQuestions((prev) =>
            prev.map((q) =>
              q.id === record.id
                ? { ...q, status: q.status === "revealing" ? "revealing" : "choosing", sessionId }
                : q
            )
          );
          setLoading(false);
        }

        if (data.phase === "error") {
          setQuestions((prev) =>
            prev.map((q) =>
              q.id === record.id ? { ...q, status: "done", error: data.message } : q
            )
          );
          setLoading(false);
        }
      },
      onError: (err) => {
        if (eventsReceived) return;
        setQuestions((prev) =>
          prev.map((q) =>
            q.id === record.id
              ? { ...q, status: "done", error: err.message || "请求失败" }
              : q
          )
        );
        setLoading(false);
      },
    });

    scrollToBottom();
  };

  const handleConfirm = (record: QuestionRecord) => {
    if (!record.sessionId || record.studentQuestionId == null || !record.text) return;

    setQuestions((prev) =>
      prev.map((q) => (q.id === record.id ? { ...q, status: "processing" } : q))
    );

    const formData = new FormData();
    formData.append("student_question_id", String(record.studentQuestionId));
    formData.append("question_text", record.text);
    formData.append("session_id", record.sessionId);

    let difficulty = 0;
    let hint = "";

    let eventsReceived = false;
    connect("/api/student/confirm", formData, {
      onEvent: (data: SSEEvent) => {
        eventsReceived = true;
        if (data.phase === "hint") {
          if (data.thinking_hint) hint = data.thinking_hint;
          if (data.difficulty !== undefined) difficulty = data.difficulty;
          if (data.student_question_id != null) record.studentQuestionId = data.student_question_id;
          setQuestions((prev) =>
            prev.map((q) =>
              q.id === record.id
                ? { ...q, status: "hint", hint, difficulty, studentQuestionId: record.studentQuestionId }
                : q
            )
          );
        }
        if (data.phase === "done") {
          setQuestions((prev) =>
            prev.map((q) =>
              q.id === record.id ? { ...q, status: "choosing" } : q
            )
          );
        }
        if (data.phase === "error") {
          setQuestions((prev) =>
            prev.map((q) =>
              q.id === record.id ? { ...q, status: "done", error: data.message } : q
            )
          );
        }
      },
      onError: (err) => {
        if (eventsReceived) return;
        setQuestions((prev) =>
          prev.map((q) =>
            q.id === record.id ? { ...q, status: "done", error: err.message || "请求失败" } : q
          )
        );
      },
    });
  };

  const handleChoose = (record: QuestionRecord, choice: "think" | "explain") => {
    if (!record.sessionId || !record.id) return;
    const sqId = record.studentQuestionId;
    if (sqId == null) return;

    setQuestions((prev) =>
      prev.map((q) => (q.id === record.id ? { ...q, status: "solving" } : q))
    );

    const formData = new FormData();
    formData.append("student_question_id", String(sqId));
    formData.append("choice", choice);
    formData.append("session_id", record.sessionId);

    let solution: SolutionData | undefined;

    let eventsReceived = false;
    connect("/api/student/choose", formData, {
      onEvent: (data: SSEEvent) => {
        eventsReceived = true;

        if (data.phase === "solution" && data.solution) {
          solution = data.solution;
          // Apply solution immediately — don't wait for "done" (which may be lost to abort)
          setQuestions((prev) =>
            prev.map((q) =>
              q.id === record.id ? { ...q, status: "done", solution } : q
            )
          );
        }
        if (data.phase === "thinking") {
          setQuestions((prev) =>
            prev.map((q) =>
              q.id === record.id ? { ...q, status: "thinking" } : q
            )
          );
        }
        if (data.phase === "done") {
          // Apply solution if not already applied by "solution" event
          if (solution) {
            setQuestions((prev) =>
              prev.map((q) =>
                q.id === record.id ? { ...q, status: "done", solution } : q
              )
            );
          } else {
            setQuestions((prev) =>
              prev.map((q) =>
                q.id === record.id ? { ...q, status: "done" } : q
              )
            );
          }
        }
      },
      onError: () => {
        if (eventsReceived) return;
        setQuestions((prev) =>
          prev.map((q) =>
            q.id === record.id ? { ...q, status: "done", error: "获取解答失败" } : q
          )
        );
      },
    });
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div style={{ maxWidth: "var(--page-max-width)", margin: "0 auto", padding: "var(--page-padding)" }}>
      <Title level={3}>AI Tutor — 提问</Title>

      <Card className="card-hover-lift" style={{ marginBottom: "var(--card-gap)" }}>
        <TextArea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="输入题目文字，或上传题目图片..."
          rows={3}
          style={{ marginBottom: 12 }}
          disabled={loading}
        />
        <Space style={{ width: "100%", justifyContent: "space-between" }}>
          <Upload
            fileList={fileList}
            beforeUpload={(file) => {
              setFileList([{ uid: "-1", name: file.name, status: "done", originFileObj: file as UploadFile["originFileObj"] }]);
              return false;
            }}
            onRemove={() => setFileList([])}
            accept=".jpg,.jpeg,.png,.bmp,.gif,.webp,.pdf"
            maxCount={1}
          >
            <Button icon={<CameraOutlined />} disabled={loading}>
              上传题目
            </Button>
          </Upload>
          <Button
            type="primary"
            htmlType="button"
            icon={loading ? <LoadingOutlined /> : <SendOutlined />}
            onClick={handleSubmit}
            disabled={(!input.trim() && fileList.length === 0) || loading}
            loading={loading}
          >
            发送
          </Button>
        </Space>
      </Card>

      <div ref={chatRef} style={{ maxHeight: "60vh", overflowY: "auto" }}>
        {questions.length > 1 && (
          <QuestionQueue
            questions={questions.map((q) => ({ id: q.id, text: q.text, status: q.status as QuestionStatus }))}
            onSelect={(id) => {
              const el = document.getElementById(`question-card-${id}`);
              el?.scrollIntoView({ behavior: "smooth" });
            }}
            selectedId={questions[questions.length - 1]?.id}
          />
        )}

        {questions.length === 0 && !loading && (
          <Alert
            message="欢迎使用 AI Tutor"
            description="输入题目文字或上传题目图片，获取思考提示和解题步骤。"
            type="info"
            showIcon
          />
        )}

        {questions.map((q) => (
          <Card key={q.id} id={`question-card-${q.id}`} className="card-hover-lift" style={{ marginBottom: 12 }}>
            <div style={{ marginBottom: 12 }}>
              <Tag color="blue">我的提问</Tag>
              <Paragraph style={{ marginTop: 4 }}>{q.text || "（图片题目）"}</Paragraph>
              {q.image && <Tag icon={<CameraOutlined />}>{q.image}</Tag>}
              {q.images && q.images.length > 0 && (
                <div style={{ marginTop: 8 }}>
                  {q.images.map((imgKey, idx) => (
                    <img
                      key={idx}
                      src={`/api/documents/images/${imgKey}`}
                      alt={`题目图片 ${idx + 1}`}
                      style={{ maxWidth: "100%", maxHeight: 300, marginRight: 8, marginBottom: 8, border: "1px solid var(--color-border)", borderRadius: "var(--radius)" }}
                    />
                  ))}
                </div>
              )}
            </div>

            {q.status === "processing" && (
              <div style={{ textAlign: "center", padding: 16 }}>
                <Spin indicator={<LoadingOutlined />} />
                <Paragraph type="secondary" style={{ marginTop: 8 }}>正在分析题目...</Paragraph>
                <Steps
                  size="small"
                  current={1}
                  items={[
                    { title: "识别题目" },
                    { title: "还原题目" },
                    { title: "生成方案" },
                  ]}
                  style={{ marginTop: 12 }}
                />
              </div>
            )}

            {q.status === "revealing" && (
              <div style={{ background: "var(--bg-reveal)", padding: 16, borderRadius: "var(--radius)", marginBottom: 8, borderLeft: "4px solid var(--color-warning)" }}>
                <Space align="start">
                  <BulbOutlined style={{ color: "var(--color-warning)", fontSize: 18, marginTop: 4 }} />
                  <div style={{ flex: 1 }}>
                    <Text strong>我们识别到以下题目，请确认是否正确：</Text>
                    {q.examQuestions && q.examQuestions.length > 1 ? (
                      <div style={{ margin: "12px 0" }}>
                        <Space style={{ marginBottom: 8 }}>
                          <Text type="secondary">
                            检测到试卷中包含 {q.examQuestions.length} 道题目，请选择要咨询的题目：
                          </Text>
                          <Checkbox
                            checked={selectedExamQuestions.length === q.examQuestions.length}
                            indeterminate={selectedExamQuestions.length > 0 && selectedExamQuestions.length < q.examQuestions.length}
                            onChange={(e) => {
                              if (e.target.checked) {
                                setSelectedExamQuestions(q.examQuestions!.map(eq => eq.index));
                              } else {
                                setSelectedExamQuestions([]);
                              }
                            }}
                          >
                            全选
                          </Checkbox>
                        </Space>
                        {q.examQuestions.map((eq) => (
                          <Card
                            key={eq.index}
                            size="small"
                            style={{ margin: "8px 0", background: selectedExamQuestions.includes(eq.index) ? "var(--color-primary-bg)" : "var(--color-bg-container)" }}
                            title={
                              <Checkbox
                                checked={selectedExamQuestions.includes(eq.index)}
                                onChange={(e) => {
                                  if (e.target.checked) {
                                    setSelectedExamQuestions(prev => [...prev, eq.index]);
                                  } else {
                                    setSelectedExamQuestions(prev => prev.filter(i => i !== eq.index));
                                  }
                                }}
                              >
                                {eq.label}
                              </Checkbox>
                            }
                          >
                            <Paragraph style={{ margin: 0 }}>{eq.text}</Paragraph>
                            {eq.images && eq.images.length > 0 && (
                              <div style={{ marginTop: 8 }}>
                                <Image.PreviewGroup>
                                  {eq.images.map((imgKey, imgIdx) => (
                                    <Image
                                      key={imgIdx}
                                      src={`/api/documents/images/${imgKey}`}
                                      alt={`${eq.label} 图片`}
                                      width={120}
                                      style={{ marginRight: 8, borderRadius: 4 }}
                                    />
                                  ))}
                                </Image.PreviewGroup>
                              </div>
                            )}
                          </Card>
                        ))}
                        <div style={{ textAlign: "center", marginTop: 12 }}>
                          <Button
                            type="primary"
                            size="large"
                            disabled={selectedExamQuestions.length === 0}
                            onClick={() => handleConfirm(q)}
                          >
                            确认选中的 {selectedExamQuestions.length} 道题目，开始解答
                          </Button>
                        </div>
                      </div>
                    ) : (
                      <div>
                        <Paragraph
                          style={{
                            marginTop: 8,
                            padding: 12,
                            background: "#fff",
                            borderRadius: 4,
                            whiteSpace: "pre-wrap",
                          }}
                        >
                          {q.text || "（未能识别题目文字，请手动输入）"}
                        </Paragraph>
                        {q.images && q.images.length > 0 && (
                          <div style={{ marginTop: 8 }}>
                            <Image.PreviewGroup>
                              {q.images.map((imgKey, imgIdx) => (
                                <Image
                                  key={imgIdx}
                                  src={`/api/documents/images/${imgKey}`}
                                  alt={`题目图片 ${imgIdx + 1}`}
                                  width={120}
                                  style={{ marginRight: 8, borderRadius: 4 }}
                                />
                              ))}
                            </Image.PreviewGroup>
                          </div>
                        )}
                      </div>
                    )}
                    <div style={{ textAlign: "center", marginTop: 12 }}>
                      <Button
                        type="primary"
                        size="large"
                        onClick={() => handleConfirm(q)}
                      >
                        确认题目，开始解答
                      </Button>
                    </div>
                  </div>
                </Space>
              </div>
            )}

            {(q.status === "hint" || q.status === "choosing" || q.status === "thinking" || q.status === "solving") && (
              <div style={{ background: "var(--bg-hint)", padding: 12, borderRadius: "var(--radius)", marginBottom: 8, borderLeft: "4px solid var(--color-success)" }}>
                <Space align="start">
                  <BulbOutlined style={{ color: "var(--color-success)", fontSize: 18, marginTop: 4 }} />
                  <div>
                    <Text strong>思考提示</Text>
                    {q.difficulty != null && q.difficulty > 0 && (
                      <Tag color={DIFFICULTY_COLORS[q.difficulty]} style={{ marginLeft: 8 }}>
                        {DIFFICULTY_LABELS[q.difficulty]}
                      </Tag>
                    )}
                    <Paragraph style={{ marginTop: 4 }}><MathRenderer content={q.hint || ""} /></Paragraph>
                  </div>
                </Space>
              </div>
            )}

            {q.status === "thinking" && (
              <div style={{ textAlign: "center", margin: "12px 0" }}>
                <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                  <Alert
                    message="请先独立思考，完成后再查看讲解"
                    type="info"
                    showIcon
                  />
                  <Button
                    type="primary"
                    size="large"
                    onClick={() => handleChoose(q, "explain")}
                  >
                    查看讲解
                  </Button>
                </Space>
              </div>
            )}

            {q.status === "choosing" && (
              <div style={{ textAlign: "center", margin: "12px 0" }}>
                <Space size="large">
                  <Button type="default" size="large" onClick={() => handleChoose(q, "think")}>
                    我先思考
                  </Button>
                  <Button type="primary" size="large" onClick={() => handleChoose(q, "explain")}>
                    直接讲解
                  </Button>
                </Space>
              </div>
            )}

            {q.status === "solving" && (
              <div style={{ textAlign: "center", padding: 16 }}>
                <Spin indicator={<LoadingOutlined />} />
                <Paragraph type="secondary" style={{ marginTop: 8 }}>正在生成解题步骤...</Paragraph>
              </div>
            )}

            {q.status === "done" && q.solution && (
              <div style={{ background: "var(--bg-solution)", padding: 16, borderRadius: "var(--radius)", borderLeft: "4px solid var(--color-info)" }}>
                <Title level={5}>
                  <CheckCircleOutlined style={{ color: "var(--color-info)", marginRight: "var(--radius)" }} />
                  解题步骤
                </Title>
                <Paragraph strong>答案：<MathRenderer content={q.solution.final_answer} /></Paragraph>
                <Divider />
                {q.solution.solution_steps?.map((s: { step: number; description: string }) => (
                  <Paragraph key={s.step}>
                    <Tag color="blue">{s.step}</Tag> <MathRenderer content={s.description} />
                  </Paragraph>
                ))}
                {q.solution.knowledge_points && q.solution.knowledge_points.length > 0 && (
                  <>
                    <Divider />
                    <Text strong>知识点：</Text>
                    <Space wrap style={{ marginTop: 4 }}>
                      {q.solution.knowledge_points.map((kp: string) => (
                        <Tag key={kp} color="purple">{kp}</Tag>
                      ))}
                    </Space>
                  </>
                )}
                {q.solution.explanation && (
                  <Alert
                    message="总结"
                    description={q.solution.explanation}
                    type="success"
                    style={{ marginTop: 12 }}
                  />
                )}
              </div>
            )}

            {q.error && (
              <Alert
                message="处理出错"
                description={q.error}
                type="error"
                showIcon
                icon={<ExclamationCircleOutlined />}
                style={{ marginTop: 8 }}
              />
            )}
          </Card>
        ))}
      </div>
    </div>
  );
}
