from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import zipfile

from fastapi.testclient import TestClient
import pytest
import yaml

import moments_inventory.cli as cli_module
from moments_inventory.ai_kefu.app import build_default_service, create_app
from moments_inventory.ai_kefu.chat_sync import ChatSyncBridge
from moments_inventory.ai_kefu.models import KnowledgeChunk, LibraryStateRecord, ProductRecord
from moments_inventory.ai_kefu.risk import RiskDecision
from moments_inventory.ai_kefu.service import DraftResult
from moments_inventory.ai_kefu.settings import RetrievalSettings
from moments_inventory.ai_kefu.storage import SQLiteKefuRepository
from moments_inventory.exporter import HEADERS
from moments_inventory.weflow_client import WeFlowSession


def test_knowledge_import_endpoint_accepts_explicit_knowledge_tier(tmp_path):
    repository = SQLiteKefuRepository(tmp_path / "ai-kefu.db")
    repository.initialize()
    client = TestClient(
        create_app(
            service=RecordingDraftService(),
            repository=repository,
            retrieval_settings=RetrievalSettings(chunk_size=20, chunk_overlap=5),
        )
    )

    response = client.post(
        "/api/knowledge/imports",
        json={
            "source_name": "shipping-rules.md",
            "category": "供应链发货",
            "knowledge_tier": "shipping_info",
            "content": "深圳仓现货通常 24 小时内发出。",
            "tags": ["supplier:老王", "深圳仓"],
        },
    )

    assert response.status_code == 200
    assert response.json()["knowledge_tier"] == "shipping_info"
    assert all(chunk.knowledge_tier == "shipping_info" for chunk in repository.list_knowledge_chunks())


def test_knowledge_import_endpoint_accepts_structured_shipping_fields(tmp_path):
    repository = SQLiteKefuRepository(tmp_path / "ai-kefu.db")
    repository.initialize()
    client = TestClient(
        create_app(
            service=RecordingDraftService(),
            repository=repository,
            retrieval_settings=RetrievalSettings(chunk_size=200, chunk_overlap=20),
        )
    )

    response = client.post(
        "/api/knowledge/imports",
        json={
            "source_name": "supplier-laowang-shenzhen",
            "category": "供应链发货",
            "knowledge_tier": "shipping_info",
            "content": "",
            "structured_fields": {
                "supplier_name": "老王",
                "warehouse_location": "深圳华强北",
                "dispatch_sla": "24 小时内发出",
                "delivery_scope": "全国可发",
                "exceptions": "周日只处理加急单",
                "contact_window": "09:00-21:00",
                "notes": "缺货时先确认补货周期",
            },
            "tags": ["现货", "加急"],
        },
    )

    assert response.status_code == 200
    assert response.json()["knowledge_tier"] == "shipping_info"
    chunks = repository.list_knowledge_chunks()
    assert len(chunks) == 1
    assert "供应商：老王" in chunks[0].text
    assert "仓库位置：深圳华强北" in chunks[0].text
    assert "发货时效：24 小时内发出" in chunks[0].text
    assert "老王" in chunks[0].tags
    assert "深圳华强北" in chunks[0].tags


def test_knowledge_import_persists_embeddings_when_provider_available(tmp_path):
    repository = SQLiteKefuRepository(tmp_path / "ai-kefu.db")
    repository.initialize()

    class FakeEmbeddingProvider:
        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            assert len(texts) == 1
            return [[0.11, 0.22]]

    client = TestClient(
        create_app(
            service=RecordingDraftService(),
            repository=repository,
            retrieval_settings=RetrievalSettings(chunk_size=200, chunk_overlap=20),
            embedding_provider=FakeEmbeddingProvider(),
        )
    )

    response = client.post(
        "/api/knowledge/imports",
        json={
            "source_name": "faq-embedding.txt",
            "category": "售后",
            "knowledge_tier": "faq",
            "content": "退款到账通常需要 1 到 3 个工作日。",
            "tags": ["退款", "到账"],
        },
    )

    assert response.status_code == 200
    chunks = repository.list_knowledge_chunks()
    assert len(chunks) == 1
    assert chunks[0].embedding == [0.11, 0.22]


def test_list_knowledge_sources_endpoint_returns_explicit_knowledge_tier(tmp_path):
    repository = SQLiteKefuRepository(tmp_path / "ai-kefu.db")
    repository.initialize()
    repository.save_knowledge_chunks(
        [
            KnowledgeChunk(
                chunk_id="chunk-001",
                source_name="after-sale.md",
                category="正式售后",
                knowledge_tier="after_sale_doc",
                text="售后问题需先提供订单号与问题视频。",
                tags=["售后", "需凭证"],
            )
        ]
    )
    client = TestClient(
        create_app(
            service=RecordingDraftService(),
            repository=repository,
            retrieval_settings=RetrievalSettings(chunk_size=20, chunk_overlap=5),
        )
    )

    response = client.get("/api/knowledge/sources")

    assert response.status_code == 200
    assert response.json() == [
        {
            "source_name": "after-sale.md",
            "category": "正式售后",
            "knowledge_tier": "after_sale_doc",
            "chunk_count": 1,
            "tags": ["售后", "需凭证"],
        }
    ]


def test_list_knowledge_libraries_endpoint_returns_library_states(tmp_path):
    repository = SQLiteKefuRepository(tmp_path / "ai-kefu.db")
    repository.initialize()
    repository.save_library_state(
        LibraryStateRecord(
            library_type="master_rule_bundle",
            source_name="library:master_rule_bundle",
            original_filename="master-rule.md",
            imported_count=2,
            skipped_count=0,
            status="active",
            uploaded_at="2026-05-15T18:00:00+08:00",
        )
    )
    client = TestClient(
        create_app(
            service=RecordingDraftService(),
            repository=repository,
            retrieval_settings=RetrievalSettings(chunk_size=20, chunk_overlap=5),
        )
    )

    response = client.get("/api/knowledge/libraries")

    assert response.status_code == 200
    assert response.json() == [
        {
            "library_type": "master_rule_bundle",
            "source_name": "library:master_rule_bundle",
            "original_filename": "master-rule.md",
            "imported_count": 2,
            "skipped_count": 0,
            "status": "active",
            "uploaded_at": "2026-05-15T18:00:00+08:00",
        }
    ]


def test_knowledge_upload_endpoint_ingests_master_rule_bundle(tmp_path):
    repository = SQLiteKefuRepository(tmp_path / "ai-kefu.db")
    repository.initialize()
    client = TestClient(
        create_app(
            service=RecordingDraftService(),
            repository=repository,
            retrieval_settings=RetrievalSettings(chunk_size=200, chunk_overlap=20),
        )
    )

    response = client.post(
        "/api/knowledge/uploads",
        data={"library_type": "master_rule_bundle"},
        files={
            "file": (
                "master-rule.md",
                (
                    "# 售前总规则\n\n"
                    "客服先确认商品成色，再报价。\n\n"
                    "## 常见问题\n\n"
                    "Q：支持退货吗？\n"
                    "A：按售后规则执行。\n"
                ).encode("utf-8"),
                "text/markdown",
            )
        },
    )

    assert response.status_code == 200
    assert response.json()["library_type"] == "master_rule_bundle"
    assert response.json()["status"] == "active"
    assert response.json()["replaced"] is False
    assert response.json()["imported_count"] == 2
    assert response.json()["skipped_count"] == 0
    assert response.json()["message"] == "上传成功"
    assert response.json()["uploaded_at"]
    assert repository.get_library_state("master_rule_bundle") == LibraryStateRecord(
        library_type="master_rule_bundle",
        source_name="library:master_rule_bundle",
        original_filename="master-rule.md",
        imported_count=2,
        skipped_count=0,
        status="active",
        uploaded_at=response.json()["uploaded_at"],
    )
    assert sorted(chunk.source_name for chunk in repository.list_knowledge_chunks()) == [
        "library:master_rule_bundle:faq",
        "library:master_rule_bundle:master_rule",
    ]


def test_knowledge_upload_endpoint_replaces_existing_library_state_and_chunks(tmp_path):
    repository = SQLiteKefuRepository(tmp_path / "ai-kefu.db")
    repository.initialize()
    client = TestClient(
        create_app(
            service=RecordingDraftService(),
            repository=repository,
            retrieval_settings=RetrievalSettings(chunk_size=200, chunk_overlap=20),
        )
    )

    first_response = client.post(
        "/api/knowledge/uploads",
        data={"library_type": "master_rule_bundle"},
        files={
            "file": (
                "rules-v1.md",
                (
                    "# Rules\n\n"
                    "Old rule.\n\n"
                    "## FAQ\n\n"
                    "Q: old?\n"
                    "A: old.\n"
                ).encode("utf-8"),
                "text/markdown",
            )
        },
    )
    second_response = client.post(
        "/api/knowledge/uploads",
        data={"library_type": "master_rule_bundle"},
        files={
            "file": (
                "rules-v2.md",
                (
                    "# Rules\n\n"
                    "New rule.\n\n"
                    "## FAQ\n\n"
                    "Q: new?\n"
                    "A: new.\n"
                ).encode("utf-8"),
                "text/markdown",
            )
        },
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json()["replaced"] is True
    assert repository.get_library_state("master_rule_bundle") == LibraryStateRecord(
        library_type="master_rule_bundle",
        source_name="library:master_rule_bundle",
        original_filename="rules-v2.md",
        imported_count=2,
        skipped_count=0,
        status="active",
        uploaded_at=second_response.json()["uploaded_at"],
    )
    chunk_texts = [chunk.text for chunk in repository.list_knowledge_chunks()]
    assert any("New rule." in text for text in chunk_texts)
    assert all("Old rule." not in text for text in chunk_texts)


def test_knowledge_upload_endpoint_replaces_products_with_empty_inventory(tmp_path):
    repository = SQLiteKefuRepository(tmp_path / "ai-kefu.db")
    repository.initialize()
    repository.save_products(
        [
            ProductRecord(
                product_id="legacy-1",
                source_record_id="legacy-1",
                brand="Canon",
                model_std="IXUS 95",
                sale_status="在售",
                is_functional=True,
                has_inspection_video=False,
                has_sample_output=False,
                cost_price=500,
                sale_price=650,
                profit_amount=150,
                source_name="legacy",
                source_wxid="wxid-legacy",
                published_at="2026-05-15T10:00:00+08:00",
                image_path="",
                video_path="",
                raw_copy="legacy",
                manual_review_needed=False,
            )
        ]
    )
    client = TestClient(
        create_app(
            service=RecordingDraftService(),
            repository=repository,
            retrieval_settings=RetrievalSettings(chunk_size=200, chunk_overlap=20),
        )
    )

    response = client.post(
        "/api/knowledge/uploads",
        data={"library_type": "product_inventory_excel"},
        files={
            "file": (
                "inventory-empty.xlsx",
                build_products_workbook_bytes([HEADERS]),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 200
    assert response.json()["imported_count"] == 0
    assert response.json()["replaced"] is False
    assert repository.list_products() == []


def test_knowledge_upload_endpoint_rejects_broken_product_inventory_excel(tmp_path):
    repository = SQLiteKefuRepository(tmp_path / "ai-kefu.db")
    repository.initialize()
    client = TestClient(
        create_app(
            service=RecordingDraftService(),
            repository=repository,
            retrieval_settings=RetrievalSettings(chunk_size=200, chunk_overlap=20),
        )
    )

    response = client.post(
        "/api/knowledge/uploads",
        data={"library_type": "product_inventory_excel"},
        files={
            "file": (
                "broken.xlsx",
                b"not-a-real-xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 400
    assert "xlsx" in response.json()["detail"]


def test_knowledge_upload_endpoint_rejects_malformed_product_inventory_excel(tmp_path):
    repository = SQLiteKefuRepository(tmp_path / "ai-kefu.db")
    repository.initialize()
    client = TestClient(
        create_app(
            service=RecordingDraftService(),
            repository=repository,
            retrieval_settings=RetrievalSettings(chunk_size=200, chunk_overlap=20),
        )
    )

    response = client.post(
        "/api/knowledge/uploads",
        data={"library_type": "product_inventory_excel"},
        files={
            "file": (
                "broken-shared-strings.xlsx",
                build_malformed_xlsx_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 400
    assert "xlsx" in response.json()["detail"]


def test_knowledge_upload_endpoint_rejects_malformed_product_material_excel(tmp_path):
    repository = SQLiteKefuRepository(tmp_path / "ai-kefu.db")
    repository.initialize()
    client = TestClient(
        create_app(
            service=RecordingDraftService(),
            repository=repository,
            retrieval_settings=RetrievalSettings(chunk_size=200, chunk_overlap=20),
        )
    )

    response = client.post(
        "/api/knowledge/uploads",
        data={"library_type": "product_material_excel"},
        files={
            "file": (
                "broken-shared-strings.xlsx",
                build_malformed_xlsx_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 400
    assert "xlsx" in response.json()["detail"]


def test_knowledge_upload_endpoint_persists_embeddings_when_provider_available(tmp_path):
    repository = SQLiteKefuRepository(tmp_path / "ai-kefu.db")
    repository.initialize()

    class FakeEmbeddingProvider:
        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            return [[0.11, 0.22] for _ in texts]

    client = TestClient(
        create_app(
            service=RecordingDraftService(),
            repository=repository,
            retrieval_settings=RetrievalSettings(chunk_size=200, chunk_overlap=20),
            embedding_provider=FakeEmbeddingProvider(),
        )
    )

    response = client.post(
        "/api/knowledge/uploads",
        data={"library_type": "master_rule_bundle"},
        files={
            "file": (
                "master-rule.md",
                (
                    "# Rules\n\n"
                    "Upload rule.\n\n"
                    "## FAQ\n\n"
                    "Q: upload?\n"
                    "A: yes.\n"
                ).encode("utf-8"),
                "text/markdown",
            )
        },
    )

    assert response.status_code == 200
    chunks = repository.list_knowledge_chunks()
    assert len(chunks) == 2
    assert all(chunk.embedding == [0.11, 0.22] for chunk in chunks)


def test_knowledge_upload_endpoint_rejects_unimplemented_library_type(tmp_path):
    repository = SQLiteKefuRepository(tmp_path / "ai-kefu.db")
    repository.initialize()
    client = TestClient(
        create_app(
            service=RecordingDraftService(),
            repository=repository,
            retrieval_settings=RetrievalSettings(chunk_size=200, chunk_overlap=20),
        )
    )

    response = client.post(
        "/api/knowledge/uploads",
        data={"library_type": "shipping_info_excel"},
        files={
            "file": (
                "shipping-info.xlsx",
                b"placeholder",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 501
    assert "shipping_info_excel" in response.json()["detail"]


def test_knowledge_import_endpoint_remains_available_after_upload_api_added(tmp_path):
    repository = SQLiteKefuRepository(tmp_path / "ai-kefu.db")
    repository.initialize()
    client = TestClient(
        create_app(
            service=RecordingDraftService(),
            repository=repository,
            retrieval_settings=RetrievalSettings(chunk_size=20, chunk_overlap=5),
        )
    )

    response = client.post(
        "/api/knowledge/imports",
        json={
            "source_name": "faq.txt",
            "category": "售后",
            "knowledge_tier": "faq",
            "content": "退款到账通常需要一到三个工作日。",
            "tags": ["退款"],
        },
    )

    assert response.status_code == 200
    assert response.json()["source_name"] == "faq.txt"


class RecordingDraftService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def generate_draft(
        self,
        *,
        conversation_id: str,
        customer_message: str,
        risk_decision: RiskDecision,
    ) -> DraftResult:
        self.calls.append(
            {
                "conversation_id": conversation_id,
                "customer_message": customer_message,
                "risk_decision": risk_decision,
            }
        )
        from moments_inventory.ai_kefu.workflow import WorkflowAnalysis

        return DraftResult(
            reply_text="有现货的，我先把参数发你看一下。",
            risk_level=risk_decision.risk_level,
            reason=risk_decision.reason,
            used_knowledge=[
                KnowledgeChunk(
                    chunk_id="chunk-001",
                    source_name="product.txt",
                    category="产品",
                    text="A1 目前有现货，可次日发货。",
                    tags=["A1", "现货"],
                )
            ],
            analysis=WorkflowAnalysis(
                customer_stage="推单",
                intent="商品推荐",
                should_handoff=False,
                reply_type="商品推荐",
                required_data=["库存", "预算"],
            ),
        )


def build_products_workbook_bytes(rows: list[list[object]]) -> bytes:
    workbook_path = Path.cwd() / "_tmp_test_inventory.xlsx"
    try:
        from moments_inventory.exporter import _write_workbook

        _write_workbook(workbook_path, rows)
        return workbook_path.read_bytes()
    finally:
        if workbook_path.exists():
            workbook_path.unlink()


def build_malformed_xlsx_bytes() -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
</Types>""",
        )
        archive.writestr(
            "xl/workbook.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Sheet1" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>""",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>""",
        )
        archive.writestr(
            "xl/sharedStrings.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="1" uniqueCount="1">
  <si><t>only-one-string</t></si>
</sst>""",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1">
      <c r="A1" t="s"><v>99</v></c>
    </row>
  </sheetData>
</worksheet>""",
        )
    return buffer.getvalue()


def test_health_endpoint_returns_ok():
    client = TestClient(create_app(service=RecordingDraftService()))

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_protected_endpoints_require_api_key():
    client = TestClient(create_app(service=RecordingDraftService(), api_key="secret-key"))

    health_response = client.get("/api/health")
    draft_response = client.post(
        "/api/drafts",
        json={
            "conversation_id": "conv-1",
            "customer_message": "A1 现在有现货吗",
        },
    )

    assert health_response.status_code == 200
    assert draft_response.status_code == 401


def test_protected_endpoints_accept_matching_api_key():
    client = TestClient(create_app(service=RecordingDraftService(), api_key="secret-key"))

    response = client.post(
        "/api/drafts",
        headers={"X-API-Key": "secret-key"},
        json={
            "conversation_id": "conv-1",
            "customer_message": "A1 现在有现货吗",
        },
    )

    assert response.status_code == 200


def test_generate_draft_endpoint_returns_structured_result():
    service = RecordingDraftService()
    client = TestClient(create_app(service=service))

    response = client.post(
        "/api/drafts",
        json={
            "conversation_id": "conv-1",
            "customer_message": "A1 现在有现货吗",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reply_text"] == "有现货的，我先把参数发你看一下。"
    assert body["risk_level"] == "L2"
    assert "现货" in body["reason"]
    assert body["used_knowledge"][0]["chunk_id"] == "chunk-001"
    assert body["used_knowledge"][0]["knowledge_tier"] == "product_material"
    assert body["customer_stage"] == "推单"
    assert body["intent"] == "商品推荐"
    assert body["should_handoff"] is False
    assert body["reply_type"] == "商品推荐"
    assert body["required_data"] == ["库存", "预算"]

    assert service.calls[0]["conversation_id"] == "conv-1"
    assert service.calls[0]["customer_message"] == "A1 现在有现货吗"
    assert service.calls[0]["risk_decision"].risk_level == "L2"


def test_generate_draft_endpoint_can_return_locked_reply_type():
    from moments_inventory.ai_kefu.workflow import WorkflowAnalysis

    class LockedDraftService:
        def generate_draft(
            self,
            *,
            conversation_id: str,
            customer_message: str,
            risk_decision: RiskDecision,
        ) -> DraftResult:
            return DraftResult(
                reply_text="小宝多买有优惠的 你需要几台呀~",
                risk_level=risk_decision.risk_level,
                reason=risk_decision.reason,
                used_knowledge=[],
                analysis=WorkflowAnalysis(
                    customer_stage="推单",
                    intent="砍价",
                    should_handoff=False,
                    reply_type="固定话术",
                    required_data=["优惠规则"],
                ),
            )

    client = TestClient(create_app(service=LockedDraftService()))

    response = client.post(
        "/api/drafts",
        json={
            "conversation_id": "conv-locked",
            "customer_message": "多买有优惠吗",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reply_text"] == "小宝多买有优惠的 你需要几台呀~"
    assert body["reply_type"] == "固定话术"


def test_knowledge_import_endpoint_replaces_existing_source_chunks(tmp_path):
    repository = SQLiteKefuRepository(tmp_path / "ai-kefu.db")
    repository.initialize()
    repository.save_knowledge_chunks(
        [
            KnowledgeChunk(
                chunk_id="old-1",
                source_name="faq.txt",
                category="售后",
                text="旧内容",
                tags=["旧"],
            )
        ]
    )
    client = TestClient(
        create_app(
            service=RecordingDraftService(),
            repository=repository,
            retrieval_settings=RetrievalSettings(chunk_size=12, chunk_overlap=4),
        )
    )

    response = client.post(
        "/api/knowledge/imports",
        json={
            "source_name": "faq.txt",
            "category": "售后",
            "content": "退款到账通常需要三个工作日，请耐心等待。",
            "tags": ["退款", "到账"],
        },
    )

    assert response.status_code == 200
    chunks = repository.list_knowledge_chunks()
    assert all(chunk.source_name == "faq.txt" for chunk in chunks)
    assert all(chunk.text != "旧内容" for chunk in chunks)
    assert all(chunk.tags == ["退款", "到账"] for chunk in chunks)


def test_list_knowledge_sources_endpoint_returns_aggregated_sources(tmp_path):
    repository = SQLiteKefuRepository(tmp_path / "ai-kefu.db")
    repository.initialize()
    repository.save_knowledge_chunks(
        [
            KnowledgeChunk(
                chunk_id="chunk-001",
                source_name="faq.txt",
                category="售后",
                text="退款到账通常需要三个工作日。",
                tags=["退款"],
            ),
            KnowledgeChunk(
                chunk_id="chunk-002",
                source_name="faq.txt",
                category="售后",
                text="售后问题请先提供订单号。",
                tags=["售后"],
            ),
            KnowledgeChunk(
                chunk_id="chunk-003",
                source_name="style.md",
                category="回复风格",
                text="说话自然一点，别太像机器人。",
                tags=["活人感"],
            ),
        ]
    )
    client = TestClient(
        create_app(
            service=RecordingDraftService(),
            repository=repository,
            retrieval_settings=RetrievalSettings(chunk_size=20, chunk_overlap=5),
        )
    )

    response = client.get("/api/knowledge/sources")

    assert response.status_code == 200
    assert response.json() == [
        {
            "source_name": "faq.txt",
            "category": "售后",
            "knowledge_tier": "faq",
            "chunk_count": 2,
            "tags": ["退款", "售后"],
        },
        {
            "source_name": "style.md",
            "category": "回复风格",
            "knowledge_tier": "style_sample",
            "chunk_count": 1,
            "tags": ["活人感"],
        },
    ]


def test_create_app_rejects_partial_runtime_dependency_injection():
    with pytest.raises(ValueError, match="必须同时提供"):
        create_app(
            service=RecordingDraftService(),
            retrieval_settings=RetrievalSettings(chunk_size=20, chunk_overlap=5),
        )


def test_build_default_service_uses_openai_compatible_provider_from_config(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    config_path = tmp_path / "ai_kefu.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "workspace_dir": "./workspace",
                "database_path": "./data/ai-kefu.db",
                "embedding_provider": "openai",
                "chat_provider": "openai_compatible",
                "chat_model": "gpt-4.1-mini",
                "chat_provider_options": {
                    "api_base": "https://example.com/v1",
                    "api_key_env": "AI_KEFU_OPENAI_API_KEY",
                    "timeout_seconds": 15,
                },
                "retrieval": {
                    "chunk_size": 300,
                    "chunk_overlap": 30,
                },
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AI_KEFU_OPENAI_API_KEY", "real-secret")

    captured: dict[str, object] = {}

    class FakeProvider:
        def __init__(self, *, api_base: str, api_key: str, model: str, timeout_seconds: int):
            captured["api_base"] = api_base
            captured["api_key"] = api_key
            captured["model"] = model
            captured["timeout_seconds"] = timeout_seconds

    monkeypatch.setattr("moments_inventory.ai_kefu.app.OpenAICompatibleChatProvider", FakeProvider)

    service = build_default_service(config_path)

    assert type(service).__name__ == "KefuDraftService"
    assert captured == {
        "api_base": "https://example.com/v1",
        "api_key": "real-secret",
        "model": "gpt-4.1-mini",
        "timeout_seconds": 15,
    }


def test_build_parser_supports_kefu_dev_command():
    parser = cli_module.build_parser()

    args = parser.parse_args(
        ["kefu-dev", "--host", "0.0.0.0", "--port", "9000", "--ai-kefu-config", "config/ai_kefu.yaml"]
    )

    assert args.command == "kefu-dev"
    assert args.host == "0.0.0.0"
    assert args.port == 9000
    assert args.ai_kefu_config == "config/ai_kefu.yaml"


def test_cli_kefu_dev_runs_uvicorn_without_loading_legacy_settings(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}
    app_instance = object()

    def fake_load_settings(_path: str):
        raise AssertionError("kefu-dev 不应该加载旧配置")

    def fake_create_app_with_config(config_path: str):
        captured["app_created"] = True
        captured["config_path"] = config_path
        return app_instance

    def fake_run(app: object, *, host: str, port: int) -> None:
        captured["app"] = app
        captured["host"] = host
        captured["port"] = port

    monkeypatch.setattr(cli_module, "load_settings", fake_load_settings)
    monkeypatch.setattr(cli_module, "create_app", fake_create_app_with_config)
    monkeypatch.setattr(cli_module, "uvicorn", SimpleNamespace(run=fake_run))

    result = cli_module.main(
        ["kefu-dev", "--host", "0.0.0.0", "--port", "9000", "--ai-kefu-config", "config/ai_kefu.yaml"]
    )

    assert result == 0
    assert captured == {
        "app_created": True,
        "config_path": "config/ai_kefu.yaml",
        "app": app_instance,
        "host": "0.0.0.0",
        "port": 9000,
    }


def _build_chat_sync_bridge() -> ChatSyncBridge:
    bridge = ChatSyncBridge(merge_window_seconds=8)
    bridge.sync_sessions(
        [
            WeFlowSession(
                session_id="s-1",
                username="wxid_alice",
                display_name="Alice",
                session_type="private",
                last_timestamp=120,
                unread_count=2,
            ),
            WeFlowSession(
                session_id="s-2",
                username="wxid_bob",
                display_name="Bob",
                session_type="private",
                last_timestamp=90,
                unread_count=0,
            ),
        ]
    )
    return bridge


def test_chat_sync_list_endpoint_returns_empty_array_when_bridge_is_disabled():
    client = TestClient(create_app(service=RecordingDraftService()))

    response = client.get("/api/chat-sync/sessions")

    assert response.status_code == 200
    assert response.json() == []


def test_chat_sync_control_endpoints_return_service_unavailable_when_bridge_is_disabled():
    client = TestClient(create_app(service=RecordingDraftService()))

    detail_response = client.get("/api/chat-sync/sessions/s-1")
    switch_response = client.post(
        "/api/chat-sync/current-session",
        json={"sessionId": "s-1", "autoGenerate": True},
    )
    refresh_response = client.post("/api/chat-sync/sessions/s-1/refresh")

    assert detail_response.status_code == 503
    assert switch_response.status_code == 503
    assert refresh_response.status_code == 503


def test_chat_sync_sessions_endpoint_returns_camel_case_session_list():
    bridge = _build_chat_sync_bridge()
    bridge.set_current_session("s-2", auto_generate=False)
    client = TestClient(create_app(service=RecordingDraftService(), chat_sync_bridge=bridge))

    response = client.get("/api/chat-sync/sessions")

    assert response.status_code == 200
    assert response.json()[0]["sessionId"] == "s-2"
    assert response.json()[0]["isCurrent"] is True
    assert response.json()[1]["sessionId"] == "s-1"


def test_chat_sync_current_session_endpoint_switches_current_session():
    bridge = _build_chat_sync_bridge()
    client = TestClient(create_app(service=RecordingDraftService(), chat_sync_bridge=bridge))

    response = client.post(
        "/api/chat-sync/current-session",
        json={"sessionId": "s-1", "autoGenerate": True},
    )

    assert response.status_code == 200
    assert response.json()["sessionId"] == "s-1"
    assert response.json()["autoGenerate"] is True


def test_chat_sync_current_session_endpoint_returns_404_for_unknown_session():
    bridge = _build_chat_sync_bridge()
    client = TestClient(create_app(service=RecordingDraftService(), chat_sync_bridge=bridge))

    response = client.post(
        "/api/chat-sync/current-session",
        json={"sessionId": "missing", "autoGenerate": False},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "chat sync session not found"


def test_draft_history_endpoint_returns_audit_records(tmp_path):
    from moments_inventory.ai_kefu.audit import DraftAuditRecord

    repository = SQLiteKefuRepository(tmp_path / "ai-kefu.db")
    repository.initialize()
    repository.save_draft_audit_record(
        DraftAuditRecord(
            draft_id="draft-001",
            conversation_id="conv-001",
            customer_message="娴嬭瘯娑堟伅",
            reply_text="娴嬭瘯鍥炲",
            risk_level="L2",
            reason="鍙戣揣鍜ㄨ",
            workflow_json='{"intent":"鍙戣揣鍜ㄨ"}',
            used_chunk_ids_json='["faq-001"]',
            final_status="generated",
            operator_note="",
            created_at="2026-05-07T12:00:00+08:00",
        )
    )
    client = TestClient(
        create_app(
            service=RecordingDraftService(),
            repository=repository,
            retrieval_settings=RetrievalSettings(chunk_size=20, chunk_overlap=5),
        )
    )

    response = client.get("/api/drafts/history")

    assert response.status_code == 200
    assert response.json() == [
        {
            "draft_id": "draft-001",
            "conversation_id": "conv-001",
            "customer_message": "娴嬭瘯娑堟伅",
            "reply_text": "娴嬭瘯鍥炲",
            "risk_level": "L2",
            "reason": "鍙戣揣鍜ㄨ",
            "workflow": {"intent": "鍙戣揣鍜ㄨ"},
            "used_chunk_ids": ["faq-001"],
            "final_status": "generated",
            "operator_note": "",
            "created_at": "2026-05-07T12:00:00+08:00",
        }
    ]


def test_submit_draft_feedback_updates_audit_record(tmp_path):
    from moments_inventory.ai_kefu.audit import DraftAuditRecord

    repository = SQLiteKefuRepository(tmp_path / "ai-kefu.db")
    repository.initialize()
    repository.save_draft_audit_record(
        DraftAuditRecord(
            draft_id="draft-001",
            conversation_id="conv-001",
            customer_message="娴嬭瘯娑堟伅",
            reply_text="娴嬭瘯鍥炲",
            risk_level="L2",
            reason="鍙戣揣鍜ㄨ",
            workflow_json="{}",
            used_chunk_ids_json="[]",
            final_status="generated",
            operator_note="",
            created_at="2026-05-07T12:00:00+08:00",
        )
    )
    client = TestClient(
        create_app(
            service=RecordingDraftService(),
            repository=repository,
            retrieval_settings=RetrievalSettings(chunk_size=20, chunk_overlap=5),
        )
    )

    response = client.post(
        "/api/drafts/feedback",
        json={
            "draft_id": "draft-001",
            "final_status": "edited",
            "operator_note": "宸ヤ汉鎵嬪姩琛ュ厖鍙戣揣鏃舵晥",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    records = repository.list_draft_audit_records(limit=10)
    assert len(records) == 1
    assert records[0].final_status == "edited"
    assert records[0].operator_note == "宸ヤ汉鎵嬪姩琛ュ厖鍙戣揣鏃舵晥"


def test_create_app_default_runtime_returns_non_empty_fallback_reply():
    client = TestClient(create_app())

    response = client.post(
        "/api/drafts",
        json={
            "conversation_id": "conv-default",
            "customer_message": "你好，在吗",
        },
    )

    assert response.status_code == 200
    assert response.json()["reply_text"] == "我先帮您记下需求，稍后给您更准确的回复。"
