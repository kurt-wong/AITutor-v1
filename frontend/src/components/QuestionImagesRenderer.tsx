/**
 * QuestionImagesRenderer — Shared placement-aware image renderer.
 *
 * S#173: Extracted from QuestionEditPage to avoid duplication across
 * admin and student-end pages. Renders images by placement category:
 *   - stem: inline after question content (width=280)
 *   - explanation: inline after explanation (width=240)
 *   - page_context: collapsed details section (width=120, opacity=0.7)
 *   - associated: treated like page_context
 *   - placement=null/None: rendered once in a fallback section
 *
 * S#174 fix: placement=null images are always rendered exactly once in
 * the fallback section, never duplicated across placement groups.
 */

import { Image, Space } from "antd";

export interface QuestionImage {
  image_id: number;
  image_key: string;
  image_type: string;
  description: string | null;
  created_at?: string;
  page_no?: number | null;
  bbox?: number[] | null;
  placement?: string | null;
  source?: string | null;
  figure_id?: string | null;
  label?: string | null;
}

interface Props {
  images: QuestionImage[];
  /** Which placements to render. Defaults to all. */
  placements?: string[];
  /** Image width override per placement. */
  widthMap?: Record<string, number>;
}

const DEFAULT_WIDTHS: Record<string, number> = {
  stem: 280,
  explanation: 240,
  page_context: 120,
  associated: 120,
  fallback: 160,
};

export default function QuestionImagesRenderer({
  images,
  placements,
  widthMap,
}: Props) {
  if (!images || images.length === 0) return null;

  const w = { ...DEFAULT_WIDTHS, ...widthMap };
  const targetPlacements = placements || ["stem", "explanation", "page_context", "associated"];

  // S#174: placement=null images go to fallback, never into placement groups
  const byPlacement = (p: string) =>
    images.filter((img) => img.placement === p);
  const nullPlacement = images.filter((img) => !img.placement);

  const stemImgs = targetPlacements.includes("stem") ? byPlacement("stem") : [];
  const explImgs = targetPlacements.includes("explanation") ? byPlacement("explanation") : [];
  const ctxImgs = [
    ...(targetPlacements.includes("page_context") ? byPlacement("page_context") : []),
    ...(targetPlacements.includes("associated") ? byPlacement("associated") : []),
  ];

  return (
    <>
      {/* Stem images — inline, centered */}
      {stemImgs.map((img) => (
        <div key={img.image_id} style={{ textAlign: "center", margin: "12px 0" }}>
          <Image
            src={`/api/documents/images/${img.image_key}`}
            alt={img.description || "题干配图"}
            width={w.stem}
            style={{ borderRadius: 8, border: "1px solid #f0f0f0" }}
          />
          {(img.source || img.description) && (
            <div style={{ fontSize: 11, color: "#999" }}>
              {img.source || "image"} · {img.description || ""}
            </div>
          )}
        </div>
      ))}

      {/* Explanation images — inline, centered */}
      {explImgs.map((img) => (
        <div key={img.image_id} style={{ textAlign: "center", margin: "8px 0" }}>
          <Image
            src={`/api/documents/images/${img.image_key}`}
            alt={img.description || "详解配图"}
            width={w.explanation}
            style={{ borderRadius: 8, border: "1px solid #f0f0f0" }}
          />
          {(img.source || img.description) && (
            <div style={{ fontSize: 11, color: "#999" }}>
              {img.source || "image"} · {img.description || ""}
            </div>
          )}
        </div>
      ))}

      {/* Page context / associated images — collapsed */}
      {ctxImgs.length > 0 && (
        <details style={{ marginTop: 8 }}>
          <summary style={{ cursor: "pointer", color: "#999", fontSize: 12 }}>
            同页参考图 ({ctxImgs.length} 张)
          </summary>
          <Space wrap style={{ marginTop: 8 }}>
            {ctxImgs.map((img) => (
              <div key={img.image_id} style={{ textAlign: "center" }}>
                <Image
                  src={`/api/documents/images/${img.image_key}`}
                  alt={img.description || "同页参考"}
                  width={w.page_context}
                  style={{ borderRadius: 4, border: "1px solid #f0f0f0", opacity: 0.7 }}
                />
                {img.page_no && (
                  <div style={{ fontSize: 10, color: "#bbb" }}>page {img.page_no}</div>
                )}
              </div>
            ))}
          </Space>
        </details>
      )}

      {/* S#174: Fallback — placement=null images rendered exactly once */}
      {nullPlacement.length > 0 && (
        <details style={{ marginTop: 8 }}>
          <summary style={{ cursor: "pointer", color: "#999", fontSize: 12 }}>
            配图 ({nullPlacement.length} 张)
          </summary>
          <Space wrap style={{ marginTop: 8 }}>
            {nullPlacement.map((img) => (
              <div key={img.image_id} style={{ textAlign: "center" }}>
                <Image
                  src={`/api/documents/images/${img.image_key}`}
                  alt={img.description || "配图"}
                  width={w.fallback}
                  style={{ borderRadius: 4, border: "1px solid #f0f0f0" }}
                />
                {img.page_no && (
                  <div style={{ fontSize: 10, color: "#bbb" }}>page {img.page_no}</div>
                )}
              </div>
            ))}
          </Space>
        </details>
      )}
    </>
  );
}
