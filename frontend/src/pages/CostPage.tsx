import { useState, useEffect } from "react";
import { Card, Table, Typography, Spin, message, Statistic, Row, Col } from "antd";
import { DollarOutlined } from "@ant-design/icons";
import { apiGet } from "../services/api";
import type { CostRecord } from "../types";

const { Title } = Typography;

export default function CostPage() {
  const [loading, setLoading] = useState(true);
  const [records, setRecords] = useState<CostRecord[]>([]);
  const [totalCost, setTotalCost] = useState(0);
  const [totalTokens, setTotalTokens] = useState(0);

  useEffect(() => {
    fetchCostData();
  }, []);

  const fetchCostData = async () => {
    try {
      const data = await apiGet<{ records?: CostRecord[] } & Record<string, unknown>>("/api/cost/");
      const costRecords = data.records || [];
      setRecords(costRecords);
      const cost = costRecords.reduce((sum, r) => sum + (r.cost_usd || 0), 0);
      const tokens = costRecords.reduce((sum, r) => sum + (r.total_tokens || 0), 0);
      setTotalCost(cost);
      setTotalTokens(tokens);
    } catch {
      message.error("加载费用数据失败");
    } finally {
      setLoading(false);
    }
  };

  const columns = [
    { title: "ID", dataIndex: "id", key: "id", width: 60 },
    { title: "供应商", dataIndex: "provider", key: "provider" },
    { title: "模型", dataIndex: "model", key: "model" },
    { title: "输入 Token", dataIndex: "prompt_tokens", key: "prompt_tokens" },
    { title: "输出 Token", dataIndex: "completion_tokens", key: "completion_tokens" },
    { title: "总 Token", dataIndex: "total_tokens", key: "total_tokens" },
    {
      title: "费用(USD)",
      dataIndex: "cost_usd",
      key: "cost_usd",
      render: (v: number) => `$${v.toFixed(6)}`,
    },
  ];

  return (
    <div>
      <Title level={4}>费用统计</Title>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={12}>
          <Card>
            <Statistic
              title="总费用"
              value={totalCost}
              precision={6}
              prefix={<DollarOutlined />}
              suffix="USD"
            />
          </Card>
        </Col>
        <Col span={12}>
          <Card>
            <Statistic title="总 Token" value={totalTokens} />
          </Card>
        </Col>
      </Row>
      <Spin spinning={loading}>
        <Table dataSource={records} columns={columns} rowKey="id" />
      </Spin>
    </div>
  );
}
