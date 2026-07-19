import { useState, useEffect } from "react";
import { Table, Typography, Spin, message, Tag } from "antd";
import { apiGet } from "../services/api";
import type { Exam } from "../types";

const { Title } = Typography;

export default function ExamPage() {
  const [loading, setLoading] = useState(true);
  const [exams, setExams] = useState<Exam[]>([]);

  useEffect(() => {
    fetchExams();
  }, []);

  const fetchExams = async () => {
    try {
      const data = await apiGet<Exam[]>("/api/exams/");
      setExams(data);
    } catch (err) {
      message.error("加载试卷列表失败");
    } finally {
      setLoading(false);
    }
  };

  const columns = [
    { title: "ID", dataIndex: "id", key: "id", width: 80 },
    { title: "名称", dataIndex: "title", key: "title" },
    {
      title: "学科",
      dataIndex: "subject",
      key: "subject",
      render: (s: string | null) => <Tag>{s || "-"}</Tag>,
    },
    { title: "题目数", dataIndex: "question_count", key: "question_count", width: 100 },
    { title: "时长(分钟)", dataIndex: "duration_minutes", key: "duration_minutes", width: 120 },
  ];

  return (
    <div>
      <Title level={4}>试卷管理</Title>
      <Spin spinning={loading}>
        <Table dataSource={exams} columns={columns} rowKey="id" />
      </Spin>
    </div>
  );
}
