/**
 * Types and constants unit tests
 * Validates shared constants: DIFFICULTY_LABELS, DIFFICULTY_COLORS, etc.
 */
import { describe, it, expect } from "vitest";
import {
  DIFFICULTY_LABELS,
  DIFFICULTY_COLORS,
  ERROR_COLORS,
  SUBJECTS,
  GRADES,
  SUBJECT_COLORS,
} from "../types";

describe("DIFFICULTY_LABELS", () => {
  it("has labels for all difficulty levels 1-5", () => {
    expect(DIFFICULTY_LABELS[1]).toBe("简单");
    expect(DIFFICULTY_LABELS[2]).toBe("基础");
    expect(DIFFICULTY_LABELS[3]).toBe("中等");
    expect(DIFFICULTY_LABELS[4]).toBe("困难");
    expect(DIFFICULTY_LABELS[5]).toBe("综合");
    expect(Object.keys(DIFFICULTY_LABELS)).toHaveLength(5);
  });
});

describe("DIFFICULTY_COLORS", () => {
  it("maps each difficulty to a valid Ant Design color", () => {
    const validColors = ["green", "blue", "orange", "red", "purple", "cyan", "magenta", "gold"];
    for (const color of Object.values(DIFFICULTY_COLORS)) {
      expect(validColors).toContain(color);
    }
  });

  it("covers all 5 difficulty levels", () => {
    expect(Object.keys(DIFFICULTY_COLORS)).toHaveLength(5);
  });
});

describe("ERROR_COLORS", () => {
  it("has mappings for known error types", () => {
    expect(ERROR_COLORS.conceptual).toBe("red");
    expect(ERROR_COLORS.calculation).toBe("orange");
    expect(ERROR_COLORS.careless).toBe("gold");
    expect(ERROR_COLORS.unknown).toBe("default");
  });
});

describe("SUBJECTS", () => {
  it("contains all 9 Chinese K-12 subjects", () => {
    expect(SUBJECTS).toHaveLength(9);
    const names = SUBJECTS.map((s) => s.value);
    expect(names).toContain("数学");
    expect(names).toContain("语文");
    expect(names).toContain("英语");
  });

  it("each subject has matching value and label", () => {
    for (const subject of SUBJECTS) {
      expect(subject.value).toBe(subject.label);
    }
  });
});

describe("GRADES", () => {
  it("covers middle school and high school", () => {
    expect(GRADES).toHaveLength(6);
    expect(GRADES.map((g) => g.value)).toEqual([
      "初一", "初二", "初三", "高一", "高二", "高三",
    ]);
  });
});

describe("SUBJECT_COLORS", () => {
  it("assigns a color to every subject", () => {
    for (const subject of SUBJECTS) {
      expect(SUBJECT_COLORS[subject.value]).toBeDefined();
    }
  });
});
