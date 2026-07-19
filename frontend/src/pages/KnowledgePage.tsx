import { useState, useEffect } from "react";
import { Card, Tree, Typography, Spin, message } from "antd";
import type { DataNode } from "antd/es/tree";
import { apiGet } from "../services/api";
import type { KnowledgeNode } from "../types";

const { Title } = Typography;

export default function KnowledgePage() {
  const [loading, setLoading] = useState(true);
  const [treeData, setTreeData] = useState<DataNode[]>([]);

  useEffect(() => {
    fetchKnowledge();
  }, []);

  const fetchKnowledge = async () => {
    try {
      const data = await apiGet<{ nodes?: KnowledgeNode[] } & Record<string, unknown>>("/api/knowledge/");
      const knowledgeNodes = data.nodes || [];
      setTreeData(buildTree(knowledgeNodes));
    } catch {
      message.error("加载知识树失败");
    } finally {
      setLoading(false);
    }
  };

  const buildTree = (nodes: KnowledgeNode[]): DataNode[] => {
    const nodeMap = new Map<number, DataNode>();
    const roots: DataNode[] = [];

    // First pass: create all nodes
    nodes.forEach((node) => {
      const treeNode: DataNode = {
        key: node.id,
        title: `${node.name} (${node.code})`,
        children: [],
      };
      nodeMap.set(node.id, treeNode);
    });

    // Second pass: attach children to parents
    nodes.forEach((node) => {
      const treeNode = nodeMap.get(node.id)!;
      if (node.parent_id === null) {
        roots.push(treeNode);
      } else {
        const parent = nodeMap.get(node.parent_id);
        if (parent) {
          parent.children = parent.children || [];
          parent.children.push(treeNode);
        }
      }
    });

    // Clean up empty children arrays
    const pruneEmpty = (list: DataNode[]) => {
      for (const item of list) {
        if (item.children && item.children.length === 0) {
          delete item.children;
        } else if (item.children) {
          pruneEmpty(item.children);
        }
      }
    };
    pruneEmpty(roots);

    return roots;
  };

  return (
    <div>
      <Title level={4}>知识体系</Title>
      <Spin spinning={loading}>
        <Card>
          <Tree treeData={treeData} defaultExpandAll />
        </Card>
      </Spin>
    </div>
  );
}
