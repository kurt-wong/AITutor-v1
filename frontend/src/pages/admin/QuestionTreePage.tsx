import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  Card, Tree, Table, Typography, Space, Tag, Spin, Input, Select,
} from "antd";
import { SearchOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { apiGet, apiGetParams } from "../../services/api";
import { DIFFICULTY_LABELS, DIFFICULTY_COLORS } from "../../types";
import MathRenderer from "../../components/MathRenderer";

const { Title } = Typography;

interface TreeNode {
  title: string;
  key: string;
  children?: TreeNode[];
}

interface CatalogSubject {
  name: string;
  document_count: number;
  grades: { name: string; document_count: number; categories: { name: string; document_count: number }[] }[];
}

interface QuestionRow {
  id: number;
  content: string;
  difficulty: number | null;
  subject_id: number | null;
  created_at: string;
}

export default function QuestionTreePage() {
  const navigate = useNavigate();
  const [treeData, setTreeData] = useState<TreeNode[]>([]);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [selectedKeys, setSelectedKeys] = useState<string[]>([]);
  const [questions, setQuestions] = useState<QuestionRow[]>([]);
  const [questionsLoading, setQuestionsLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [keyword, setKeyword] = useState("");
  const [difficultyFilter, setDifficultyFilter] = useState<number | undefined>();
  const [page, setPage] = useState(0);

  useEffect(() => {
    fetchCatalog();
  }, []);

  useEffect(() => {
    fetchQuestions();
  }, [page, keyword, difficultyFilter, selectedKeys]);

  const selectedSubject = selectedKeys.find((k) => k.startsWith("subject:"))?.split(":")[1];
  const selectedGrade = selectedKeys.find((k) => k.startsWith("grade:"))?.split(":")[2];
  const selectedCategory = selectedKeys.find((k) => k.startsWith("cat:"))?.split(":")[3];

  const fetchCatalog = async () => {
    setCatalogLoading(true);
    try {
      const subjects = await apiGet<CatalogSubject[]>("/api/admin/catalog");
      const tree: TreeNode[] = subjects.map((subj) => ({
        title: `${subj.name} (${subj.document_count})`,
        key: `subject:${subj.name}`,
        children: subj.grades.map((grade) => ({
          title: `${grade.name} (${grade.document_count})`,
          key: `grade:${subj.name}:${grade.name}`,
          children: grade.categories.map((cat) => ({
            title: `${cat.name} (${cat.document_count})`,
            key: `cat:${subj.name}:${grade.name}:${cat.name}`,
          })),
        })),
      }));
      setTreeData(tree);
    } catch {
      setTreeData([]);
    } finally {
      setCatalogLoading(false);
    }
  };

  const fetchQuestions = async () => {
    setQuestionsLoading(true);
    try {
      const params: Record<string, string | number | undefined> = {
        skip: page * 20,
        limit: 20,
        keyword: keyword || undefined,
        difficulty: difficultyFilter,
        subject: selectedSubject,
        grade: selectedGrade,
        category: selectedCategory,
      };
      const data = await apiGetParams<{ questions: QuestionRow[]; total: number }>("/api/admin/questions", params);
      setQuestions(data.questions || []);
      setTotal(data.total || 0);
    } catch {
      setQuestions([]);
    } finally {
      setQuestionsLoading(false);
    }
  };

  const columns: ColumnsType<QuestionRow> = [
    {
      title: "ID",
      dataIndex: "id",
      width: 60,
      render: (id: number) => (
        <a onClick={() => navigate(`/admin/question-edit?id=${id}`)} style={{ cursor: "pointer" }}>
          {id}
        </a>
      ),
    },
    { title: "题目内容", dataIndex: "content", render: (text: string) => <MathRenderer content={text} /> },
    {
      title: "难度",
      dataIndex: "difficulty",
      width: 80,
      render: (d: number | null) =>
        d ? <Tag color={DIFFICULTY_COLORS[d]}>{DIFFICULTY_LABELS[d]}</Tag> : <Tag>-</Tag>,
    },
  ];

  return (
    <div style={{ maxWidth: "var(--page-max-width)", margin: "0 auto", padding: "var(--page-padding)" }}>
      <Title level={3}>题库目录</Title>
      <Space style={{ marginBottom: "var(--card-gap)" }} wrap>
        <Input
          placeholder="搜索关键词"
          prefix={<SearchOutlined />}
          value={keyword}
          onChange={(e) => { setKeyword(e.target.value); setPage(0); }}
          style={{ width: 200 }}
        />
        <Select
          placeholder="难度筛选"
          allowClear
          style={{ width: 120 }}
          value={difficultyFilter}
          onChange={(v) => { setDifficultyFilter(v); setPage(0); }}
          options={Object.entries(DIFFICULTY_LABELS).map(([k, v]) => ({ value: Number(k), label: v }))}
        />
      </Space>
      <Spin spinning={catalogLoading}>
        <div style={{ display: "flex", gap: 16 }}>
          {treeData.length > 0 && (
            <Card title="目录" size="small" style={{ width: 260, flexShrink: 0 }}>
              <Tree
                treeData={treeData}
                selectedKeys={selectedKeys}
                onSelect={(keys) => setSelectedKeys(keys as string[])}
                defaultExpandAll
              />
            </Card>
          )}
          <div style={{ flex: 1, minWidth: 0 }}>
        <Table
          dataSource={questions}
          columns={columns}
          rowKey="id"
          loading={questionsLoading}
          pagination={{ current: page + 1, pageSize: 20, total, onChange: (p) => setPage(p - 1) }}
        />
          </div>
        </div>
      </Spin>
    </div>
  );
}
