import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { KnowledgeUploadModal } from "./KnowledgeUploadModal";

describe("KnowledgeUploadModal", () => {
  it("uses xlsx input rules for the product inventory library", () => {
    render(
      <KnowledgeUploadModal
        open
        importLoading={false}
        importError={null}
        selectedLibraryType="product_inventory_excel"
        onLibraryTypeChange={vi.fn()}
        onFileChange={vi.fn()}
        onDrop={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("选择文件")).toHaveAttribute("accept", ".xlsx");
    expect(screen.getByText("重新上传会全量覆盖当前商品库")).toBeInTheDocument();
  });

  it("switches file hints when the library type changes", () => {
    const onLibraryTypeChange = vi.fn();

    render(
      <KnowledgeUploadModal
        open
        importLoading={false}
        importError={null}
        selectedLibraryType="master_rule_bundle"
        onLibraryTypeChange={onLibraryTypeChange}
        onFileChange={vi.fn()}
        onDrop={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("选择文件")).toHaveAttribute("accept", ".md");

    fireEvent.change(screen.getByLabelText("业务库类型"), {
      target: { value: "shipping_info_excel" },
    });

    expect(onLibraryTypeChange).toHaveBeenCalledWith("shipping_info_excel");
  });
});
