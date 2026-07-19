import React from "react";
import ReactDOM from "react-dom/client";
import { ConfigProvider } from "antd";
import App from "./App";
import { ThemeModeProvider, useThemeMode } from "./hooks/useThemeMode";
import "./styles/theme.css";

// ── Apple 风格主题配置 (Design.md) ──
// Seed Token（品牌定制）+ Algorithm（内置算法切换）+ Component Token（组件微调）
// 设计规范: D:\Project\AI Tutors\Design.md

const themeConfig = {
  // ═══ Seed Token — Apple 品牌色 / 圆角 / 字体 ═══
  token: {
    // ── Brand: 唯一品牌色 Action Blue #0066cc ──
    colorPrimary: "#0066cc",

    // ── Radius: Apple 圆角体系 ──
    borderRadius: 8,                   // 默认 = {rounded.sm}
    borderRadiusLG: 18,                // 大组件 = {rounded.lg}

    // ── Typography: SF Pro / Inter 栈 ──
    fontFamily:
      "'Inter', 'SF Pro Display', 'SF Pro Text', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
    fontSize: 14,                      // UI 控件保持 14px；正文在 Typography 组件级别设为 17px
    lineHeight: 1.47,                  // Apple body line-height

    // ── Semantic colors (Apple 体系) ──
    colorSuccess: "#34c759",           // Apple green
    colorWarning: "#ff9500",           // Apple orange
    colorError: "#ff3b30",             // Apple red
    colorInfo: "#0071e3",              // Focus Blue

    // ── Surface / Layout colors ──
    colorBgLayout: "#f5f5f7",          // Parchment (全局背景)
    colorBgContainer: "#ffffff",       // Pure White (卡片/内容区)
    colorBorder: "#e0e0e0",            // Hairline
    colorBorderSecondary: "#f0f0f0",   // Divider Soft

    // ── Text colors ──
    colorText: "#1d1d1f",              // Near-Black Ink
    colorTextSecondary: "#7a7a7a",     // Ink Muted 48
    colorTextTertiary: "#cccccc",      // Body Muted

    // ── Controls ──
    controlHeight: 36,
  },

  // ═══ Algorithm — 动态切换（由 useThemeMode hook 注入） ═══
  algorithm: [],

  // ═══ Component Token — 组件级微调 ═══
  components: {
    Layout: {
      headerBg: "#000000",            // global-nav: 纯黑顶栏
      headerHeight: 44,               // Apple global-nav height
      siderBg: "#f5f5f7",             // Parchment 侧栏 (浅色模式)
    },
    Menu: {
      itemBg: "#f5f5f7",              // Parchment 背景
      itemSelectedBg: "rgba(0, 102, 204, 0.1)",  // Action Blue 10% 选中
      itemSelectedColor: "#0066cc",   // Action Blue 文字
      itemHoverBg: "rgba(0, 0, 0, 0.04)",
      itemBorderRadius: 8,
      subMenuItemBg: "#f5f5f7",
    },
    Button: {
      borderRadius: 9999,             // {rounded.pill} — pill CTA
      controlHeight: 36,
      primaryShadow: "none",          // Apple 无阴影按钮
    },
    Card: {
      borderRadiusLG: 18,             // {rounded.lg}
      paddingLG: 24,                  // {spacing.lg}
      boxShadow: "none",              // 无阴影（Apple 仅产品图有阴影）
    },
    Table: {
      headerBg: "#f5f5f7",
      rowHoverBg: "rgba(0, 102, 204, 0.04)",
      borderRadiusLG: 12,
      boxShadow: "none",
    },
    Tag: {
      borderRadiusSM: 9999,           // pill tags
    },
    Typography: {
      titleFontWeight: 600,           // Apple headline weight 600 (not 700)
      fontSize: 17,                   // Apple body: 17px
    },
    Alert: {
      borderRadiusLG: 10,
    },
    Select: {
      borderRadius: 8,
      controlHeight: 36,
    },
    Input: {
      borderRadius: 8,
      controlHeight: 36,
    },
    Statistic: {
      titleFontSize: 14,
    },
    Segmented: {
      borderRadius: 8,
    },
  },
};

// ── Root: connects ThemeModeProvider → ConfigProvider ──────────────────

function Root() {
  const { algorithm } = useThemeMode();
  const mergedTheme = { ...themeConfig, algorithm };
  return (
    <ConfigProvider theme={mergedTheme}>
      <App />
    </ConfigProvider>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeModeProvider>
      <Root />
    </ThemeModeProvider>
  </React.StrictMode>
);
