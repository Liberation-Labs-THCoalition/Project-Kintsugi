"""Kintsugi Continuum Memory Architecture (CMA) — Phase 1 Stream 1C.

Implements the SimpleMem pipeline (arXiv:2601.02553) with five modules:

- **embeddings**: Vector embedding providers (local + API)
- **cma_stage1**: Semantic structured compression (sliding window, entropy, normalization)
- **cold_archive**: Sub-threshold compressed storage with integrity verification
- **temporal**: Append-only decision/event log
- **significance**: Memory layers, expiration policies, and reaper
- **spaced**: Fibonacci spaced retrieval scheduling
"""

from kintsugi.memory.cma_stage1 import (
    AtomicFact,
    Stage1Result,
    Turn,
    Window,
    filter_windows,
    normalize_window,
    run_stage1,
    score_entropy,
    segment_dialogue,
)
from kintsugi.memory.cold_archive import (
    ArchivedWindow,
    ColdArchive,
    IntegrityReport,
)
from kintsugi.memory.embeddings import (
    APIEmbeddingProvider,
    EmbeddingProvider,
    LocalEmbeddingProvider,
    get_embedding_provider,
)
from kintsugi.memory.significance import (
    ExpiredMemoryReaper,
    MemoryLayer,
    ReapResult,
    compute_expiration,
    compute_layer,
)
from kintsugi.memory.spaced import (
    FIBONACCI,
    DueMemory,
    SpacedRetrieval,
    fib_interval,
)
from kintsugi.memory.temporal import (
    Category,
    TemporalEvent,
    TemporalLog,
)

from kintsugi.memory.cma_stage2 import (
    Fact,
    Insight,
    compute_affinity,
    cluster_facts,
    consolidate,
)
from kintsugi.memory.cma_stage3 import (
    QueryProfile,
    ScoredResult,
    estimate_complexity,
    fuse_rrf,
    fuse_weighted,
    retrieve,
)
from kintsugi.memory.org_isolation import (
    ORG_MEMORIES_SCHEMA,
    OrgMemoryStore,
    MemoryRecord,
    get_org_connection,
)
from kintsugi.memory.bdi_bridge import (
    BDIBridge,
    Belief,
    Desire,
    Intention,
)
from kintsugi.memory.temporal_tree import (
    TemporalTree,
    TreeNode,
    TimeScope,
    ebbinghaus_decay,
    temporal_iou,
)
from kintsugi.memory.temporal_scorer import (
    QueryScoper,
    ScoredResult as TemporalScoredResult,
    ScoringWeights,
    TemporalScorer,
)
from kintsugi.memory.dreamer_consolidator import DreamerConsolidator
from kintsugi.memory.sira_enrichment import (
    DomainMapper,
    LLMEnricher,
    MemoryEnricher,
    QueryExpander,
    SIRAIndex,
)
from kintsugi.memory.tgs_verification import (
    GraphEdge,
    GraphNode,
    GraphResult,
    GraphStore,
    TextGraphVerifier,
    TextStore,
    VerificationReport,
    VerifiedMemory,
)
from kintsugi.memory.tgs_adapter import (
    KintsugiTextStore,
    PostgresGraphStore,
    create_kintsugi_verifier,
)
from kintsugi.memory.kg_extractor import (
    ExtractedEntity,
    ExtractedTriple,
    ExtractionResult,
    extract_entities,
    extract_triples_cooccurrence,
    run_extraction,
)
from kintsugi.memory.kg_store import (
    insert_triple,
    link_entity_to_memory,
    process_memory_for_kg,
    upsert_entity,
)
from kintsugi.memory.kg_retrieval import (
    GraphRetrievalResult,
    PPRConfig,
    apply_catrag_weighting,
    find_seed_nodes,
    graph_retrieve,
    load_adjacency,
    personalized_pagerank,
)

__all__ = [
    # embeddings
    "EmbeddingProvider",
    "LocalEmbeddingProvider",
    "APIEmbeddingProvider",
    "get_embedding_provider",
    # cma_stage1
    "Turn",
    "Window",
    "AtomicFact",
    "Stage1Result",
    "segment_dialogue",
    "score_entropy",
    "filter_windows",
    "normalize_window",
    "run_stage1",
    # cma_stage2
    "Fact",
    "Insight",
    "compute_affinity",
    "cluster_facts",
    "consolidate",
    # cma_stage3
    "QueryProfile",
    "ScoredResult",
    "estimate_complexity",
    "fuse_rrf",
    "fuse_weighted",
    "retrieve",
    # org_isolation
    "ORG_MEMORIES_SCHEMA",
    "OrgMemoryStore",
    "MemoryRecord",
    "get_org_connection",
    # bdi_bridge
    "BDIBridge",
    "Belief",
    "Desire",
    "Intention",
    # cold_archive
    "ColdArchive",
    "ArchivedWindow",
    "IntegrityReport",
    # temporal
    "TemporalLog",
    "TemporalEvent",
    "Category",
    # significance
    "MemoryLayer",
    "compute_layer",
    "compute_expiration",
    "ExpiredMemoryReaper",
    "ReapResult",
    # spaced
    "FIBONACCI",
    "fib_interval",
    "SpacedRetrieval",
    "DueMemory",
    # temporal_tree
    "TemporalTree",
    "TreeNode",
    "TimeScope",
    "ebbinghaus_decay",
    "temporal_iou",
    # temporal_scorer
    "TemporalScorer",
    "ScoringWeights",
    "TemporalScoredResult",
    "QueryScoper",
    # dreamer_consolidator
    "DreamerConsolidator",
    # sira_enrichment
    "SIRAIndex",
    "LLMEnricher",
    "DomainMapper",
    "QueryExpander",
    "MemoryEnricher",
    # tgs_verification
    "TextStore",
    "GraphStore",
    "GraphNode",
    "GraphEdge",
    "GraphResult",
    "VerifiedMemory",
    "VerificationReport",
    "TextGraphVerifier",
    # tgs_adapter
    "KintsugiTextStore",
    "PostgresGraphStore",
    "create_kintsugi_verifier",
    # kg_extractor
    "ExtractedEntity",
    "ExtractedTriple",
    "ExtractionResult",
    "extract_entities",
    "extract_triples_cooccurrence",
    "run_extraction",
    # kg_store
    "upsert_entity",
    "insert_triple",
    "link_entity_to_memory",
    "process_memory_for_kg",
    # kg_retrieval
    "PPRConfig",
    "GraphRetrievalResult",
    "find_seed_nodes",
    "load_adjacency",
    "apply_catrag_weighting",
    "personalized_pagerank",
    "graph_retrieve",
]
