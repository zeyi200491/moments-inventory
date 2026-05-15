import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { KnowledgeLibraryView } from "./KnowledgeLibraryView";

describe("KnowledgeLibraryView", () => {
  it("shows five business library cards and the product overwrite warning", () => {
    const onOpenUpload = vi.fn();

    render(
      <KnowledgeLibraryView
        libraries={[
          {
            library_type: "master_rule_bundle",
            source_name: "library:master_rule_bundle",
            original_filename: "rules.md",
            imported_count: 2,
            skipped_count: 0,
            status: "active",
            uploaded_at: "2026-05-15T20:00:00+08:00",
          },
          {
            library_type: "product_inventory_excel",
            source_name: "library:product_inventory_excel",
            original_filename: "inventory.xlsx",
            imported_count: 120,
            skipped_count: 0,
            status: "active",
            uploaded_at: "2026-05-15T20:00:00+08:00",
          },
          {
            library_type: "product_material_excel",
            source_name: "library:product_material_excel",
            original_filename: "materials.xlsx",
            imported_count: 38,
            skipped_count: 0,
            status: "active",
            uploaded_at: "2026-05-15T20:00:00+08:00",
          },
          {
            library_type: "shipping_info_excel",
            source_name: "library:shipping_info_excel",
            original_filename: "shipping.xlsx",
            imported_count: 12,
            skipped_count: 1,
            status: "active",
            uploaded_at: "2026-05-15T20:00:00+08:00",
          },
          {
            library_type: "style_sample_md",
            source_name: "library:style_sample_md",
            original_filename: "style.md",
            imported_count: 3,
            skipped_count: 0,
            status: "active",
            uploaded_at: "2026-05-15T20:00:00+08:00",
          },
        ]}
        importMessage={null}
        importError={null}
        lastUpload={null}
        onOpenUpload={onOpenUpload}
      />,
    );

    expect(screen.getByText("商品库存库")).toBeInTheDocument();
    expect(screen.getByText("重新上传会全量覆盖当前商品库")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /上传|重新上传/ })).toHaveLength(6);
  });

  it("reupload button reopens the modal for the selected business library", () => {
    const onOpenUpload = vi.fn();

    render(
      <KnowledgeLibraryView
        libraries={[
          {
            library_type: "product_inventory_excel",
            source_name: "library:product_inventory_excel",
            original_filename: "inventory.xlsx",
            imported_count: 120,
            skipped_count: 0,
            status: "active",
            uploaded_at: "2026-05-15T20:00:00+08:00",
          },
        ]}
        importMessage={null}
        importError={null}
        lastUpload={null}
        onOpenUpload={onOpenUpload}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "重新上传" }));

    expect(onOpenUpload).toHaveBeenCalledWith("product_inventory_excel");
  });
});
