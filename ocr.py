import logging
import numpy as np
from PIL import Image
import easyocr
from io import BytesIO
from typing import Optional

logger = logging.getLogger(__name__)

# Initialize EasyOCR reader globally (it's expensive to create)
# Support Ukrainian, Russian, and English
reader = None

def get_reader():
    """Get or create EasyOCR reader instance"""
    global reader
    if reader is None:
        try:
            # Initialize with Ukrainian, Russian, and English
            reader = easyocr.Reader(['uk', 'ru', 'en'], gpu=False)
            logger.info("EasyOCR reader initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize EasyOCR reader: {e}")
            reader = False  # Mark as failed to avoid retrying
    return reader if reader is not False else None


def extract_text_from_image(image_bytes: bytes) -> Optional[str]:
    """
    Extract text from image using EasyOCR
    This runs in a thread pool to avoid blocking
    """
    try:
        # Get EasyOCR reader
        ocr_reader = get_reader()
        if not ocr_reader:
            logger.error("EasyOCR reader not available")
            return None
        
        # Open image from bytes
        image = Image.open(BytesIO(image_bytes))
        
        # Convert to RGB if necessary
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        # Convert PIL image to numpy array for EasyOCR
        image_array = np.array(image)
        
        # Extract text using EasyOCR
        results = ocr_reader.readtext(
            image_array,
            detail=1,  # Return confidence scores
            paragraph=True,  # Group text into paragraphs
            width_ths=0.7,  # Text width threshold
            height_ths=0.7,  # Text height threshold
        )
        
        if not results:
            logger.info("No text found in image")
            return None
        
        # Process results and extract text with confidence filtering
        text_parts = []
        total_confidence = 0
        
        for result in results:
            # Handle different return formats from EasyOCR
            if len(result) == 3:
                bbox, text, confidence = result
            elif len(result) == 2:
                bbox, text = result
                confidence = 1.0  # Default confidence if not provided
            else:
                logger.warning(f"Unexpected EasyOCR result format: {result}")
                continue
                
            # Filter out low-confidence results (< 0.3)
            if confidence > 0.3:
                text = text.strip()
                if text:  # Only add non-empty text
                    text_parts.append(text)
                    total_confidence += confidence
        
        if not text_parts:
            logger.info("No high-confidence text found in image")
            return None
        
        # Join text parts with spaces, preserving line breaks where appropriate
        extracted_text = ' '.join(text_parts)
        
        # Clean up the text
        lines = []
        for line in extracted_text.split('.'):
            line = line.strip()
            if line and len(line) > 2:  # Filter out very short fragments
                lines.append(line)
        
        final_text = '. '.join(lines)
        if final_text and not final_text.endswith('.'):
            final_text += '.'
        
        avg_confidence = total_confidence / len(text_parts) if text_parts else 0
        
        logger.info(f"Extracted {len(final_text)} characters from image (avg confidence: {avg_confidence:.2f})")
        return final_text if final_text else None
        
    except Exception as e:
        logger.error(f"Error extracting text from image: {e}")
        return None