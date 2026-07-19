import {
  createContext,
  useContext,
  useState,
  useCallback,
  useMemo,
  useEffect,
  type ReactNode,
} from "react";
import { theme } from "antd";
import type { ThemeConfig } from "antd";

// ── Types ──────────────────────────────────────────────────────────────

type ThemeMode = "light" | "dark";

interface ThemeModeContextValue {
  mode: ThemeMode;
  setMode: (m: ThemeMode) => void;
  toggleTheme: () => void;
  algorithm: ThemeConfig["algorithm"];
}

// ── Context ────────────────────────────────────────────────────────────

const ThemeModeContext = createContext<ThemeModeContextValue>({
  mode: "light",
  setMode: () => {},
  toggleTheme: () => {},
  algorithm: [],
});

// ── Hook ───────────────────────────────────────────────────────────────

export function useThemeMode(): ThemeModeContextValue {
  return useContext(ThemeModeContext);
}

// ── Provider ───────────────────────────────────────────────────────────

export function ThemeModeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<ThemeMode>(() => {
    try {
      const stored = localStorage.getItem("aitutor_theme");
      return stored === "dark" ? "dark" : "light";
    } catch {
      return "light";
    }
  });

  // Sync data-theme attribute on <html> for CSS variable override
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", mode);
  }, [mode]);

  const setModeAndPersist = useCallback((m: ThemeMode) => {
    setMode(m);
    try {
      localStorage.setItem("aitutor_theme", m);
    } catch {
      // localStorage unavailable (private browsing, quota, etc.) — non-critical
    }
  }, []);

  const toggleTheme = useCallback(() => {
    setModeAndPersist(mode === "dark" ? "light" : "dark");
  }, [mode, setModeAndPersist]);

  const algorithm = useMemo<ThemeConfig["algorithm"]>(() => {
    return mode === "dark" ? [theme.darkAlgorithm] : [theme.defaultAlgorithm];
  }, [mode]);

  return (
    <ThemeModeContext.Provider
      value={{ mode, setMode: setModeAndPersist, toggleTheme, algorithm }}
    >
      {children}
    </ThemeModeContext.Provider>
  );
}
