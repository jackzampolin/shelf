#!/usr/bin/env python3
"""
Test script to reproduce page 15 Agent 3 JSON parsing error
"""

import sys
from book_llm_process import LLMProcessor

def main():
    print("Testing page 15 Agent 3 verification...")
    print("=" * 60)

    processor = LLMProcessor("The-Accidental-President")

    # Process just page 15
    result = processor.process_page(15, 447)

    print("\n" + "=" * 60)
    print("✅ Processing completed")
    print(f"Result: {result}")

    # Check if debug file was created
    debug_file = processor.book_dir / "debug_page_0015_agent3_json_error.txt"
    if debug_file.exists():
        print(f"\n📝 Debug file created: {debug_file}")
        print("\nFirst 500 chars of debug output:")
        with open(debug_file) as f:
            print(f.read()[:500])
    else:
        print("\n✓ No JSON error this time!")

if __name__ == "__main__":
    main()