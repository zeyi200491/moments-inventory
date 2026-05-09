from moments_inventory.ai_kefu.models import KnowledgeChunk
from moments_inventory.ai_kefu.workflow import WorkflowAnalysis


def test_retrieval_prioritizes_shipping_info_when_workflow_requires_shipping():
    from moments_inventory.ai_kefu.retrieval import TieredKnowledgeRetriever

    retriever = TieredKnowledgeRetriever(top_k=2, fallback_k=1)
    result = retriever.retrieve(
        customer_message="今天拍的话多久发货",
        workflow_analysis=WorkflowAnalysis(
            customer_stage="推单",
            intent="发货咨询",
            should_handoff=False,
            reply_type="需查询后回答",
            required_data=["库存", "发货信息"],
        ),
        knowledge_chunks=[
            KnowledgeChunk(
                chunk_id="faq-001",
                source_name="faq.txt",
                category="发货",
                text="现货订单通常会在 24 小时内发货。",
                tags=["发货", "物流"],
            ),
            KnowledgeChunk(
                chunk_id="shipping-001",
                source_name="shipping-rules.md",
                category="供应链发货",
                text="老王深圳仓现货通常 24 小时内发出。",
                knowledge_tier="shipping_info",
                tags=["supplier:老王", "深圳仓", "24小时内"],
            ),
        ],
        selected_products=[],
    )

    assert [chunk.chunk_id for chunk in result.shipping_info_chunks] == ["shipping-001"]
    assert [chunk.chunk_id for chunk in result.faq_chunks] == ["faq-001"]


def test_retrieval_prioritizes_after_sale_doc_when_workflow_requires_after_sale():
    from moments_inventory.ai_kefu.retrieval import TieredKnowledgeRetriever

    retriever = TieredKnowledgeRetriever(top_k=2, fallback_k=1)
    result = retriever.retrieve(
        customer_message="售后怎么处理 需要准备什么",
        workflow_analysis=WorkflowAnalysis(
            customer_stage="售后说明",
            intent="售后咨询",
            should_handoff=False,
            reply_type="固定话术",
            required_data=["售后规则"],
        ),
        knowledge_chunks=[
            KnowledgeChunk(
                chunk_id="faq-002",
                source_name="faq.txt",
                category="售后",
                text="售后问题请先提供订单号。",
                tags=["售后"],
            ),
            KnowledgeChunk(
                chunk_id="after-sale-001",
                source_name="after-sale.md",
                category="正式售后",
                text="正式售后需先提供订单号与问题视频。",
                knowledge_tier="after_sale_doc",
                tags=["售后", "需凭证"],
            ),
        ],
        selected_products=[],
    )

    assert [chunk.chunk_id for chunk in result.after_sale_doc_chunks] == ["after-sale-001"]
    assert [chunk.chunk_id for chunk in result.faq_chunks] == ["faq-002"]


def test_retrieval_reranks_shipping_info_by_specificity():
    from moments_inventory.ai_kefu.retrieval import TieredKnowledgeRetriever

    retriever = TieredKnowledgeRetriever(top_k=2, fallback_k=1)
    result = retriever.retrieve(
        customer_message="老王深圳仓今天拍多久发货",
        workflow_analysis=WorkflowAnalysis(
            customer_stage="推单",
            intent="发货咨询",
            should_handoff=False,
            reply_type="需查询后回答",
            required_data=["发货信息"],
        ),
        knowledge_chunks=[
            KnowledgeChunk(
                chunk_id="shipping-generic",
                source_name="shipping-rules.md",
                category="供应链发货",
                text="现货订单通常会在 24 小时内发货。",
                knowledge_tier="shipping_info",
                tags=["老王", "深圳仓", "发货", "多久"],
            ),
            KnowledgeChunk(
                chunk_id="shipping-specific",
                source_name="supplier-laowang.md",
                category="供应链发货",
                text="老王深圳仓现货通常 24 小时内发出，周末顺延半天。",
                knowledge_tier="shipping_info",
                tags=["supplier:老王", "24小时内"],
            ),
        ],
        selected_products=[],
    )

    assert [chunk.chunk_id for chunk in result.shipping_info_chunks] == [
        "shipping-specific",
        "shipping-generic",
    ]


def test_retrieval_reranks_after_sale_doc_by_query_terms():
    from moments_inventory.ai_kefu.retrieval import TieredKnowledgeRetriever

    retriever = TieredKnowledgeRetriever(top_k=2, fallback_k=1)
    result = retriever.retrieve(
        customer_message="退款多久到账",
        workflow_analysis=WorkflowAnalysis(
            customer_stage="售后说明",
            intent="售后咨询",
            should_handoff=False,
            reply_type="简短回答",
            required_data=["售后规则"],
        ),
        knowledge_chunks=[
            KnowledgeChunk(
                chunk_id="after-sale-generic",
                source_name="after-sale.md",
                category="正式售后",
                text="正式售后需要先提供订单号和问题视频。",
                knowledge_tier="after_sale_doc",
                tags=["售后", "凭证"],
            ),
            KnowledgeChunk(
                chunk_id="after-sale-refund",
                source_name="refund-policy.md",
                category="正式售后",
                text="退款到账通常需要 1 到 3 个工作日，原路返回。",
                knowledge_tier="after_sale_doc",
                tags=["退款", "到账"],
            ),
        ],
        selected_products=[],
    )

    assert [chunk.chunk_id for chunk in result.after_sale_doc_chunks] == [
        "after-sale-refund",
        "after-sale-generic",
    ]


def test_retrieval_can_use_query_embedding_to_promote_semantic_match():
    from moments_inventory.ai_kefu.retrieval import TieredKnowledgeRetriever

    retriever = TieredKnowledgeRetriever(top_k=2, fallback_k=1)
    result = retriever.retrieve(
        customer_message="续航怎么样",
        workflow_analysis=WorkflowAnalysis(
            customer_stage="验机",
            intent="电池咨询",
            should_handoff=False,
            reply_type="简短回答",
            required_data=["商品素材"],
        ),
        knowledge_chunks=[
            KnowledgeChunk(
                chunk_id="material-generic",
                source_name="materials.md",
                category="商品素材",
                text="这台机器成色不错，机身细节干净。",
                knowledge_tier="product_material",
                tags=["成色", "外观"],
                embedding=[0.2, 0.1, 0.0],
            ),
            KnowledgeChunk(
                chunk_id="material-battery",
                source_name="materials.md",
                category="商品素材",
                text="电池正常使用一天一充，续航稳定。",
                knowledge_tier="product_material",
                tags=["电池", "续航"],
                embedding=[0.95, 0.0, 0.0],
            ),
        ],
        selected_products=[],
        query_embedding=[1.0, 0.0, 0.0],
    )

    assert [chunk.chunk_id for chunk in result.product_material_chunks] == [
        "material-battery",
        "material-generic",
    ]
