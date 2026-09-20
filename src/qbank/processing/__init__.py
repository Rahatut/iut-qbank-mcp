"""Processing pipeline components and stage interfaces.

Exposes:
  - Interfaces: Extractor, ExtractionChecker, OCRProcessor, MetadataExtractor,
    Classifier, Chunker, EmbeddingProvider
  - Implementations: PyMuPDFExtractor, TextQualityChecker, TesseractOCRProcessor,
    RuleBasedMetadataExtractor, RuleBasedClassifier, QuestionPaperChunker,
    SentenceTransformerProvider
"""
from qbank.processing.chunker import QuestionData, QuestionPaperChunker
from qbank.processing.classifier import RuleBasedClassifier
from qbank.processing.embedding import SentenceTransformerProvider
from qbank.processing.extractor import PyMuPDFExtractor, TextQualityChecker
from qbank.processing.interfaces import (
    ChunkData,
    Chunker,
    Classifier,
    EmbeddingProvider,
    ExtractedDocument,
    ExtractionChecker,
    Extractor,
    MetadataExtractor,
    NormalizedMetadata,
    OCRProcessor,
    PageText,
)
from qbank.processing.metadata import RuleBasedMetadataExtractor
from qbank.processing.ocr import TesseractOCRProcessor

__all__ = [
    # Data structures
    "ChunkData",
    "ExtractedDocument",
    "NormalizedMetadata",
    "PageText",
    "QuestionData",
    # Interfaces
    "Chunker",
    "Classifier",
    "EmbeddingProvider",
    "ExtractionChecker",
    "Extractor",
    "MetadataExtractor",
    "OCRProcessor",
    # Implementations
    "PyMuPDFExtractor",
    "QuestionPaperChunker",
    "RuleBasedClassifier",
    "RuleBasedMetadataExtractor",
    "SentenceTransformerProvider",
    "TesseractOCRProcessor",
    "TextQualityChecker",
]
