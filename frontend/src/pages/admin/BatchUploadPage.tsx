import { useState, useEffect, useRef } from "react";
import {
  Card, Upload, Select, Button, Typography, Space, Table, Tag, Progress, message,
} from "antd";
import { UploadOutlined, SyncOutlined, CheckCircleOutlined, CloseCircleOutlined } from "@ant-design/icons";
import type { UploadFile } from "antd/es/upload";
import type { ColumnsType } from "antd/es/table";
import { apiGet, apiPostForm, LONG_TIMEOUT_MS } from "../../services/api";
import { SUBJECTS, GRADES, CATEGORIES } from "../../types";

const { Dragger } = Upload;
const { Title, Text } = Typography;

interface UploadResult {
  filename: string;
  success: boolean;
  document_id: number | null;
  task_id: string | null;
  error: string | null;
}

interface TaskProgress {
  task_id: string;
  filename: string;
  document_id: number | null;
  state: string;
  progress: number;
  current_step: string;
  detail: string;
  questions_count?: number;
}

const STEP_LABELS: Record<string, string> = {
  start: "准备中",
  download: "下载文件",
  convert: "转换 PDF",
  ocr: "OCR 识别",
  store: "保存题目",
  solve: "生成解答",
  difficulty: "评估难度",
  done: "处理完成",
  error: "处理失败",
};

export default function BatchUploadPage() {
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [subject, setSubject] = useState<string | undefined>();
  const [grade, setGrade] = useState<string | undefined>();
  const [category, setCategory] = useState<string | undefined>();
  const [uploading, setUploading] = useState(false);
  const [results, setResults] = useState<UploadResult[]>([]);
  const [tasks, setTasks] = useState<TaskProgress[]>([]);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, []);

  const handleUpload = async () => {
    if (fileList.length === 0) return;
    setUploading(true);
    setTasks([]);

    try {
      const formData = new FormData();
      fileList.forEach((f) => {
        if (f.originFileObj) formData.append("files", f.originFileObj);
      });
      if (subject) formData.append("subject", subject);
      if (grade) formData.append("grade", grade);
      if (category) formData.append("category", category);

      const data = await apiPostForm<{ data?: { results: UploadResult[] } }>(
        "/api/admin/documents/batch-upload",
        formData,
        LONG_TIMEOUT_MS
      );
      const body = (data as any).data || data;
      const uploadResults = body.results || [];
      setResults(uploadResults);
      setFileList([]);

      // Initialize task progress tracking
      const initialTasks: TaskProgress[] = uploadResults
        .filter((r: UploadResult) => r.success && r.task_id)
        .map((r: UploadResult) => ({
          task_id: r.task_id!,
          filename: r.filename,
          document_id: r.document_id,
          state: "pending",
          progress: 0,
          current_step: "start",
          detail: "等待处理...",
        }));
      setTasks(initialTasks);

      const successCount = uploadResults.filter((r: UploadResult) => r.success).length;
      const total = uploadResults.length;
      message.success(`上传完成：${successCount}/${total} 成功，正在后台处理...`);

      // Start polling for progress
      if (initialTasks.length > 0) {
        startPolling(initialTasks.map((t: TaskProgress) => t.task_id));
      }
    } catch (err: any) {
      message.error(`上传失败：${err?.message || "请检查网络或文件大小"}`);
    } finally {
      setUploading(false);
    }
  };

  const startPolling = (taskIds: string[]) => {
    if (pollingRef.current) clearInterval(pollingRef.current);

    const doPoll = async () => {
      try {
        const idsParam = taskIds.join(",");
        const data = await apiGet<{ tasks: Record<string, { status: any; logs: any[] }> }>(
          `/api/documents/tasks/batch/${idsParam}`
        );

        if (!data?.tasks) return;

        let allDone = true;

        setTasks((prev) =>
          prev.map((t) => {
            const taskData = data.tasks[t.task_id];
            if (!taskData) return t;

            const status = taskData.status;
            const state = status.state || "unknown";

            if (state !== "completed" && state !== "failed") {
              allDone = false;
            }

            return {
              ...t,
              state,
              progress: status.progress ?? 0,
              current_step: status.current_step || "unknown",
              detail: status.detail || "",
              questions_count: status.questions_count,
            };
          })
        );

        if (allDone) {
          if (pollingRef.current) clearInterval(pollingRef.current);
          pollingRef.current = null;
          message.success("所有文件处理完成！");
        }
      } catch {
        // Polling error, will retry
      }
    };

    pollingRef.current = setInterval(doPoll, 3000); // Poll every 3 seconds, single batch request
  };

  const getProgressStatus = (task: TaskProgress) => {
    if (task.state === "completed") return "success";
    if (task.state === "failed") return "exception";
    return "active";
  };

  const taskColumns: ColumnsType<TaskProgress> = [
    {
      title: "文件名",
      dataIndex: "filename",
      key: "filename",
      ellipsis: true,
    },
    {
      title: "状态",
      key: "status",
      width: 120,
      render: (_, task) => {
        if (task.state === "completed") {
          return <Tag icon={<CheckCircleOutlined />} color="success">完成</Tag>;
        }
        if (task.state === "failed") {
          return <Tag icon={<CloseCircleOutlined />} color="error">失败</Tag>;
        }
        return <Tag icon={<SyncOutlined spin />} color="processing">处理中</Tag>;
      },
    },
    {
      title: "进度",
      key: "progress",
      width: 200,
      render: (_, task) => (
        <Progress
          percent={Math.max(0, task.progress)}
          size="small"
          status={getProgressStatus(task)}
          format={() => task.state === "failed" ? "失败" : `${Math.max(0, task.progress)}%`}
        />
      ),
    },
    {
      title: "当前步骤",
      key: "step",
      width: 150,
      render: (_, task) => (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {STEP_LABELS[task.current_step] || task.current_step}
        </Text>
      ),
    },
    {
      title: "详情",
      key: "detail",
      ellipsis: true,
      render: (_, task) => (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {task.detail}
          {task.questions_count !== undefined && ` (${task.questions_count} 道题)`}
        </Text>
      ),
    },
  ];

  const resultColumns: ColumnsType<UploadResult> = [
    { title: "文件名", dataIndex: "filename", key: "filename" },
    {
      title: "上传状态",
      dataIndex: "success",
      key: "success",
      render: (ok: boolean) => ok ? <Tag color="green">成功</Tag> : <Tag color="red">失败</Tag>,
    },
    { title: "文档 ID", dataIndex: "document_id", key: "document_id", render: (id: number | null) => (id !== null ? id : "-") },
    { title: "错误信息", dataIndex: "error", key: "error", ellipsis: true, render: (err: string | null) => err || "-" },
  ];

  return (
    <div style={{ maxWidth: "var(--page-max-width)", margin: "0 auto", padding: "var(--page-padding)" }}>
      <Title level={3}><UploadOutlined style={{ marginRight: "var(--radius)" }} />批量上传</Title>

      <Card style={{ marginBottom: "var(--card-gap)" }}>
        <Space wrap style={{ marginBottom: 12 }}>
          <Select placeholder="学科" allowClear value={subject} onChange={setSubject} options={SUBJECTS} style={{ width: 120 }} />
          <Select placeholder="年级" allowClear value={grade} onChange={setGrade} options={GRADES} style={{ width: 100 }} />
          <Select placeholder="类别" allowClear value={category} onChange={setCategory} options={CATEGORIES} style={{ width: 100 }} />
        </Space>
        <Dragger
          fileList={fileList}
          onChange={({ fileList: newFileList }) => setFileList(newFileList)}
          multiple
          accept=".pdf,.doc,.docx,.jpg,.jpeg,.png,.tiff,.tif,.bmp,.gif"
          beforeUpload={() => false}
        >
          <p className="ant-upload-drag-icon"><UploadOutlined /></p>
          <p>点击或拖拽文件到此处上传</p>
          <p>支持 PDF、文档、图片格式</p>
        </Dragger>
        <Button
          type="primary"
          onClick={handleUpload}
          loading={uploading}
          disabled={fileList.length === 0}
          style={{ marginTop: 12 }}
        >
          {uploading ? "上传中..." : `上传 ${fileList.length} 个文件`}
        </Button>
      </Card>

      {/* Real-time processing progress */}
      {tasks.length > 0 && (
        <Card title="处理进度" style={{ marginBottom: "var(--card-gap)" }}>
          <Table
            dataSource={tasks}
            columns={taskColumns}
            rowKey="task_id"
            pagination={false}
            size="small"
          />
        </Card>
      )}

      {/* Upload results */}
      {results.length > 0 && (
        <Card title="上传结果">
          <Table dataSource={results} columns={resultColumns} rowKey="filename" pagination={false} />
        </Card>
      )}
    </div>
  );
}
