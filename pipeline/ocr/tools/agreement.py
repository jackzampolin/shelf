import difflib
from typing import List, Dict, Any

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.pipeline.rich_progress import RichProgressBar

from ..providers import OCRProvider
from ..storage import OCRStageStorage


def calculate_agreements(
    storage: BookStorage,
    logger: PipelineLogger,
    ocr_storage: OCRStageStorage,
    providers: List[OCRProvider],
    page_numbers: List[int],
    stage_name: str,
):

    if not page_numbers:
        return

    stage_storage = storage.stage(stage_name)

    logger.info(f"Calculating provider agreement for {len(page_numbers)} pages...")
    progress = RichProgressBar(
        total=len(page_numbers), prefix="   ", width=40, unit="pages"
    )
    progress.update(0, suffix="calculating...")

    calculated = 0
    for idx, page_num in enumerate(page_numbers):
        try:
            provider_outputs = _load_provider_outputs(
                storage, ocr_storage, providers, page_num
            )

            if len(provider_outputs) < len(providers):
                logger.warning(
                    f"Page {page_num} missing some provider outputs, skipping"
                )
                continue

            agreement = _calculate_text_agreement(provider_outputs)

            stage_storage.metrics_manager.record(
                key=f"page_{page_num:04d}",
                custom_metrics={"provider_agreement": agreement},
                accumulate=True  # Preserve existing metrics
            )

            calculated += 1
            progress.update(idx + 1, suffix=f"{calculated}/{len(page_numbers)}")

        except Exception as e:
            logger.page_error("Failed to calculate agreement", page=page_num, error=str(e))

    progress.finish(f"   ✓ Calculated agreement for {calculated} pages")


def _load_provider_outputs(
    storage: BookStorage,
    ocr_storage: OCRStageStorage,
    providers: List[OCRProvider],
    page_num: int,
) -> Dict[str, Dict[str, Any]]:
    provider_outputs = {}

    for provider in providers:
        provider_data = ocr_storage.load_provider_page(
            storage, provider.config.name, page_num
        )

        if provider_data:
            provider_outputs[provider.config.name] = {
                "text": _extract_text(provider_data),
                "confidence": _calculate_confidence(provider_data),
                "data": provider_data,
            }

    return provider_outputs


def _extract_text(ocr_output: Dict[str, Any]) -> str:
    blocks = ocr_output.get("blocks", [])
    paragraphs = []

    for block in blocks:
        for para in block.get("paragraphs", []):
            text = para.get("text", "").strip()
            if text:
                paragraphs.append(text)

    return "\n\n".join(paragraphs)


def _calculate_confidence(ocr_output: Dict[str, Any]) -> float:
    blocks = ocr_output.get("blocks", [])
    confidences = []

    for block in blocks:
        for para in block.get("paragraphs", []):
            conf = para.get("avg_confidence", 0.0)
            if conf > 0:
                confidences.append(conf)

    return sum(confidences) / len(confidences) if confidences else 0.0


def _calculate_text_agreement(provider_outputs: Dict[str, Dict]) -> float:
    texts = [output["text"] for output in provider_outputs.values()]

    if len(texts) < 2:
        return 1.0

    # Pairwise similarities
    similarities = []
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            sim = difflib.SequenceMatcher(None, texts[i], texts[j]).ratio()
            similarities.append(sim)

    return sum(similarities) / len(similarities) if similarities else 0.0
