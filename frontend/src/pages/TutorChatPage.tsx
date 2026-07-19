import { useState, useRef } from "react";
import { Input, Button, Card, Typography, Space, Select, Tag } from "antd";
import { SendOutlined, RobotOutlined, UserOutlined } from "@ant-design/icons";
import { useSSEStream } from "../hooks/useSSEStream";
import type { SSEEvent } from "../types";

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

const MODE_OPTIONS = [
  { value: "tutor", label: "引导式辅导" },
  { value: "reasoning", label: "完整解答" },
  { value: "fast", label: "快速回答" },
];

export default function TutorChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [mode, setMode] = useState("tutor");
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { connect } = useSSEStream();

  const sendMessage = async () => {
    if (!input.trim() || loading) return;

    const userMsg: ChatMessage = { role: "user", content: input.trim() };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    let assistantContent = "";
    setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

    connect("/api/tutor/chat", JSON.stringify({
      question_text: userMsg.content,
      mode,
      subject: "",
    }), {
      onEvent: (data: SSEEvent & { text?: string }) => {
        if (data.text) {
          assistantContent += data.text;
          setMessages((prev) => {
            const updated = [...prev];
            updated[updated.length - 1] = { role: "assistant", content: assistantContent };
            return updated;
          });
        }
        if (data.phase === "done" || data.phase === "error") {
          setLoading(false);
        }
      },
      onError: () => {
        setMessages((prev) => [...prev, { role: "assistant", content: "Error: Connection failed" }]);
        setLoading(false);
      },
    });

    setLoading(false);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "calc(100vh - 160px)" }}>
      <Title level={4}>辅导对话</Title>

      <Space style={{ marginBottom: 12 }}>
        <Text>模式:</Text>
        <Select value={mode} onChange={setMode} options={MODE_OPTIONS} style={{ width: 200 }} />
        {mode === "tutor" && <Tag color="green">循序渐进引导</Tag>}
        {mode === "reasoning" && <Tag color="blue">完整解题过程</Tag>}
        {mode === "fast" && <Tag color="orange">快速给出答案</Tag>}
      </Space>

      <Card
        style={{ flex: 1, overflow: "auto", marginBottom: 12 }}
        bodyStyle={{ padding: 12 }}
      >
        {messages.length === 0 && (
          <Text type="secondary" style={{ display: "block", textAlign: "center", padding: 40 }}>
            输入题目，开始辅导对话
          </Text>
        )}
        {messages.map((msg, i) => (
          <div
            key={i}
            style={{
              display: "flex",
              justifyContent: msg.role === "user" ? "flex-end" : "flex-start",
              marginBottom: 8,
            }}
          >
            <Card
              size="small"
              style={{
                maxWidth: "80%",
                background: msg.role === "user" ? "var(--color-primary)" : "var(--color-canvas-parchment)",
              }}
              bodyStyle={{ padding: "8px 12px" }}
            >
              <Space align="start">
                {msg.role === "user" ? (
                  <UserOutlined style={{ color: "var(--color-text-on-dark)" }} />
                ) : (
                  <RobotOutlined style={{ color: "var(--color-info)" }} />
                )}
                <Paragraph
                  style={{
                    margin: 0,
                    color: msg.role === "user" ? "var(--color-text-on-dark)" : "var(--color-text)",
                    whiteSpace: "pre-wrap",
                  }}
                >
                  {msg.content}
                </Paragraph>
              </Space>
            </Card>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </Card>

      <Space.Compact style={{ width: "100%" }}>
        <TextArea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onPressEnter={(e) => {
            if (!e.shiftKey) {
              e.preventDefault();
              sendMessage();
            }
          }}
          placeholder="输入题目...（Shift+Enter 换行）"
          autoSize={{ minRows: 1, maxRows: 4 }}
          disabled={loading}
        />
        <Button
          type="primary"
          icon={<SendOutlined />}
          onClick={sendMessage}
          loading={loading}
        >
          发送
        </Button>
      </Space.Compact>
    </div>
  );
}
