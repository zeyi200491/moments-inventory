import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { KnowledgeLibraryView } from "./KnowledgeLibraryView";

describe("KnowledgeLibraryView", () => {
  it("shows four business library cards after product material is merged away", () => {
    render(
      <KnowledgeLibraryView
        libraries={[]}
        importMessage={null}
        importError={null}
        lastUpload={null}
        onOpenUpload={vi.fn()}
      />,
    );

    expect(screen.getByText("商品库存库")).toBeInTheDocument();
    expect(screen.queryByText("商品素材库")).toBeNull();
    expect(screen.getAllByRole("button", { name: /上传知识库|上传|重新上传/ }).length).toBe(5);
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
