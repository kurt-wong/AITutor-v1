/**
 * SettingsPage — LLM API 配置管理页面
 *
 * 允许管理员在前端配置 LLM Provider 的 API Key、Base URL、Model 等参数。
 * 配置保存后通过后端热重载即时生效，无需重启服务。
 *
 * Session #58 P0-A: Provider lists and model options are now fetched
 * dynamically from the API instead of hardcoded.
 */

import { useEffect, useState } from "react";
import {
  Card,
  Tabs,
  Form,
  Input,
  Select,
  Button,
  message,
  Spin,
  Space,
  Tag,
  Descriptions,
  Divider,
} from "antd";
import {
  SaveOutlined,
  ExperimentOutlined,
  RobotOutlined,
  PictureOutlined,
  CloudServerOutlined,
} from "@ant-design/icons";
import { apiGet, apiPost, apiPut } from "../../services/api";

// ── Types ────────────────────────────────────────────

interface LLMSettings {
  [key: string]: string;
}

interface SettingsResponse {
  config: LLMSettings;
  runtime_mode: string;
}

interface TestResult {
  success: boolean;
  provider: string;
  model: string;
  response_preview: string;
  latency_tokens: Record<string, number>;
  error?: string;
}

interface ProviderInfo {
  id: string;
  label: string;
  models: string[];
  default_model: string;
}

interface ProvidersResponse {
  text: ProviderInfo[];
  vision: ProviderInfo[];
  routing: Record<string, string>;
}

// ── Constants ────────────────────────────────────────

const GATEWAY_MODE_OPTIONS = [
  { value: "live", label: "Live (真实 API)" },
  { value: "mock", label: "Mock (模拟响应)" },
];

// ── Component ─────────────────────────────────────────

export default function SettingsPage() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [settings, setSettings] = useState<LLMSettings>({});
  const [runtimeMode, setRuntimeMode] = useState("");
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [providers, setProviders] = useState<ProvidersResponse | null>(null);
  const [form] = Form.useForm();

  // Load settings and provider registry on mount
  useEffect(() => {
    loadSettings();
    loadProviders();
  }, []);

  async function loadSettings() {
    setLoading(true);
    try {
      const data = await apiGet<SettingsResponse>("/api/admin/settings/llm");
      setSettings(data.config);
      setRuntimeMode(data.runtime_mode);
      form.setFieldsValue(data.config);
    } catch {
      message.error("加载 LLM 配置失败");
    } finally {
      setLoading(false);
    }
  }

  async function loadProviders() {
    try {
      const data = await apiGet<ProvidersResponse>("/api/admin/settings/llm/providers");
      setProviders(data);
    } catch {
      // Non-fatal: UI falls back to raw text inputs
      console.warn("Failed to load provider registry, model fields will use text inputs");
    }
  }

  async function handleSave(values: Record<string, string>) {
    setSaving(true);
    try {
      const result = await apiPut<{ updated: string[]; runtime_mode: string }>(
        "/api/admin/settings/llm",
        values,
      );
      const count = result.updated?.length ?? Object.keys(values).length;
      message.success(`已保存 ${count} 项配置，Gateway 已热重载`);
      if (result.runtime_mode) setRuntimeMode(result.runtime_mode);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "保存配置失败";
      message.error(msg);
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    setTesting(true);
    setTestResult(null);
    try {
      const raw = await apiPost<{ data?: TestResult } & TestResult>("/api/admin/settings/llm/test");
      const result = (raw as { data?: TestResult }).data ?? (raw as TestResult);
      setTestResult(result);
      if (result.success) {
        message.success(`测试通过 — Provider: ${result.provider}, Model: ${result.model}`);
      } else {
        message.warning(`测试失败: ${result.error || "未知错误"}`);
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "测试请求失败";
      message.error(`测试连接失败: ${msg}`);
      setTestResult({ success: false, provider: "", model: "", response_preview: "", latency_tokens: {}, error: msg });
    } finally {
      setTesting(false);
    }
  }

  function maskApiKey(key: string): string {
    if (!key) return "(未设置)";
    if (key.length <= 8) return "***";
    return key.slice(0, 4) + "****" + key.slice(-4);
  }

  /** Build Select options from provider registry */
  function providerOptions(type: "text" | "vision"): { value: string; label: string }[] {
    if (!providers) return [];
    return providers[type].map((p) => ({ value: p.id, label: p.label }));
  }

  // ── Render ──────────────────────────────────────────

  if (loading) {
    return <Spin size="large" style={{ display: "block", margin: "120px auto" }} />;
  }

  const tabItems = [
    {
      key: "text",
      label: <span><RobotOutlined /> 文本模型</span>,
      children: (
        <Space direction="vertical" size="large" style={{ width: "100%" }}>
          {/* --- Gateway Mode --- */}
          <Card title="Gateway 模式" size="small">
            <Form.Item name="llm.gateway_mode" label="运行模式" style={{ marginBottom: 0 }}>
              <Select options={GATEWAY_MODE_OPTIONS} style={{ width: 200 }} />
            </Form.Item>
          </Card>

          {/* --- DeepSeek --- */}
          <Card title="DeepSeek" size="small" extra={<Tag color="blue">默认推理模型</Tag>}>
            <Form.Item name="llm.deepseek.api_key" label="API Key">
              <Input.Password placeholder="sk-..." />
            </Form.Item>
            <Form.Item name="llm.deepseek.base_url" label="Base URL">
              <Input placeholder="https://api.deepseek.com/v1" />
            </Form.Item>
            <Form.Item name="llm.reasoning_model" label="推理模型" help="输入模型 ID，如 deepseek-v4-pro">
              <Input placeholder="deepseek-v4-pro" />
            </Form.Item>
          </Card>

          {/* --- MIMO --- */}
          <Card title="MIMO" size="small" extra={<Tag color="green">默认快速模型</Tag>}>
            <Form.Item name="llm.mimo.api_key" label="API Key">
              <Input.Password placeholder="sk-..." />
            </Form.Item>
            <Form.Item name="llm.mimo.base_url" label="Base URL">
              <Input placeholder="https://api.xiaomimimo.com/v1" />
            </Form.Item>
            <Form.Item name="llm.fast_model" label="快速回答模型" help="输入模型 ID，如 mimo-v2.5">
              <Input placeholder="mimo-v2.5" />
            </Form.Item>
          </Card>

          {/* --- 路由偏好 --- */}
          <Card title="路由偏好" size="small">
            <Form.Item name="llm.text_provider" label="默认文本 Provider">
              <Select
                options={providerOptions("text")}
                style={{ width: 250 }}
                placeholder={providers ? "选择 Provider" : "mimo / deepseek"}
              />
            </Form.Item>
            <Form.Item name="llm.tutor_model" label="辅导模式模型">
              <Input placeholder="deepseek-v4-flash" />
            </Form.Item>
          </Card>
        </Space>
      ),
    },
    {
      key: "vision",
      label: <span><PictureOutlined /> 视觉模型</span>,
      children: (
        <Space direction="vertical" size="large" style={{ width: "100%" }}>
          <Card title="视觉 Provider" size="small">
            <Form.Item name="llm.vision_provider" label="默认视觉 Provider">
              <Select
                options={providerOptions("vision")}
                style={{ width: 250 }}
                placeholder={providers ? "选择 Provider" : "mimo-vision / deepseek-vl / qwen-vl"}
              />
            </Form.Item>
            <Form.Item name="llm.vision_model" label="视觉模型">
              <Input placeholder="mimo-v2.5" />
            </Form.Item>
          </Card>

          <Card title="Qwen-VL (DashScope)" size="small" extra={<Tag>备选</Tag>}>
            <Form.Item name="llm.qwen_vl.api_key" label="API Key">
              <Input.Password placeholder="sk-..." />
            </Form.Item>
            <Form.Item name="llm.qwen_vl.base_url" label="Base URL">
              <Input placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1" />
            </Form.Item>
          </Card>
        </Space>
      ),
    },
    {
      key: "ollama",
      label: <span><CloudServerOutlined /> Ollama / 本地</span>,
      children: (
        <Space direction="vertical" size="large" style={{ width: "100%" }}>
          <Card title="Ollama 连接" size="small">
            <Form.Item name="llm.ollama.base_url" label="Ollama 地址"
              help="PC 上 Ollama 服务的地址，NAS 部署时填写 PC 的局域网 IP">
              <Input placeholder="http://192.168.1.100:11434" />
            </Form.Item>
            <Form.Item name="llm.ollama.text_model" label="文本 Fallback 模型">
              <Input placeholder="qwen2.5:7b" />
            </Form.Item>
          </Card>

          <Card title="VibeThinker (本地 STEM 推理)" size="small" extra={<Tag color="purple">3.1B Q8_0</Tag>}>
            <Form.Item name="llm.vibethinker.model" label="模型名">
              <Input placeholder="vibethinker-3b:q8_0" />
            </Form.Item>
            <Form.Item name="llm.vibethinker.timeout" label="超时 (秒)">
              <Input type="number" placeholder="300" />
            </Form.Item>
          </Card>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>系统设置</h2>

      {/* Current status */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Descriptions column={4} size="small">
          <Descriptions.Item label="运行时模式">
            <Tag color={runtimeMode === "live" ? "green" : "orange"}>{runtimeMode}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="DeepSeek Key">{maskApiKey(settings["llm.deepseek.api_key"])}</Descriptions.Item>
          <Descriptions.Item label="MIMO Key">{maskApiKey(settings["llm.mimo.api_key"])}</Descriptions.Item>
          <Descriptions.Item label="Ollama URL">{settings["llm.ollama.base_url"] || "(默认)"}</Descriptions.Item>
        </Descriptions>
      </Card>

      {/* Edit form */}
      <Form
        form={form}
        layout="vertical"
        onFinish={handleSave}
        initialValues={settings}
      >
        <Card>
          <Tabs items={tabItems} />

          <Divider />

          <Space>
            <Button
              type="primary"
              htmlType="submit"
              icon={<SaveOutlined />}
              loading={saving}
            >
              保存配置
            </Button>
            <Button
              icon={<ExperimentOutlined />}
              onClick={handleTest}
              loading={testing}
            >
              测试连接
            </Button>
          </Space>
        </Card>
      </Form>

      {/* Test result */}
      {testResult && (
        <Card
          size="small"
          title="测试结果"
          style={{ marginTop: 16 }}
          extra={
            <Tag color={testResult.success ? "green" : "red"}>
              {testResult.success ? "通过" : "失败"}
            </Tag>
          }
        >
          {testResult.success ? (
            <Descriptions column={3} size="small">
              <Descriptions.Item label="Provider">{testResult.provider}</Descriptions.Item>
              <Descriptions.Item label="Model">{testResult.model}</Descriptions.Item>
              <Descriptions.Item label="响应预览">{testResult.response_preview}</Descriptions.Item>
            </Descriptions>
          ) : (
            <p style={{ color: "#dc2626" }}>{testResult.error || "未知错误"}</p>
          )}
        </Card>
      )}
    </div>
  );
}
