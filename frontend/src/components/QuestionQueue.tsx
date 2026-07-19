import { Tag, Space } from "antd";
import {
  LoadingOutlined,
  BulbOutlined,
  FormOutlined,
  CheckCircleOutlined,
} from "@ant-design/icons";

export type QuestionStatus =
  | "asking"
  | "processing"
  | "revealing"
  | "hint"
  | "choosing"
  | "thinking"
  | "solving"
  | "done";

interface QueueItem {
  id: number;
  text: string;
  status: QuestionStatus;
}

interface Props {
  questions: QueueItem[];
  onSelect?: (id: number) => void;
  selectedId?: number;
}

const STATUS_CONFIG: Record<
  QuestionStatus,
  { label: string; color: string; icon: React.ReactNode }
> = {
  asking: { label: "已提交", color: "default", icon: null },
  processing: {
    label: "分析中",
    color: "processing",
    icon: <LoadingOutlined />,
  },
  hint: {
    label: "展示提示",
    color: "green",
    icon: <BulbOutlined />,
  },
  revealing: {
    label: "确认题目",
    color: "gold",
    icon: <FormOutlined />,
  },
  choosing: {
    label: "等待选择",
    color: "blue",
    icon: <FormOutlined />,
  },
  thinking: {
    label: "独立思考中",
    color: "cyan",
    icon: <BulbOutlined />,
  },
  solving: {
    label: "解题中",
    color: "processing",
    icon: <LoadingOutlined />,
  },
  done: {
    label: "已完成",
    color: "success",
    icon: <CheckCircleOutlined />,
  },
};

export default function QuestionQueue({ questions, onSelect, selectedId }: Props) {
  if (questions.length <= 1) return null;

  return (
    <div
      style={{
        borderBottom: "1px solid var(--color-border-secondary)",
        padding: "8px 16px",
        marginBottom: 16,
        background: "var(--color-bg-layout)",
        overflowX: "auto",
      }}
    >
      <Space wrap size={[8, 0]}>
        {questions.map((q) => {
          const config = STATUS_CONFIG[q.status];
          return (
            <Tag
              key={q.id}
              color={selectedId === q.id ? "blue" : config.color}
              style={{
                cursor: onSelect ? "pointer" : "default",
                margin: 4,
                padding: "2px 8px",
                opacity: selectedId === q.id ? 1 : 0.8,
              }}
              onClick={() => onSelect?.(q.id)}
            >
              <Space size={4}>
                {config.icon}
                <span>
                  {q.text.slice(0, 12)}
                  {q.text.length > 12 ? "…" : ""}
                </span>
                <span style={{ fontSize: 11 }}>({config.label})</span>
              </Space>
            </Tag>
          );
        })}
      </Space>
    </div>
  );
}
