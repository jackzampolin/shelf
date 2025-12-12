"""Book metadata extraction CLI commands."""

import json
from infra.config import Config
from infra.pipeline.storage import Library


def cmd_metadata_extract(args):
    """Extract book metadata using web-search LLM."""
    from tools.metadata import extract_metadata, save_metadata

    library = Library(storage_root=Config.book_storage_root)
    storage = library.get_book_storage(args.scan_id)

    if not storage.exists:
        print(f"Error: Book '{args.scan_id}' not found")
        return

    print(f"Extracting metadata for: {args.scan_id}")
    print(f"  Model: {args.model or 'default (with web search)'}")
    print(f"  Pages: first {args.pages}")
    print()

    try:
        metadata = extract_metadata(
            storage,
            model=args.model,
            max_pages=args.pages,
        )

        print(f"Extracted metadata:")
        print(f"  Title:       {metadata.title}")
        if metadata.subtitle:
            print(f"  Subtitle:    {metadata.subtitle}")
        print(f"  Authors:     {', '.join(metadata.authors)}")
        if metadata.identifiers.isbn_13 or metadata.identifiers.isbn_10:
            isbn = metadata.identifiers.isbn_13 or metadata.identifiers.isbn_10
            print(f"  ISBN:        {isbn}")
        if metadata.publisher:
            print(f"  Publisher:   {metadata.publisher}")
        if metadata.publication_year:
            print(f"  Year:        {metadata.publication_year}")
        if metadata.subjects:
            print(f"  Subjects:    {', '.join(metadata.subjects[:5])}")
        if metadata.description:
            desc = metadata.description[:100] + "..." if len(metadata.description) > 100 else metadata.description
            print(f"  Description: {desc}")
        print(f"  Confidence:  {metadata.extraction_confidence:.0%}")
        print()

        if not args.dry_run:
            save_metadata(storage, metadata)
            print(f"Saved to: {storage.metadata_file}")
        else:
            print("(dry run - not saved)")

        if args.json:
            print()
            print(json.dumps(metadata.model_dump(exclude_none=True), indent=2, default=str))

    except Exception as e:
        print(f"Error: {e}")
        raise


def cmd_metadata_enrich(args):
    """Enrich metadata using Open Library API."""
    from tools.metadata import enrich_from_open_library, save_enriched_metadata

    library = Library(storage_root=Config.book_storage_root)
    storage = library.get_book_storage(args.scan_id)

    if not storage.exists:
        print(f"Error: Book '{args.scan_id}' not found")
        return

    print(f"Enriching metadata for: {args.scan_id}")

    try:
        metadata = enrich_from_open_library(storage)

        print(f"Enriched metadata:")
        print(f"  Title:       {metadata.title}")
        print(f"  Authors:     {', '.join(metadata.authors)}")
        if metadata.identifiers.isbn_13:
            print(f"  ISBN-13:     {metadata.identifiers.isbn_13}")
        if metadata.identifiers.open_library_id:
            print(f"  Open Lib ID: {metadata.identifiers.open_library_id}")
        if metadata.cover_url:
            print(f"  Cover URL:   {metadata.cover_url}")
        if metadata.subjects_lcsh:
            print(f"  LCSH:        {', '.join(metadata.subjects_lcsh[:5])}")
        if metadata.first_publish_year:
            print(f"  First Pub:   {metadata.first_publish_year}")
        print()

        if not args.dry_run:
            save_enriched_metadata(storage, metadata)
            print(f"Saved to: {storage.metadata_file}")
        else:
            print("(dry run - not saved)")

        if args.json:
            print()
            print(json.dumps(metadata.model_dump(exclude_none=True), indent=2, default=str))

    except Exception as e:
        print(f"Error: {e}")
        raise


def cmd_metadata_show(args):
    """Show current book metadata."""
    library = Library(storage_root=Config.book_storage_root)
    storage = library.get_book_storage(args.scan_id)

    if not storage.exists:
        print(f"Error: Book '{args.scan_id}' not found")
        return

    try:
        metadata = storage.load_metadata()
    except FileNotFoundError:
        print(f"No metadata found for: {args.scan_id}")
        return

    if args.json:
        print(json.dumps(metadata, indent=2, default=str))
    else:
        print(f"Metadata for: {args.scan_id}")
        print()
        for key, value in metadata.items():
            if value is not None and value != [] and value != {}:
                if isinstance(value, list):
                    value = ", ".join(str(v) for v in value[:5])
                    if len(metadata.get(key, [])) > 5:
                        value += "..."
                elif isinstance(value, dict):
                    value = json.dumps(value)
                print(f"  {key}: {value}")
