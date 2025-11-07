import sys

from infra.pipeline.storage.library import Library
from infra.config import Config


def cmd_delete(args):
    library = Library(storage_root=Config.book_storage_root)
    scan = library.get_scan_info(args.scan_id)

    if not scan:
        print(f"❌ Book not found: {args.scan_id}")
        sys.exit(1)

    if not args.yes:
        scan_dir = Config.book_storage_root / args.scan_id
        print(f"\n⚠️  WARNING: This will DELETE all files for:")
        print(f"   Scan ID: {args.scan_id}")
        print(f"   Title:   {scan.get('title', args.scan_id)}")
        print(f"   Author:  {scan.get('author', 'Unknown')}")
        print(f"   Directory: {scan_dir}")

        try:
            response = input("\nAre you sure? (yes/no): ").strip().lower()
            if response not in ['yes', 'y']:
                print("Cancelled.")
                sys.exit(0)
        except EOFError:
            print("\n❌ Cancelled (no input)")
            sys.exit(0)

    try:
        result = library.delete_book(scan_id=args.scan_id)
        print(f"\n✅ Deleted: {result['scan_id']}")
        print(f"   Files deleted from: {result['scan_dir']}")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
