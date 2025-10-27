// Labels Viewer - Canvas Drawing Logic

function drawBoundingBoxes() {
    const img = document.getElementById('page-image');
    const canvas = document.getElementById('bbox-canvas');

    if (!img || !canvas) return;

    const ctx = canvas.getContext('2d');

    // Match canvas size to image display size
    canvas.width = img.offsetWidth;
    canvas.height = img.offsetHeight;

    // Get image dimensions from data attributes
    const imgWidth = parseInt(img.dataset.width);
    const imgHeight = parseInt(img.dataset.height);

    if (!imgWidth || !imgHeight) return;

    // Calculate scale
    const scaleX = canvas.width / imgWidth;
    const scaleY = canvas.height / imgHeight;

    // Get block type colors
    const colors = getBlockTypeColors();

    // Draw each block
    if (window.labelData && window.labelData.blocks && window.ocrData && window.ocrData.blocks) {
        window.ocrData.blocks.forEach((block, idx) => {
            const bbox = block.bbox;
            const labelBlock = window.labelData.blocks[idx];

            if (!bbox || !labelBlock) return;

            // Scale coordinates
            const x = bbox.x0 * scaleX;
            const y = bbox.y0 * scaleY;
            const width = (bbox.x1 - bbox.x0) * scaleX;
            const height = (bbox.y1 - bbox.y0) * scaleY;

            // Get color for this block type
            const blockType = labelBlock.classification || 'BODY';
            const color = colors[blockType] || colors['BODY'];

            // Draw rectangle
            ctx.strokeStyle = color;
            ctx.lineWidth = 2;
            ctx.strokeRect(x, y, width, height);

            // Fill with semi-transparent color
            ctx.fillStyle = color.replace('1)', '0.1)');
            ctx.fillRect(x, y, width, height);

            // Draw block number
            ctx.fillStyle = color.replace('1)', '0.9)');
            ctx.font = '14px sans-serif';
            ctx.fillText(String(idx + 1), x + 5, y + 18);
        });
    }
}

function getBlockTypeColors() {
    return {
        'CHAPTER_HEADING': 'rgba(231, 76, 60, 1)',      // Red
        'SECTION_HEADING': 'rgba(230, 126, 34, 1)',     // Orange
        'BODY': 'rgba(52, 152, 219, 1)',                // Blue
        'HEADER': 'rgba(149, 165, 166, 1)',             // Gray
        'FOOTER': 'rgba(149, 165, 166, 1)',             // Gray
        'PAGE_NUMBER': 'rgba(142, 68, 173, 1)',         // Purple
        'FOOTNOTE': 'rgba(241, 196, 15, 1)',            // Yellow
        'ENDNOTES': 'rgba(241, 196, 15, 1)',            // Yellow
        'QUOTE': 'rgba(26, 188, 156, 1)',               // Teal
        'TITLE_PAGE': 'rgba(46, 204, 113, 1)',          // Green
        'TABLE_OF_CONTENTS': 'rgba(155, 89, 182, 1)',   // Purple
        'COPYRIGHT': 'rgba(127, 140, 141, 1)',          // Dark Gray
        'DEDICATION': 'rgba(236, 240, 241, 1)',         // Light Gray
        'EPIGRAPH': 'rgba(52, 73, 94, 1)',              // Dark Blue
        'INTRODUCTION': 'rgba(41, 128, 185, 1)',        // Medium Blue
        'EPILOGUE': 'rgba(192, 57, 43, 1)',             // Dark Red
        'ACKNOWLEDGMENTS': 'rgba(39, 174, 96, 1)',      // Green
        'INDEX': 'rgba(211, 84, 0, 1)',                 // Orange
        'ILLUSTRATION_CAPTION': 'rgba(243, 156, 18, 1)',// Yellow-Orange
        'PHOTO_CREDIT': 'rgba(189, 195, 199, 1)',       // Light Gray
        'OCR_ARTIFACT': 'rgba(231, 76, 60, 0.5)',       // Transparent Red
        'OTHER': 'rgba(149, 165, 166, 0.7)',            // Transparent Gray
    };
}

// Redraw on window resize
window.addEventListener('resize', drawBoundingBoxes);

// Draw on page load
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        // Wait for image to load
        const img = document.getElementById('page-image');
        if (img) {
            if (img.complete) {
                drawBoundingBoxes();
            } else {
                img.addEventListener('load', drawBoundingBoxes);
            }
        }
    });
} else {
    // DOM already loaded
    const img = document.getElementById('page-image');
    if (img) {
        if (img.complete) {
            drawBoundingBoxes();
        } else {
            img.addEventListener('load', drawBoundingBoxes);
        }
    }
}
