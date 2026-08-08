import { useEffect, useState } from "react";
import {
  Alert,
  Card,
  Descriptions,
  List,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
} from "antd";
import { apiGet } from "../services/api";

const { Title, Text } = Typography;

interface MonitorDocument {
  id: number;
  filename: string;
  processing_status: string;
  subject: string | null;
  grade: string | null;
  ocr_markdown_chars: number | null;
  created_at: string;
}

interface MonitorLog {
  stage: string;
  message: string;
  created_at: string;
}

interface MonitorData {
  document: MonitorDocument | null;
  processing_logs: MonitorLog[];
  counts: Record<string, number>;
  solutions_by: Array<{ model_source: string; mode: string; c: number }>;
  redis_tasks: Array<{
    task_id: string;
    status: Record<string, unknown>;
    logs: Array<{ step?: string; message: string }>;
  }>;
}

interface NodeRow {
  key: string;
  name: string;
  status: "ok" | "warn" | "error" | "wait";
  detail: string;
}

function statusTag(status: NodeRow["status"]) {
  if (status === "ok") return <Tag color="success">OK</Tag>;
  if (status === "warn") return <Tag color="warning">WARN</Tag>;
  if (status === "error") return <Tag color="error">FAIL</Tag>;
  return <Tag>WAIT</Tag>;
}

export default function MonitorPage() {
  const [data, setData] = useState<MonitorData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;

    const load = async () => {
      try {
        const next = await apiGet<MonitorData>("/api/documents/monitor/latest");
        if (active) {
          setData(next);
          setError("");
        }
      } catch (e) {
        if (active) {
          setError(e instanceof Error ? e.message : String(e));
        }
      } finally {
        if (active) setLoading(false);
      }
    };

    load();
    const timer = setInterval(load, 5000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);

  if (loading && !data) {
    return (
      <div style={{ textAlign: "center", padding: 60 }}>
        <Spin size="large" />
      </div>
    );
  }

  const doc = data?.document ?? null;
  const counts = data?.counts ?? {};

  const nodes: NodeRow[] = [
    {
      key: "upload",
      name: "PDF 上传",
      status: doc ? "ok" : "wait",
      detail: doc ? doc.filename : "等待上传",
    },
    {
      key: "ocr",
      name: "OCR / PP-StructureV3",
      status: (counts.document_pages ?? 0) > 0 ? "ok" : "wait",
      detail: `${counts.document_pages ?? 0} pages / ${
        doc?.ocr_markdown_chars ?? 0
      } markdown chars`,
    },
    {
      key: "llm",
      name: "LLM 主提取",
      status: (counts.questions ?? 0) > 0 ? "ok" : "wait",
      detail: `${counts.questions ?? 0} questions`,
    },
    {
      key: "annotations",
      name: "L2 标注镜像",
      status: (counts.question_annotations ?? 0) > 0 ? "ok" : "error",
      detail: `${counts.question_annotations ?? 0} annotations`,
    },
    {
      key: "solutions",
      name: "解答",
      status: (counts.solutions ?? 0) > 0 ? "ok" : "wait",
      detail: `${counts.solutions ?? 0} solutions`,
    },
    {
      key: "explanation",
      name: "详解",
      status: (counts.solutions_with_explanation ?? 0) > 0 ? "ok" : "error",
      detail: `${counts.solutions_with_explanation ?? 0} explanations`,
    },
    {
      key: "embedding",
      name: "嵌入",
      status: (counts.question_embeddings ?? 0) > 0 ? "ok" : "error",
      detail: `${counts.question_embeddings ?? 0} embeddings`,
    },
    {
      key: "knowledge",
      name: "知识映射",
      status: (counts.question_knowledge ?? 0) > 0 ? "ok" : "wait",
      detail: `${counts.question_knowledge ?? 0} mappings`,
    },
    {
      key: "images",
      name: "图片关联",
      status: (counts.question_images ?? 0) > 0 ? "ok" : "wait",
      detail: `${counts.question_images ?? 0} images`,
    },
  ];

  const columns = [
    {
      title: "节点",
      dataIndex: "name",
      key: "name",
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      render: statusTag,
    },
    {
      title: "实测",
      dataIndex: "detail",
      key: "detail",
    },
  ];

  return (
    <div>
      <Title level={4}>Pipeline Monitor</Title>
      {error && <Alert type="error" message={error} showIcon style={{ marginBottom: 16 }} />}

      {doc && (
        <Card style={{ marginBottom: 16 }}>
          <Descriptions
            size="small"
            column={{ xs: 1, sm: 2, lg: 4 }}
            items={[
              { key: "file", label: "文件", children: doc.filename },
              { key: "status", label: "文档状态", children: doc.processing_status },
              { key: "subject", label: "学科", children: doc.subject ?? "-" },
              { key: "grade", label: "年级", children: doc.grade ?? "-" },
              { key: "markdown", label: "OCR markdown", children: `${doc.ocr_markdown_chars ?? 0} chars` },
              { key: "created", label: "创建时间", children: doc.created_at },
            ]}
          />
        </Card>
      )}

      <Card title="节点处理情况" style={{ marginBottom: 16 }}>
        <Table
          rowKey="key"
          columns={columns}
          dataSource={nodes}
          pagination={false}
          size="small"
        />
      </Card>

      <Space direction="vertical" size={16} style={{ width: "100%" }}>
        <Card title="持久化处理日志">
          <List
            size="small"
            dataSource={data?.processing_logs ?? []}
            locale={{ emptyText: "暂无日志" }}
            renderItem={(log) => (
              <List.Item>
                <Space direction="vertical" size={0} style={{ width: "100%" }}>
                  <Space>
                    <Tag>{log.stage}</Tag>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {log.created_at}
                    </Text>
                  </Space>
                  <Text>{log.message}</Text>
                </Space>
              </List.Item>
            )}
          />
        </Card>

        {data?.redis_tasks.map((task) => (
          <Card key={task.task_id} title={`Redis 任务 ${task.task_id.slice(0, 8)}`}>
            <Descriptions
              size="small"
              column={{ xs: 1, sm: 2 }}
              items={[
                {
                  key: "state",
                  label: "状态",
                  children: String(task.status.state ?? "-"),
                },
                {
                  key: "step",
                  label: "当前步骤",
                  children: String(task.status.current_step ?? "-"),
                },
                {
                  key: "steps",
                  label: "已完成",
                  children: Array.isArray(task.status.steps_completed)
                    ? task.status.steps_completed.join(", ")
                    : "-",
                },
              ]}
            />
            <List
              size="small"
              dataSource={task.logs.slice(-20)}
              locale={{ emptyText: "暂无步骤日志" }}
              renderItem={(log) => (
                <List.Item>
                  <Space direction="vertical" size={0} style={{ width: "100%" }}>
                    {log.step && <Tag>{log.step}</Tag>}
                    <Text>{log.message}</Text>
                  </Space>
                </List.Item>
              )}
            />
          </Card>
        ))}
      </Space>
    </div>
  );
}
