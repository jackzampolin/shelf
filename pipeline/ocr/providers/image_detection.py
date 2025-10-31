import cv2
import numpy as np
import pytesseract


def validate_image_candidates(pil_image, image_candidates, psm_mode):
    confirmed_images = []
    recovered_text_blocks = []

    for candidate_bbox in image_candidates:
        x, y, w, h = candidate_bbox

        cropped = pil_image.crop((x, y, x + w, y + h))

        try:
            validation_text = pytesseract.image_to_string(
                cropped,
                lang='eng',
                config='--psm 7 --oem 1'
            ).strip()
        except Exception:
            confirmed_images.append(candidate_bbox)
            continue

        if len(validation_text) > 3:
            recovered_text_blocks.append({
                'text': validation_text,
                'bbox': list(candidate_bbox),
                'confidence': 0.7
            })
        else:
            confirmed_images.append(candidate_bbox)

    return confirmed_images, recovered_text_blocks


class ImageDetector:
    @staticmethod
    def detect_images(pil_image, text_boxes, min_area=10000):
        img_array = np.array(pil_image)
        if len(img_array.shape) == 3:
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        else:
            gray = img_array

        height, width = gray.shape
        text_mask = np.zeros((height, width), dtype=np.uint8)

        for x, y, w, h in text_boxes:
            padding = 10
            x1 = max(0, x - padding)
            y1 = max(0, y - padding)
            x2 = min(width, x + w + padding)
            y2 = min(height, y + h + padding)
            cv2.rectangle(text_mask, (x1, y1), (x2, y2), 255, -1)

        _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
        non_text = cv2.bitwise_and(cv2.bitwise_not(binary), cv2.bitwise_not(text_mask))

        contours, _ = cv2.findContours(non_text, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        image_boxes = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            area = w * h

            if area > min_area:
                aspect_ratio = w / h if h > 0 else 0
                if 0.2 < aspect_ratio < 5.0:
                    image_boxes.append((x, y, w, h))

        return image_boxes
