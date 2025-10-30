"""
Image detection and validation for OCR.

Uses OpenCV to detect image regions on pages and validate candidates
by running OCR to filter out decorative text.
"""

import cv2
import numpy as np
import pytesseract


def validate_image_candidates(pil_image, image_candidates, psm_mode):
    """
    Validate image candidates by running OCR on each.

    Filters out decorative text misclassified as images.

    Args:
        pil_image: PIL Image of full page
        image_candidates: List of (x, y, w, h) candidate bboxes
        psm_mode: PSM mode for context

    Returns:
        (confirmed_images, recovered_text_blocks)
        - confirmed_images: List of (x, y, w, h) that are actually images
        - recovered_text_blocks: List of dicts with recovered text
    """
    confirmed_images = []
    recovered_text_blocks = []

    for candidate_bbox in image_candidates:
        x, y, w, h = candidate_bbox

        # Crop candidate region
        cropped = pil_image.crop((x, y, x + w, y + h))

        # Quick OCR test with PSM 7 (single line, fast)
        try:
            validation_text = pytesseract.image_to_string(
                cropped,
                lang='eng',
                config='--psm 7 --oem 1'
            ).strip()
        except Exception:
            # If validation fails, assume it's an image
            confirmed_images.append(candidate_bbox)
            continue

        # Check if meaningful text was found
        if len(validation_text) > 3:
            # This is decorative text! Recover it
            recovered_text_blocks.append({
                'text': validation_text,
                'bbox': list(candidate_bbox),
                'confidence': 0.7  # Lower confidence for recovered text
            })
        else:
            # Actually an image
            confirmed_images.append(candidate_bbox)

    return confirmed_images, recovered_text_blocks


class ImageDetector:
    """Detects image regions on a page using OpenCV."""

    @staticmethod
    def detect_images(pil_image, text_boxes, min_area=10000):
        """
        Detect image regions by finding large areas without text.

        Args:
            pil_image: PIL Image object
            text_boxes: List of (x, y, w, h) text bounding boxes
            min_area: Minimum area in pixels for an image region

        Returns:
            List of (x, y, w, h) image bounding boxes
        """
        # Convert PIL to OpenCV format
        img_array = np.array(pil_image)
        if len(img_array.shape) == 3:
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        else:
            gray = img_array

        # Create mask of text regions
        height, width = gray.shape
        text_mask = np.zeros((height, width), dtype=np.uint8)

        for x, y, w, h in text_boxes:
            # Expand text boxes slightly to avoid detecting gaps between lines
            padding = 10
            x1 = max(0, x - padding)
            y1 = max(0, y - padding)
            x2 = min(width, x + w + padding)
            y2 = min(height, y + h + padding)
            cv2.rectangle(text_mask, (x1, y1), (x2, y2), 255, -1)

        # Find contours in non-text regions
        _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
        non_text = cv2.bitwise_and(cv2.bitwise_not(binary), cv2.bitwise_not(text_mask))

        contours, _ = cv2.findContours(non_text, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        image_boxes = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            area = w * h

            # Filter by size and aspect ratio
            if area > min_area:
                aspect_ratio = w / h if h > 0 else 0
                if 0.2 < aspect_ratio < 5.0:
                    image_boxes.append((x, y, w, h))

        return image_boxes
