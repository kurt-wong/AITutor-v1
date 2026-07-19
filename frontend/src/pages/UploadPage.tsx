import { useState, useEffect } from "react";
import {
  Upload, Button, message, Card, Typography, Spin, Modal, Select, Space, Tree,
} from "antd";
import {
  UploadOutlined, FilePdfOutlined, FileImageOutlined, FolderOutlined, InboxOutlined,
} from "@ant-design/icons";
import type { UploadFile, UploadProps } from "antd";
import type { DataNode } from "antd/es/tree";
import { apiGet, apiPostForm } from "../services/api";
import { SUBJECTS, GRADES, CATEGORIES } from "../types";
import type { Document_ } from "../types";

const { Title, Text } = Typography;
const { Dragger } = Upload;

interface UploadedDoc {
  id: number;
  filename: string;
  file_type: string;
  file_size: number;
  processing_status: string;
  subject: string | null;
  grade: string | null;
  category: string | null;
  created_at: string;
}

export default function UploadPage() {
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [uploaded, setUploaded] = useState<UploadedDoc[]>([]);
  const [uploading, setUploading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [classifyModalOpen, setClassifyModalOpen] = useState(false);
  const [subject, setSubject] = useState<string | undefined>();
  const [grade, setGrade] = useState<string | undefined>();
  const [category, setCategory] = useState<string | undefined>();

  // Load existing documents on mount
  useEffect(() => {
    fetchDocuments();
  }, []);

  const fetchDocuments = async () => {
    try {
      const data = await apiGet<{ documents?: Document_[] }>("/api/documents/");
      setUploaded(data.documents || []);
    } catch {
      message.error("加载文档列表失败");
    } finally {
      setLoading(false);
    }
  };

  // Handle batch upload with classification
  const handleBatchUpload = async () => {
    if (fileList.length === 0) {
      message.warning("Please select files first");
      return;
    }

    setUploading(true);
    setClassifyModalOpen(false);

    let successCount = 0;
    let failCount = 0;

    for (const file of fileList) {
      const formData = new FormData();
      formData.append("file", file as unknown as Blob);
      if (subject) formData.append("subject", subject);
      if (grade) formData.append("grade", grade);
      if (category) formData.append("category", category);

      try {
        const data = await apiPostForm<{ data?: Document_ }>("/api/documents/upload", formData);
        if (data.data) {
          successCount++;
          setUploaded((prev) => [data.data as unknown as UploadedDoc, ...prev]);
        } else {
          failCount++;
        }
      } catch {
        failCount++;
      }
    }

    setUploading(false);
    setFileList([]);
    setSubject(undefined);
    setGrade(undefined);
    setCategory(undefined);

    if (successCount > 0) {
      message.success(`Successfully uploaded ${successCount} file(s)`);
    }
    if (failCount > 0) {
      message.error(`Failed to upload ${failCount} file(s)`);
    }
  };

  // Show classification modal before upload
  const showClassifyModal = () => {
    if (fileList.length === 0) {
      message.warning("Please select files first");
      return;
    }
    setClassifyModalOpen(true);
  };

  // Build tree data from uploaded documents
  const buildTreeData = (): DataNode[] => {
    const tree: Record<string, Record<string, Record<string, UploadedDoc[]>>> =
      {};

    uploaded.forEach((doc) => {
      const s = doc.subject || "未分类";
      const g = doc.grade || "未分年级";
      const c = doc.category || "未分类别";

      if (!tree[s]) tree[s] = {};
      if (!tree[s][g]) tree[s][g] = {};
      if (!tree[s][g][c]) tree[s][g][c] = [];
      tree[s][g][c].push(doc);
    });

    const result: DataNode[] = [];

    Object.entries(tree).forEach(([subjectKey, grades]) => {
      const subjectChildren: DataNode[] = [];
      let subjectCount = 0;

      Object.entries(grades).forEach(([gradeKey, categories]) => {
        const gradeChildren: DataNode[] = [];
        let gradeCount = 0;

        Object.entries(categories).forEach(([catKey, docs]) => {
          gradeCount += docs.length;
          gradeChildren.push({
            title: `${catKey} (${docs.length})`,
            key: `${subjectKey}-${gradeKey}-${catKey}`,
            icon: <FolderOutlined />,
            children: docs.map((doc) => ({
              title: (
                <Space>
                  {doc.file_type.includes("pdf") ? (
                    <FilePdfOutlined style={{ color: "var(--color-error)" }} />
                  ) : (
                    <FileImageOutlined style={{ color: "var(--color-info)" }} />
                  )}
                  <Text>{doc.filename}</Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    ({(doc.file_size / 1024).toFixed(1)} KB)
                  </Text>
                </Space>
              ),
              key: `doc-${doc.id}`,
              isLeaf: true,
            })),
          });
        });

        subjectCount += gradeCount;
        subjectChildren.push({
          title: `${gradeKey} (${gradeCount})`,
          key: `${subjectKey}-${gradeKey}`,
          icon: <FolderOutlined />,
          children: gradeChildren,
        });
      });

      result.push({
        title: `${subjectKey} (${subjectCount})`,
        key: subjectKey,
        icon: <FolderOutlined />,
        children: subjectChildren,
      });
    });

    return result;
  };

  const uploadProps: UploadProps = {
    fileList,
    onChange: ({ fileList: newFileList }) => setFileList(newFileList),
    multiple: true,
    accept: ".pdf,.doc,.docx,.jpg,.jpeg,.png,.tiff,.tif,.bmp,.gif",
    beforeUpload: () => false, // Prevent auto upload
    onRemove: (file) => {
      setFileList((prev) => prev.filter((f) => f.uid !== file.uid));
    },
  };

  if (loading) {
    return (
      <div style={{ textAlign: "center", padding: "50px" }}>
        <Spin size="large" />
      </div>
    );
  }

  return (
    <div>
      <Title level={4}>Upload Document</Title>
      <Text type="secondary">
        Supported: PDF, DOC, DOCX, JPG, JPEG, PNG, TIFF, BMP, GIF (max 50MB)
      </Text>

      {/* Upload Area */}
      <Card style={{ marginTop: 16, marginBottom: 24 }}>
        <Dragger {...uploadProps} style={{ padding: "20px 0" }}>
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="ant-upload-text">
            Click or drag files to this area to upload
          </p>
          <p className="ant-upload-hint">
            Support batch upload. Multiple files can be selected at once.
          </p>
        </Dragger>

        {fileList.length > 0 && (
          <div style={{ marginTop: 16, textAlign: "right" }}>
            <Space>
              <Text>{fileList.length} file(s) selected</Text>
              <Button
                type="primary"
                icon={<UploadOutlined />}
                onClick={showClassifyModal}
                loading={uploading}
              >
                Upload with Classification
              </Button>
              <Button onClick={() => setFileList([])}>Clear</Button>
            </Space>
          </div>
        )}
      </Card>

      {/* Classification Modal */}
      <Modal
        title="Set Classification"
        open={classifyModalOpen}
        onOk={handleBatchUpload}
        onCancel={() => setClassifyModalOpen(false)}
        okText="Upload"
        confirmLoading={uploading}
      >
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <div>
            <Text strong>Subject (学科)</Text>
            <Select
              placeholder="Select subject"
              style={{ width: "100%", marginTop: 8 }}
              options={SUBJECTS}
              value={subject}
              onChange={setSubject}
              allowClear
            />
          </div>
          <div>
            <Text strong>Grade (年级)</Text>
            <Select
              placeholder="Select grade"
              style={{ width: "100%", marginTop: 8 }}
              options={GRADES}
              value={grade}
              onChange={setGrade}
              allowClear
            />
          </div>
          <div>
            <Text strong>Category (类目)</Text>
            <Select
              placeholder="Select category"
              style={{ width: "100%", marginTop: 8 }}
              options={CATEGORIES}
              value={category}
              onChange={setCategory}
              allowClear
            />
          </div>
          <Text type="secondary">
            Classification is optional. Files without classification will be
            placed under "未分类".
          </Text>
        </Space>
      </Modal>

      {/* Document Tree View */}
      <Card title={`Document Library (${uploaded.length})`}>
        {uploaded.length === 0 ? (
          <div style={{ textAlign: "center", padding: "40px 0" }}>
            <Text type="secondary">No documents uploaded yet</Text>
          </div>
        ) : (
          <Tree
            showIcon
            defaultExpandAll={false}
            treeData={buildTreeData()}
            style={{ fontSize: 14 }}
          />
        )}
      </Card>
    </div>
  );
}
