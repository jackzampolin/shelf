from typing import Dict, Any, List
import base64
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from mistralai import Mistral

from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.llm.rate_limiter import RateLimiter
from infra.pipeline.rich_progress import RichProgressBar
from ..schemas import MistralOcrPageOutput, ImageBBox, PageDimensions


# Mistral OCR pricing and rate limits (as of 2025-11)
# TODO: Update if pricing changes - check https://mistral.ai/pricing
MISTRAL_OCR_COST_PER_PAGE = 0.002  # $0.002 per page
MISTRAL_OCR_RATE_LIMIT = 360  # 6 requests/second = 360 requests/minute


def encode_image(image_path: Path) -> str:
    """Encode image file to base64."""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')


def _log_failure(stage_storage, page_num: int, error: str, attempt: int, max_retries: int):
    """Log failure to JSON file for tracking."""
    logs_dir = stage_storage.output_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    failure_log = logs_dir / "llm_failures.json"

    failure_entry = {
        "page_num": page_num,
        "error": error,
        "attempt": attempt,
        "max_retries": max_retries,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }

    # Append to existing failures or create new file
    failures = []
    if failure_log.exists():
        with open(failure_log, 'r') as f:
            failures = json.load(f)

    failures.append(failure_entry)

    with open(failure_log, 'w') as f:
        json.dump(failures, f, indent=2)


def process_single_page(
    page_num: int,
    source_storage,
    stage_storage,
    logger: PipelineLogger,
    client: Mistral,
    rate_limiter: RateLimiter,
    model: str = "mistral-ocr-latest",
    include_images: bool = False,
    max_retries: int = 3
) -> Dict[str, Any]:
    """Process a single page with Mistral OCR with retry logic."""

    page_file = source_storage.output_dir / f"page_{page_num:04d}.png"

    if not page_file.exists():
        error_msg = f"Source image not found: {page_file}"
        logger.error(f"  Page {page_num}: {error_msg}")
        _log_failure(stage_storage, page_num, error_msg, attempt=0, max_retries=max_retries)
        return {"success": False, "page_num": page_num, "error": error_msg}

    # Retry loop
    last_error = None
    for attempt in range(max_retries):
        start_time = time.time()

        try:
            # Encode image
            base64_image = encode_image(page_file)

            # Wait for rate limit token before making API call
            rate_limiter.consume()

            # Call Mistral OCR API
            ocr_response = client.ocr.process(
                model=model,
                document={
                    "type": "image_url",
                    "image_url": f"data:image/png;base64,{base64_image}"
                },
                include_image_base64=include_images
            )

            # Extract data from response
            # The response has: pages, model, document_annotation, usage_info
            if not ocr_response.pages or len(ocr_response.pages) == 0:
                error_msg = "No pages in OCR response"
                last_error = error_msg
                if attempt < max_retries - 1:
                    logger.warning(f"  Page {page_num} attempt {attempt + 1}/{max_retries}: {error_msg}, retrying...")
                    time.sleep(2 ** attempt)  # Exponential backoff: 1s, 2s, 4s
                    continue
                else:
                    logger.error(f"  Page {page_num}: {error_msg} after {max_retries} attempts")
                    _log_failure(stage_storage, page_num, error_msg, attempt=attempt + 1, max_retries=max_retries)
                    return {"success": False, "page_num": page_num, "error": error_msg}

            # Get first page (single image = single page)
            page_data = ocr_response.pages[0]

            # Extract images with bboxes
            images = []
            if hasattr(page_data, 'images') and page_data.images:
                for img in page_data.images:
                    images.append(ImageBBox(
                        top_left_x=img.top_left_x,
                        top_left_y=img.top_left_y,
                        bottom_right_x=img.bottom_right_x,
                        bottom_right_y=img.bottom_right_y,
                        image_base64=img.image_base64 if include_images else None
                    ))

            # Extract dimensions
            dimensions = PageDimensions(
                width=page_data.dimensions.width,
                height=page_data.dimensions.height,
                dpi=page_data.dimensions.dpi if hasattr(page_data.dimensions, 'dpi') else None
            )

            # Build output schema
            output = MistralOcrPageOutput(
                page_num=page_num,
                markdown=page_data.markdown,
                char_count=len(page_data.markdown),
                dimensions=dimensions,
                images=images,
                model_used=ocr_response.model,
                processing_cost=MISTRAL_OCR_COST_PER_PAGE
            )

            # Save to disk
            stage_storage.save_page(page_num, output.model_dump(), schema=MistralOcrPageOutput)

            # Calculate processing time
            processing_time = time.time() - start_time

            # Record metrics
            stage_storage.metrics_manager.record(
                key=f"page_{page_num:04d}",
                cost_usd=MISTRAL_OCR_COST_PER_PAGE,
                time_seconds=processing_time,
                custom_metrics={
                    "page": page_num,
                    "char_count": len(page_data.markdown),
                    "images_detected": len(images),
                    "model": ocr_response.model,
                }
            )

            # Success - return immediately
            return {
                "success": True,
                "page_num": page_num,
                "char_count": len(page_data.markdown),
                "images_detected": len(images),
                "processing_time": processing_time
            }

        except Exception as e:
            last_error = str(e)
            if attempt < max_retries - 1:
                logger.warning(f"  Page {page_num} attempt {attempt + 1}/{max_retries}: {last_error}, retrying...")
                time.sleep(2 ** attempt)  # Exponential backoff: 1s, 2s, 4s
            else:
                logger.error(f"  Page {page_num}: OCR failed after {max_retries} attempts: {last_error}")
                _log_failure(stage_storage, page_num, last_error, attempt=attempt + 1, max_retries=max_retries)

    # All retries exhausted
    return {"success": False, "page_num": page_num, "error": last_error}


def process_batch(
    storage: BookStorage,
    logger: PipelineLogger,
    remaining_pages: List[int],
    max_workers: int,
    model: str = "mistral-ocr-latest",
    include_images: bool = False,
    max_retries: int = 3
) -> Dict[str, Any]:
    """Process batch of pages with Mistral OCR."""

    # Get API key
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        raise ValueError("MISTRAL_API_KEY environment variable not set")

    client = Mistral(api_key=api_key)

    source_storage = storage.stage("source")
    stage_storage = storage.stage("mistral-ocr")

    # Create rate limiter (6 requests/second = 360 requests/minute)
    rate_limiter = RateLimiter(requests_per_minute=MISTRAL_OCR_RATE_LIMIT)

    logger.info(f"=== Mistral OCR: Processing {len(remaining_pages)} pages ===")
    logger.info(f"Model: {model}")
    logger.info(f"Workers: {max_workers or 'default'}")
    logger.info(f"Rate limit: {MISTRAL_OCR_RATE_LIMIT} requests/min (6/sec)")
    logger.info(f"Estimated cost: ${len(remaining_pages) * MISTRAL_OCR_COST_PER_PAGE:.4f}")

    pages_processed = 0
    total_cost = 0.0
    total_chars = 0
    total_images = 0
    total_time = 0.0
    failed_pages = []

    batch_start_time = time.time()

    # Create progress bar
    progress = RichProgressBar(
        total=len(remaining_pages),
        prefix="Mistral OCR: ",
        unit="pages"
    )

    # Process pages in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                process_single_page,
                page_num,
                source_storage,
                stage_storage,
                logger,
                client,
                rate_limiter,
                model,
                include_images,
                max_retries
            ): page_num
            for page_num in remaining_pages
        }

        total_pages = len(futures)
        completed_count = 0

        for future in as_completed(futures):
            result = future.result()
            completed_count += 1

            if result["success"]:
                pages_processed += 1
                total_cost += MISTRAL_OCR_COST_PER_PAGE
                total_chars += result.get("char_count", 0)
                total_images += result.get("images_detected", 0)
                total_time += result.get("processing_time", 0)

                # Update progress bar
                progress.update(
                    completed_count,
                    suffix=f"${total_cost:.2f} | {total_chars:,} chars | {total_images} images"
                )
            else:
                failed_pages.append(result["page_num"])
                # Still update progress for failed pages
                progress.update(
                    completed_count,
                    suffix=f"${total_cost:.2f} | {len(failed_pages)} failed"
                )

    total_elapsed = time.time() - batch_start_time
    avg_time_per_page = total_time / pages_processed if pages_processed > 0 else 0

    # Get rate limiter stats
    rate_stats = rate_limiter.get_status()

    # Build summary message
    summary_lines = [
        f"✅ Mistral OCR complete",
        f"   Pages: {pages_processed}/{total_pages} ({len(failed_pages)} failed)" if failed_pages else f"   Pages: {pages_processed}/{total_pages}",
        f"   Cost: ${total_cost:.4f}",
        f"   Text: {total_chars:,} chars, {total_images} images detected",
        f"   Time: {total_elapsed:.1f}s ({avg_time_per_page:.2f}s/page avg)",
        f"   Rate limit wait: {rate_stats['total_waited_sec']:.1f}s"
    ]

    # Finish progress bar with summary
    progress.finish("\n".join(summary_lines))

    # Also log to file
    logger.info(
        "Mistral OCR complete",
        pages_processed=pages_processed,
        failed=len(failed_pages),
        cost=f"${total_cost:.4f}",
        total_chars=total_chars,
        total_images=total_images,
        avg_time_per_page=f"{avg_time_per_page:.2f}s",
        total_time=f"{total_elapsed:.1f}s",
        rate_limited_wait=f"{rate_stats['total_waited_sec']:.1f}s"
    )

    return {
        "status": "success" if len(failed_pages) == 0 else "partial",
        "pages_processed": pages_processed,
        "failed_pages": failed_pages,
        "cost_usd": total_cost,
        "total_chars": total_chars,
        "total_images": total_images
    }
